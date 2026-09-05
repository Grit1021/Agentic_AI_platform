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
from typing import Iterable

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
        self.max_user_daily_limit = _env_int("MAX_USER_DAILY_JOB_LIMIT", 200)
        self._client = None
        self._memory = {}
        self._memory_limits = {}
        self._memory_profiles = {}
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

    @staticmethod
    def _normalize_email(email: str) -> str:
        return str(email or "").strip().lower()

    @classmethod
    def _email_hash(cls, email: str) -> str:
        normalized = cls._normalize_email(email)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:40]

    @classmethod
    def _limit_key(cls, email: str) -> str:
        return f"USER_LIMIT#{cls._email_hash(email)}"

    @classmethod
    def _profile_key(cls, email: str) -> str:
        return f"USER_PROFILE#{cls._email_hash(email)}"

    def _dynamodb(self):
        if boto3 is None:
            raise QuotaUnavailable("boto3 is not installed")
        if not self.table_name:
            raise QuotaUnavailable("QUOTA_TABLE_NAME is not configured")
        if self._client is None:
            self._client = boto3.client("dynamodb", region_name=self.region)
        return self._client

    def _limit_from_item(self, item: dict | None) -> tuple[int, bool]:
        if not item or not item.get("override", {}).get("BOOL", False):
            return self.user_daily_limit, False
        try:
            value = int(item.get("daily_limit", {}).get("N", str(self.user_daily_limit)))
        except (TypeError, ValueError):
            return self.user_daily_limit, False
        return max(1, min(self.max_user_daily_limit, value)), True

    def _memory_user_limit(self, email: str) -> tuple[int, bool]:
        normalized = self._normalize_email(email)
        if not normalized or normalized not in self._memory_limits:
            return self.user_daily_limit, False
        return int(self._memory_limits[normalized]), True

    def _batch_get_items(self, keys: list[dict]) -> list[dict]:
        """Read DynamoDB records in bounded batches without requiring Scan."""
        if not keys:
            return []
        client = self._dynamodb()
        items = []
        unique = {key["pk"]["S"]: key for key in keys}
        pending = list(unique.values())
        while pending:
            chunk, pending = pending[:100], pending[100:]
            response = client.batch_get_item(
                RequestItems={
                    self.table_name: {
                        "Keys": chunk,
                        "ConsistentRead": True,
                    }
                }
            )
            items.extend(response.get("Responses", {}).get(self.table_name, []))
            unprocessed = (
                response.get("UnprocessedKeys", {})
                .get(self.table_name, {})
                .get("Keys", [])
            )
            if unprocessed:
                retry = client.batch_get_item(
                    RequestItems={
                        self.table_name: {
                            "Keys": unprocessed,
                            "ConsistentRead": True,
                        }
                    }
                )
                items.extend(retry.get("Responses", {}).get(self.table_name, []))
        return items

    def register_user(self, owner_id: str, email: str) -> None:
        """Remember the Cognito owner for an allowed email without scanning users."""
        normalized = self._normalize_email(email)
        owner_id = str(owner_id or "").strip()
        if not normalized or not owner_id or not self.enabled:
            return
        profile_key = self._profile_key(normalized)
        if self.backend == "memory":
            with self._memory_lock:
                self._memory_profiles[normalized] = owner_id
            return
        if self.backend != "dynamodb":
            raise QuotaUnavailable(f"Unsupported quota backend: {self.backend}")
        try:
            self._dynamodb().update_item(
                TableName=self.table_name,
                Key={"pk": {"S": profile_key}},
                UpdateExpression=(
                    "SET #kind = :kind, #owner = :owner, #updated = :updated"
                ),
                ExpressionAttributeNames={
                    "#kind": "record_type",
                    "#owner": "owner_id",
                    "#updated": "updated_at",
                },
                ExpressionAttributeValues={
                    ":kind": {"S": "user_profile"},
                    ":owner": {"S": owner_id},
                    ":updated": {"S": datetime.now(timezone.utc).isoformat()},
                },
            )
        except Exception as exc:
            raise QuotaUnavailable("User quota profile storage is unavailable") from exc

    def set_user_limit(self, email: str, daily_limit: int | None) -> dict:
        """Set or reset one allowed user's effective daily analysis limit."""
        normalized = self._normalize_email(email)
        if not normalized or "@" not in normalized:
            raise ValueError("A valid user email is required")
        is_override = daily_limit is not None
        if is_override:
            if isinstance(daily_limit, bool):
                raise ValueError("Daily limit must be an integer")
            if isinstance(daily_limit, float) and not daily_limit.is_integer():
                raise ValueError("Daily limit must be an integer")
            try:
                daily_limit = int(daily_limit)
            except (TypeError, ValueError) as exc:
                raise ValueError("Daily limit must be an integer") from exc
            if not 1 <= daily_limit <= self.max_user_daily_limit:
                raise ValueError(
                    f"Daily limit must be between 1 and {self.max_user_daily_limit}"
                )
        effective_limit = int(daily_limit) if is_override else self.user_daily_limit

        if self.backend == "memory":
            with self._memory_lock:
                if is_override:
                    self._memory_limits[normalized] = effective_limit
                else:
                    self._memory_limits.pop(normalized, None)
        elif self.backend == "dynamodb":
            try:
                self._dynamodb().update_item(
                    TableName=self.table_name,
                    Key={"pk": {"S": self._limit_key(normalized)}},
                    UpdateExpression=(
                        "SET #kind = :kind, #limit = :limit, #override = :override, "
                        "#updated = :updated"
                    ),
                    ExpressionAttributeNames={
                        "#kind": "record_type",
                        "#limit": "daily_limit",
                        "#override": "override",
                        "#updated": "updated_at",
                    },
                    ExpressionAttributeValues={
                        ":kind": {"S": "user_limit"},
                        ":limit": {"N": str(effective_limit)},
                        ":override": {"BOOL": is_override},
                        ":updated": {"S": datetime.now(timezone.utc).isoformat()},
                    },
                )
            except Exception as exc:
                raise QuotaUnavailable("User limit storage is unavailable") from exc
        else:
            raise QuotaUnavailable(f"Unsupported quota backend: {self.backend}")

        return {
            "email": normalized,
            "daily_limit": effective_limit,
            "limit_source": "override" if is_override else "default",
        }

    def admin_snapshot(self, emails: Iterable[str]) -> dict:
        """Return today's site and per-user usage for the configured team."""
        normalized_emails = sorted({
            self._normalize_email(email)
            for email in emails
            if self._normalize_email(email)
        })
        day, _, reset_at = self._day_context()
        global_key = f"GLOBAL#{day}"
        profiles = {}
        limits = {}
        user_counts = {}
        global_used = 0

        if self.enabled and self.backend == "memory":
            with self._memory_lock:
                profiles = dict(self._memory_profiles)
                limits = dict(self._memory_limits)
                global_used = int(self._memory.get(global_key, 0))
                for email, owner_id in profiles.items():
                    user_key, _ = self._keys(owner_id, day)
                    user_counts[email] = int(self._memory.get(user_key, 0))
        elif self.enabled and self.backend == "dynamodb":
            try:
                config_keys = [{"pk": {"S": global_key}}]
                for email in normalized_emails:
                    config_keys.extend([
                        {"pk": {"S": self._profile_key(email)}},
                        {"pk": {"S": self._limit_key(email)}},
                    ])
                config_items = self._batch_get_items(config_keys)
                by_key = {item.get("pk", {}).get("S", ""): item for item in config_items}
                global_used = int(by_key.get(global_key, {}).get("jobs", {}).get("N", "0"))
                usage_keys = []
                for email in normalized_emails:
                    profile = by_key.get(self._profile_key(email), {})
                    owner_id = profile.get("owner_id", {}).get("S", "")
                    if owner_id:
                        profiles[email] = owner_id
                        user_key, _ = self._keys(owner_id, day)
                        usage_keys.append({"pk": {"S": user_key}})
                    limit, is_override = self._limit_from_item(
                        by_key.get(self._limit_key(email))
                    )
                    if is_override:
                        limits[email] = limit
                usage_items = self._batch_get_items(usage_keys)
                usage_by_key = {
                    item.get("pk", {}).get("S", ""): item for item in usage_items
                }
                for email, owner_id in profiles.items():
                    user_key, _ = self._keys(owner_id, day)
                    user_counts[email] = int(
                        usage_by_key.get(user_key, {}).get("jobs", {}).get("N", "0")
                    )
            except Exception as exc:
                raise QuotaUnavailable("Admin quota data is unavailable") from exc
        elif self.enabled:
            raise QuotaUnavailable(f"Unsupported quota backend: {self.backend}")

        users = []
        for email in normalized_emails:
            limit = int(limits.get(email, self.user_daily_limit))
            used = int(user_counts.get(email, 0))
            users.append({
                "email": email,
                "registered": email in profiles,
                "used": used,
                "limit": limit,
                "remaining": max(0, limit - used),
                "limit_source": "override" if email in limits else "default",
            })

        return {
            "enabled": self.enabled,
            "day": day,
            "reset_at": reset_at,
            "default_user_limit": self.user_daily_limit,
            "max_user_limit": self.max_user_daily_limit,
            "global_limit": self.global_daily_limit,
            "global_used": global_used,
            "global_remaining": max(0, self.global_daily_limit - global_used),
            "users": users,
        }

    def status(self, owner_id: str, email: str = "") -> dict:
        day, _, reset_at = self._day_context()
        normalized_email = self._normalize_email(email)
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
        user_limit = self.user_daily_limit
        is_override = False
        if self.backend == "memory":
            with self._memory_lock:
                user_used = int(self._memory.get(user_key, 0))
                global_used = int(self._memory.get(global_key, 0))
                user_limit, is_override = self._memory_user_limit(normalized_email)
        elif self.backend == "dynamodb":
            try:
                keys = [
                    {"pk": {"S": user_key}},
                    {"pk": {"S": global_key}},
                ]
                if normalized_email:
                    keys.append({"pk": {"S": self._limit_key(normalized_email)}})
                response = self._dynamodb().batch_get_item(
                    RequestItems={
                        self.table_name: {
                            "Keys": keys,
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
            if normalized_email:
                by_key = {
                    item.get("pk", {}).get("S", ""): item
                    for item in items
                }
                user_limit, is_override = self._limit_from_item(
                    by_key.get(self._limit_key(normalized_email))
                )
        else:
            raise QuotaUnavailable(f"Unsupported quota backend: {self.backend}")

        return {
            "enabled": True,
            "day": day,
            "reset_at": reset_at,
            "user_limit": user_limit,
            "user_limit_source": "override" if is_override else "default",
            "user_used": user_used,
            "user_remaining": max(0, user_limit - user_used),
            "global_limit": self.global_daily_limit,
            "global_used": global_used,
            "global_remaining": max(0, self.global_daily_limit - global_used),
        }

    def reserve(self, owner_id: str, email: str = "") -> dict:
        if not self.enabled:
            return self.status(owner_id, email)

        day, expires_at, _ = self._day_context()
        user_key, global_key = self._keys(owner_id, day)
        normalized_email = self._normalize_email(email)
        if self.backend == "memory":
            exceeded_scope = None
            with self._memory_lock:
                user_limit, _ = self._memory_user_limit(normalized_email)
                user_used = int(self._memory.get(user_key, 0))
                global_used = int(self._memory.get(global_key, 0))
                if user_used >= user_limit:
                    exceeded_scope = "user"
                elif global_used >= self.global_daily_limit:
                    exceeded_scope = "global"
                else:
                    self._memory[user_key] = user_used + 1
                    self._memory[global_key] = global_used + 1
            if exceeded_scope:
                raise QuotaExceeded(exceeded_scope, self.status(owner_id, normalized_email))
            return self.status(owner_id, normalized_email)

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

        if normalized_email:
            try:
                limit_items = self._batch_get_items([
                    {"pk": {"S": self._limit_key(normalized_email)}}
                ])
                user_limit, _ = self._limit_from_item(limit_items[0] if limit_items else None)
            except Exception as exc:
                raise QuotaUnavailable("User limit storage is unavailable") from exc
        else:
            user_limit = self.user_daily_limit

        try:
            self._dynamodb().transact_write_items(
                TransactItems=[
                    update_item(user_key, user_limit, "user_daily"),
                    update_item(global_key, self.global_daily_limit, "global_daily"),
                ]
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "TransactionCanceledException":
                status = self.status(owner_id, normalized_email)
                if status["user_remaining"] <= 0:
                    raise QuotaExceeded("user", status) from exc
                if status["global_remaining"] <= 0:
                    raise QuotaExceeded("global", status) from exc
            raise QuotaUnavailable("Daily quota storage rejected the request") from exc
        except Exception as exc:
            raise QuotaUnavailable("Daily quota storage is unavailable") from exc

        return self.status(owner_id, normalized_email)
