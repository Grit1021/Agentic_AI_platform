import os
import unittest
from unittest.mock import patch

from quota_manager import QuotaExceeded, QuotaManager


class QuotaManagerMemoryTests(unittest.TestCase):
    def build_manager(self, user_limit=3, global_limit=30):
        env = {
            "QUOTA_ENABLED": "true",
            "QUOTA_BACKEND": "memory",
            "USER_DAILY_JOB_LIMIT": str(user_limit),
            "GLOBAL_DAILY_JOB_LIMIT": str(global_limit),
        }
        with patch.dict(os.environ, env, clear=False):
            return QuotaManager()

    def test_user_daily_limit_is_enforced(self):
        manager = self.build_manager(user_limit=2, global_limit=10)
        manager.reserve("user-a")
        status = manager.reserve("user-a")
        self.assertEqual(status["user_remaining"], 0)
        with self.assertRaises(QuotaExceeded) as raised:
            manager.reserve("user-a")
        self.assertEqual(raised.exception.scope, "user")

    def test_global_daily_limit_is_enforced_across_users(self):
        manager = self.build_manager(user_limit=5, global_limit=2)
        manager.reserve("user-a")
        manager.reserve("user-b")
        with self.assertRaises(QuotaExceeded) as raised:
            manager.reserve("user-c")
        self.assertEqual(raised.exception.scope, "global")

    def test_per_user_override_is_enforced_and_can_be_reset(self):
        manager = self.build_manager(user_limit=3, global_limit=20)
        manager.set_user_limit("reader@example.com", 1)
        status = manager.reserve("owner-reader", "reader@example.com")
        self.assertEqual(status["user_limit"], 1)
        self.assertEqual(status["user_limit_source"], "override")
        with self.assertRaises(QuotaExceeded):
            manager.reserve("owner-reader", "reader@example.com")

        manager.set_user_limit("reader@example.com", None)
        reset_status = manager.status("owner-reader", "reader@example.com")
        self.assertEqual(reset_status["user_limit"], 3)
        self.assertEqual(reset_status["user_limit_source"], "default")

    def test_admin_snapshot_does_not_expose_owner_ids(self):
        manager = self.build_manager(user_limit=3, global_limit=20)
        manager.register_user("cognito-subject", "reader@example.com")
        manager.reserve("cognito-subject", "reader@example.com")
        snapshot = manager.admin_snapshot(["reader@example.com", "new@example.com"])

        self.assertEqual(snapshot["global_used"], 1)
        self.assertEqual(snapshot["users"][0]["email"], "new@example.com")
        reader = next(user for user in snapshot["users"] if user["email"] == "reader@example.com")
        self.assertTrue(reader["registered"])
        self.assertEqual(reader["used"], 1)
        self.assertNotIn("owner_id", reader)


if __name__ == "__main__":
    unittest.main()
