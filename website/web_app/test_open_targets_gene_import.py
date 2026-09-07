import contextlib
import io
import os
import unittest
from unittest.mock import patch

import jinja2
import markupsafe

if not hasattr(jinja2, "escape"):
    jinja2.escape = markupsafe.escape
if not hasattr(jinja2, "Markup"):
    jinja2.Markup = markupsafe.Markup
if not hasattr(markupsafe, "soft_unicode"):
    markupsafe.soft_unicode = markupsafe.soft_str

os.environ["AUTH_ENABLED"] = "false"
os.environ["QUOTA_ENABLED"] = "false"

with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    import server


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class OpenTargetsGeneImportTests(unittest.TestCase):
    def setUp(self):
        server._associated_gene_cache.clear()
        self.client = server.app.test_client()

    def test_accepts_custom_limit(self):
        with patch("server.requests.post") as post:
            post.return_value = _FakeResponse({
                "data": {"disease": {
                    "id": "HP_0003124",
                    "name": "Hypercholesterolemia",
                    "associatedTargets": {"count": 0, "rows": []},
                }}
            })
            response = self.client.get(
                "/api/open-targets/associated-genes?disease_id=HP_0003124&limit=522"
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(post.call_args.kwargs["json"]["variables"]["size"], 522)

    def test_rejects_limit_below_minimum(self):
        response = self.client.get(
            "/api/open-targets/associated-genes?disease_id=HP_0003124&limit=24"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Limit must be at least 25")

    def test_requires_ontology_identifier(self):
        response = self.client.get(
            "/api/open-targets/associated-genes?disease_id=hypercholesterolemia&limit=100"
        )
        self.assertEqual(response.status_code, 400)

    @patch("server.requests.post")
    def test_returns_ranked_unique_gene_symbols(self, post):
        post.return_value = _FakeResponse({
            "data": {
                "disease": {
                    "id": "HP_0003124",
                    "name": "Hypercholesterolemia",
                    "associatedTargets": {
                        "count": 2342,
                        "rows": [
                            {
                                "score": 0.819,
                                "target": {
                                    "id": "ENSG00000169174",
                                    "approvedSymbol": "PCSK9",
                                    "approvedName": "proprotein convertase subtilisin/kexin type 9",
                                },
                            },
                            {
                                "score": 0.846,
                                "target": {
                                    "id": "ENSG00000130164",
                                    "approvedSymbol": "LDLR",
                                    "approvedName": "low density lipoprotein receptor",
                                },
                            },
                            {
                                "score": 0.5,
                                "target": {
                                    "id": "ENSG00000130164",
                                    "approvedSymbol": "LDLR",
                                    "approvedName": "duplicate",
                                },
                            },
                        ],
                    },
                }
            }
        })

        response = self.client.get(
            "/api/open-targets/associated-genes?disease_id=HP:0003124&limit=100"
        )
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["disease"]["id"], "HP_0003124")
        self.assertEqual([gene["symbol"] for gene in payload["genes"]], ["LDLR", "PCSK9"])
        self.assertEqual(payload["returned_count"], 2)
        self.assertEqual(payload["ranking"], "overall association score")
        self.assertEqual(post.call_args.kwargs["timeout"], 18)
        self.assertEqual(post.call_args.kwargs["json"]["variables"], {
            "efoId": "HP_0003124",
            "size": 100,
        })


if __name__ == "__main__":
    unittest.main()
