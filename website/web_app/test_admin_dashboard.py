import contextlib
import io
import os
import unittest
import warnings
from unittest import mock

import jinja2
import markupsafe

if not hasattr(jinja2, "escape"):
    jinja2.escape = markupsafe.escape
if not hasattr(jinja2, "Markup"):
    jinja2.Markup = markupsafe.Markup
if not hasattr(markupsafe, "soft_unicode"):
    markupsafe.soft_unicode = markupsafe.soft_str

os.environ["AUTH_ENABLED"] = "true"
os.environ["ACCESS_MODE"] = "team"
os.environ["ALLOWED_EMAILS"] = "admin@example.com,reader@example.com"
os.environ["ADMIN_EMAILS"] = "admin@example.com"
os.environ["QUOTA_ENABLED"] = "true"
os.environ["QUOTA_BACKEND"] = "memory"
os.environ["USER_DAILY_JOB_LIMIT"] = "3"
os.environ["GLOBAL_DAILY_JOB_LIMIT"] = "30"
os.environ["MAX_USER_DAILY_JOB_LIMIT"] = "20"

warnings.filterwarnings("ignore")
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    import server


class AdminDashboardTests(unittest.TestCase):
    def setUp(self):
        server.quota_manager._memory.clear()
        server.quota_manager._memory_limits.clear()
        server.quota_manager._memory_profiles.clear()
        self.client = server.app.test_client()

    def login(self, email, subject):
        with self.client.session_transaction() as browser_session:
            browser_session["user"] = {
                "sub": subject,
                "email": email,
                "name": email.split("@", 1)[0],
                "email_verified": True,
            }

    def test_non_admin_cannot_discover_dashboard_or_api(self):
        self.login("reader@example.com", "reader-sub")
        self.assertEqual(self.client.get("/admin").status_code, 404)
        self.assertEqual(self.client.get("/admin.js").status_code, 404)
        self.assertEqual(self.client.get("/api/admin/users").status_code, 403)
        identity = self.client.get("/api/auth/me").get_json()
        self.assertFalse(identity["is_admin"])

    def test_admin_page_and_identity_are_available_only_to_admin(self):
        self.login("admin@example.com", "admin-sub")
        page = self.client.get("/admin")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"User limits", page.data)
        page.close()
        identity = self.client.get("/api/auth/me").get_json()
        self.assertTrue(identity["is_admin"])

    def test_login_page_can_load_shared_public_assets(self):
        page = self.client.get("/login")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"/assets/components/site-footer.", page.data)
        self.assertIn(b'<meta name="asset-version"', page.data)
        page.close()
        favicon = self.client.get("/favicon.svg")
        footer = self.client.get("/components/site-footer.js")
        self.assertEqual(favicon.status_code, 200)
        self.assertEqual(footer.status_code, 200)
        favicon.close()
        footer.close()

    def test_successful_login_starts_tour_then_resumes_safe_deep_link(self):
        fake_cognito = mock.Mock()
        fake_cognito.authorize_access_token.return_value = {
            "userinfo": {
                "sub": "reader-sub",
                "email": "reader@example.com",
                "email_verified": True,
            }
        }
        with self.client.session_transaction() as browser_session:
            browser_session["post_login_next"] = "/?demo=1&example=AD"

        with mock.patch.object(server, "cognito_client", fake_cognito), mock.patch.object(
            server, "AUTH_CONFIG_READY", True
        ):
            response = self.client.get("/auth/callback")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"],
            "/?tour=1&after_tour=%2F%3Fdemo%3D1%26example%3DAD",
        )

    def test_post_login_tour_never_forwards_to_external_url(self):
        self.assertEqual(server.build_post_login_tour_url("//example.org/path"), "/?tour=1")
        self.assertEqual(server.build_post_login_tour_url("https://example.org"), "/?tour=1")

    def test_entry_point_is_hidden_until_admin_identity_is_loaded(self):
        self.login("reader@example.com", "reader-sub")
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'id="admin-dashboard-link" href="/admin" hidden', page.data)
        page.close()

    def test_admin_can_set_and_reset_an_allowed_users_limit(self):
        self.login("admin@example.com", "admin-sub")
        response = self.client.put(
            "/api/admin/users/reader@example.com/quota",
            json={"daily_limit": 1},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["user"]["limit"], 1)
        self.assertEqual(response.get_json()["user"]["limit_source"], "override")

        server.quota_manager.reserve("reader-sub", "reader@example.com")
        with self.assertRaises(server.QuotaExceeded):
            server.quota_manager.reserve("reader-sub", "reader@example.com")

        reset = self.client.put(
            "/api/admin/users/reader@example.com/quota",
            json={"daily_limit": None},
        )
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(reset.get_json()["user"]["limit"], 3)
        self.assertEqual(reset.get_json()["user"]["limit_source"], "default")

    def test_admin_cannot_manage_an_unlisted_email_or_invalid_limit(self):
        self.login("admin@example.com", "admin-sub")
        missing = self.client.put(
            "/api/admin/users/outsider@example.com/quota",
            json={"daily_limit": 5},
        )
        self.assertEqual(missing.status_code, 404)
        invalid = self.client.put(
            "/api/admin/users/reader@example.com/quota",
            json={"daily_limit": 99},
        )
        self.assertEqual(invalid.status_code, 400)


if __name__ == "__main__":
    unittest.main()
