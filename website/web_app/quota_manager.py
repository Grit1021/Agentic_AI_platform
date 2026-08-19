"""Durable daily job quotas for GenePathwayAI.

The production backend uses DynamoDB conditional transactions so per-user and
global limits cannot be bypassed by simultaneous submissions.  A memory backend
is available only for local tests and development.
"""

from __future__ import annotations

import hashlib
import os
import threading
from datetime import datetime, timedelta, timezone

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover - exercised on minimal local previews
    boto3 = None

    class ClientError(Exception):
        """Fallback type used when boto3 is intentionally absent."""


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


class QuotaExceeded(Exception):
    def __init__(self, scope: str, status: dict):
        self.scope = scope
        self.status = status
        if scope == "user":
            message = "You have reached your daily analysis limit."
        else:
            message = "The site has reached its daily analysis limit. Please try again tomorrow."
        super().__init__(message)


class QuotaUnavailable(Exception):
    pass


class QuotaManager:
    def __init__(self):
        self.enabled = _env_bool("QUOTA_ENABLED", False)
        self.backend = os.environ.get("QUOTA_BACKEND", "dynamodb").strip().lower()
        self.table_name = os.environ.get("QUOTA_TABLE_NAME", "").strip()
        self.region = os.environ.get("AWS_REGION", os.environ.get("COGNITO_REGION", "us-east-1"))
        self.user_daily_limit = _env_int("USER_DAILY_JOB_LIMIT", 3)
        self.global_daily_limit = _env_int("GLOBAL_DAILY_JOB_LIMIT", 30)
        self._client = None
        self._memory = {}
        self._memory_lock = threading.Lock()

    @staticmethod
    def _day_context(now: datetime | None = None) -> tuple[str, int, str]:
        now = now or datetime.now(timezone.utc)
        day = now.strftime("%Y-%m-%d")
        next_day = datetime(now.year, now.month, now.day, tzinfo=timezone.utc) + timedelta(days=1)
        expires_at = int((next_day + timedelta(days=2)).timestamp())
        return day, expires_at, next_day.isoformat().replace("+00:00", "Z")

    @staticmethod
    def _owner_hash(owner_id: str) -> str:
        return hashlib.sha256(owner_id.encode("utf-8")).hexdigest()[:40]

    def _keys(self, owner_id: str, day: str) -> tuple[str, str]:
        return f"USER#{day}#{self._owner_hash(owner_id)}", f"GLOBAL#{day}"

    def _dynamodb(self):
        if boto3 is None:
            raise QuotaUnavailable("boto3 is not installed")
        if not self.table_name:
            raise QuotaUnavailable("QUOTA_TABLE_NAME is not configured")
        if self._client is None:
            self._client = boto3.client("dynamodb", region_name=self.region)
        return self._client

    def status(self, owner_id: str) -> dict:
        day, _, reset_at = self._day_context()
        if not self.enabled:
            return {
                "enabled": False,
                "day": day,
                "reset_at": reset_at,
                "user_limit": self.user_daily_limit,
                "user_used": 0,
                "user_remaining": self.user_daily_limit,
                "global_limit": self.global_daily_limit,
                "global_used": 0,
                "global_remaining": self.global_daily_limit,
            }

        user_key, global_key = self._keys(owner_id, day)
        if self.backend == "memory":
            with self._memory_lock:
                user_used = int(self._memory.get(user_key, 0))
                global_used = int(self._memory.get(global_key, 0))
        elif self.backend == "dynamodb":
            try:
                response = self._dynamodb().batch_get_item(
                    RequestItems={
                        self.table_name: {
                            "Keys": [
                                {"pk": {"S": user_key}},
                                {"pk": {"S": global_key}},
                            ],
                            "ConsistentRead": True,
                        }
                    }
                )
            except Exception as exc:
                raise QuotaUnavailable("Daily quota storage is unavailable") from exc
            items = response.get("Responses", {}).get(self.table_name, [])
            counts = {
                item.get("pk", {}).get("S", ""): int(item.get("jobs", {}).get("N", "0"))
                for item in items
            }
            user_used = counts.get(user_key, 0)
            global_used = counts.get(global_key, 0)
        else:
            raise QuotaUnavailable(f"Unsupported quota backend: {self.backend}")

        return {
            "enabled": True,
            "day": day,
            "reset_at": reset_at,
            "user_limit": self.user_daily_limit,
            "user_used": user_used,
            "user_remaining": max(0, self.user_daily_limit - user_used),
            "global_limit": self.global_daily_limit,
            "global_used": global_used,
            "global_remaining": max(0, self.global_daily_limit - global_used),
        }

    def reserve(self, owner_id: str) -> dict:
        if not self.enabled:
            return self.status(owner_id)

        day, expires_at, _ = self._day_context()
        user_key, global_key = self._keys(owner_id, day)
        if self.backend == "memory":
            exceeded_scope = None
            with self._memory_lock:
                user_used = int(self._memory.get(user_key, 0))
                global_used = int(self._memory.get(global_key, 0))
                if user_used >= self.user_daily_limit:
                    exceeded_scope = "user"
                elif global_used >= self.global_daily_limit:
                    exceeded_scope = "global"
                else:
                    self._memory[user_key] = user_used + 1
                    self._memory[global_key] = global_used + 1
            if exceeded_scope:
                raise QuotaExceeded(exceeded_scope, self.status(owner_id))
            return self.status(owner_id)

        if self.backend != "dynamodb":
            raise QuotaUnavailable(f"Unsupported quota backend: {self.backend}")

        def update_item(key: str, limit: int, kind: str) -> dict:
            return {
                "Update": {
                    "TableName": self.table_name,
                    "Key": {"pk": {"S": key}},
                    "UpdateExpression": (
                        "SET #expires = :expires, #day = :day, #kind = :kind "
                        "ADD #jobs :one"
                    ),
                    "ConditionExpression": "attribute_not_exists(#jobs) OR #jobs < :limit",
                    "ExpressionAttributeNames": {
                        "#expires": "expires_at",
                        "#day": "quota_day",
                        "#kind": "record_type",
                        "#jobs": "jobs",
                    },
                    "ExpressionAttributeValues": {
                        ":expires": {"N": str(expires_at)},
                        ":day": {"S": day},
                        ":kind": {"S": kind},
                        ":one": {"N": "1"},
                        ":limit": {"N": str(limit)},
                    },
                }
            }

        try:
            self._dynamodb().transact_write_items(
                TransactItems=[
                    update_item(user_key, self.user_daily_limit, "user_daily"),
                    update_item(global_key, self.global_daily_limit, "global_daily"),
                ]
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "TransactionCanceledException":
                status = self.status(owner_id)
                if status["user_remaining"] <= 0:
                    raise QuotaExceeded("user", status) from exc
                if status["global_remaining"] <= 0:
                    raise QuotaExceeded("global", status) from exc
            raise QuotaUnavailable("Daily quota storage rejected the request") from exc
        except Exception as exc:
            raise QuotaUnavailable("Daily quota storage is unavailable") from exc

        return self.status(owner_id)
