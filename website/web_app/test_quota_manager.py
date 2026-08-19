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


if __name__ == "__main__":
    unittest.main()
