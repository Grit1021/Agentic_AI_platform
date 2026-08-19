import os
import contextlib
import io
import unittest
import warnings
from unittest.mock import Mock, patch

import jinja2
import markupsafe

# The workstation's Flask version predates Jinja 3; production uses the
# pinned Beanstalk dependency set. Keep this compatibility shim test-only.
if not hasattr(jinja2, "escape"):
    jinja2.escape = markupsafe.escape
if not hasattr(jinja2, "Markup"):
    jinja2.Markup = markupsafe.Markup
if not hasattr(markupsafe, "soft_unicode"):
    markupsafe.soft_unicode = markupsafe.soft_str

os.environ["AUTH_ENABLED"] = "false"
os.environ["QUOTA_ENABLED"] = "true"
os.environ["QUOTA_BACKEND"] = "memory"
os.environ["USER_DAILY_JOB_LIMIT"] = "1"
os.environ["GLOBAL_DAILY_JOB_LIMIT"] = "10"
os.environ["MAX_CONCURRENT_JOBS"] = "1"

warnings.filterwarnings("ignore")
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    import server


class CompletedThread:
    """Test double that hands the concurrency slot back without running GPT."""

    def __init__(self, target=None, args=(), **kwargs):
        self.target = target
        self.args = args
        self.daemon = False

    def start(self):
        server.release_job_slot()


class ServerLimitTests(unittest.TestCase):
    def setUp(self):
        server.sessions.clear()
        server.quota_manager._memory.clear()
        server._disease_search_cache.clear()
        server._gene_search_cache.clear()
        self.client = server.app.test_client()

    def test_disease_search_preserves_open_targets_ranking(self):
        upstream = Mock()
        upstream.raise_for_status.return_value = None
        upstream.json.return_value = {
            "data": {
                "search": {
                    "hits": [
                        {
                            "id": "MONDO_0005502",
                            "name": "dengue disease",
                            "entity": "disease",
                            "description": "Dengue fever (DF), caused by dengue virus.",
                        },
                        {
                            "id": "MONDO_0006717",
                            "name": "cutaneous fibrous histiocytoma",
                            "entity": "disease",
                            "description": "A mesenchymal neoplasm.",
                        },
                    ]
                }
            }
        }

        with patch.object(server.requests, "post", return_value=upstream):
            response = self.client.get("/api/disease-search?q=df")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["source"], "Open Targets")
        self.assertEqual(payload["results"][0]["name"], "dengue disease")
        self.assertEqual(payload["results"][0]["id"], "MONDO_0005502")
        self.assertIn("MONDO_0005502", payload["results"][0]["url"])

    def test_gene_search_prefers_short_symbol_prefix_and_returns_ensembl_id(self):
        upstream = Mock()
        upstream.raise_for_status.return_value = None
        upstream.json.return_value = {
            "data": {
                "search": {
                    "hits": [
                        {
                            "id": "ENSG00000117118",
                            "name": "SDHB",
                            "entity": "target",
                            "description": "succinate dehydrogenase complex iron sulfur subunit B",
                        },
                        {
                            "id": "ENSG00000135094",
                            "name": "SDS",
                            "entity": "target",
                            "description": "serine dehydratase",
                        },
                        {
                            "id": "ENSG00000234684",
                            "name": "SDCBP2-AS1",
                            "entity": "target",
                            "description": "SDCBP2 antisense RNA 1",
                        },
                    ]
                }
            }
        }

        with patch.object(server.requests, "post", return_value=upstream):
            response = self.client.get("/api/gene-search?q=sd")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["source"], "Open Targets")
        self.assertEqual(payload["results"][0]["symbol"], "SDS")
        self.assertEqual(payload["results"][0]["ensembl_id"], "ENSG00000135094")
        self.assertEqual(payload["results"][-1]["symbol"], "SDCBP2-AS1")

    def test_second_daily_submission_is_rejected(self):
        payload = {"genes": ["APOE", "APP", "PSEN1"], "disease": "AD"}
        with patch.object(server.threading, "Thread", CompletedThread):
            first = self.client.post("/api/analyze", json=payload)
            second = self.client.post("/api/analyze", json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.get_json()["code"], "user_daily_limit")

    def test_session_progress_is_owner_scoped(self):
        analysis = server.AnalysisSession(
            "owned-session",
            ["APOE", "APP", "PSEN1"],
            "AD",
            owner_id="owner-a",
        )
        server.sessions[analysis.session_id] = analysis
        with self.client.session_transaction() as browser_session:
            browser_session["user"] = {
                "sub": "owner-b",
                "email": "other@example.com",
            }
        with (
            patch.object(server, "AUTH_ENABLED", True),
            patch.object(server, "ACCESS_MODE", "public"),
        ):
            response = self.client.get("/api/progress/owned-session")
        self.assertEqual(response.status_code, 404)

    def test_archived_demo_pdf_export_returns_a_valid_pdf(self):
        response = self.client.get("/api/export/85bd55b2/pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertTrue(response.data.startswith(b"%PDF-"))
        self.assertGreater(len(response.data), 1_000)


if __name__ == "__main__":
    unittest.main()
