import unittest

import external_evidence


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class ExternalEvidenceTests(unittest.TestCase):
    def test_pubtator_bioc_parser_keeps_only_gene_identifiers(self):
        payload = {"PubTator3": [{
            "id": "12345678",
            "passages": [{
                "annotations": [
                    {"infons": {"type": "Gene", "identifier": "7157"}},
                    {"infons": {"type": "Gene", "identifier": "NCBI Gene:7422"}},
                    {"infons": {"type": "Disease", "identifier": "MESH:D000544"}},
                ],
            }],
        }]}
        self.assertEqual(
            external_evidence._pubtator_gene_ids(payload),
            {"12345678": {"7157", "7422"}},
        )

    def test_ncbi_gene_parser_restricts_results_to_human_official_symbols(self):
        payload = {
            "result": {
                "uids": ["7157", "22059"],
                "7157": {
                    "organism": {"taxid": 9606, "scientificname": "Homo sapiens"},
                    "nomenclaturesymbol": "TP53",
                    "name": "TP53",
                },
                "22059": {"taxid": 10090, "nomenclaturesymbol": "Trp53", "name": "Trp53"},
            },
        }
        self.assertEqual(external_evidence._human_gene_symbols(payload), {"7157": "TP53"})

    def test_fetch_joins_pubtator_ids_to_human_ncbi_gene_symbols(self):
        responses = iter([
            _FakeResponse([{
                "id": "12345678",
                "passages": [{"annotations": [
                    {"infons": {"type": "Gene", "identifier": "7157"}},
                    {"infons": {"type": "Gene", "identifier": "22059"}},
                ]}],
            }]),
            _FakeResponse({
                "result": {
                    "uids": ["7157", "22059"],
                    "7157": {"organism": {"taxid": 9606}, "nomenclaturesymbol": "TP53"},
                    "22059": {"taxid": 10090, "nomenclaturesymbol": "Trp53"},
                },
            }),
        ])

        def fake_get(*_args, **_kwargs):
            return next(responses)

        result = external_evidence.fetch_pubtator_gene_annotations(
            ["12345678"],
            http_get=fake_get,
            sleep=lambda _seconds: None,
        )
        self.assertEqual(result, {"12345678": ["TP53"]})

    def test_excludes_submitted_and_intersection_genes(self):
        pathway = {
            "intersection_genes": ["APP", "APOE"],
            "literature": [{"pmid": "11111111"}, {"pmid": "22222222"}],
        }
        annotations = {
            "11111111": ["APP", "TREM2", "PLCG2"],
            "22222222": ["TREM2", "RIN3", "BAD SYMBOL"],
        }

        entries = external_evidence.build_external_evidence_genes(
            pathway,
            input_genes=["APP", "APOE", "PLCG2"],
            annotations_by_pmid=annotations,
        )

        self.assertEqual([entry["gene"] for entry in entries], ["TREM2", "RIN3"])
        self.assertEqual(entries[0]["pmids"], ["11111111", "22222222"])
        self.assertEqual(entries[0]["evidence_count"], 2)

    def test_ties_are_stable_and_maximum_is_enforced(self):
        pathway = {
            "intersection_genes": [],
            "literature": [{"pmid": "33333333"}],
        }
        entries = external_evidence.build_external_evidence_genes(
            pathway,
            annotations_by_pmid={"33333333": ["TYROBP", "CD9", "LGALS3"]},
            max_genes=2,
        )
        self.assertEqual([entry["gene"] for entry in entries], ["CD9", "LGALS3"])

    def test_attachment_is_optional_auditable_and_never_ranking_evidence(self):
        pathway = {
            "intersection_genes": ["GENE1"],
            "literature": [{"pmid": "44444444"}],
        }
        external_evidence.attach_external_evidence_genes(
            [pathway],
            input_genes=["GENE1"],
            annotations_by_pmid={"44444444": ["GENE2"]},
        )

        self.assertEqual(pathway["external_evidence_genes"][0]["gene"], "GENE2")
        self.assertFalse(pathway["external_evidence_provenance"]["used_for_ranking"])
        self.assertIn("not used for enrichment", pathway["external_evidence_note"])
        self.assertIn("PubTator3", pathway["external_evidence_provenance"]["source"])

    def test_empty_regeneration_removes_stale_external_evidence(self):
        pathway = {
            "intersection_genes": ["GENE1"],
            "literature": [],
            "external_evidence_genes": [{"gene": "STALE"}],
            "external_evidence_note": "stale",
            "external_evidence_provenance": {"used_for_ranking": False},
        }
        external_evidence.attach_external_evidence_genes(
            [pathway],
            input_genes=["GENE1"],
            annotations_by_pmid={},
        )

        self.assertNotIn("external_evidence_genes", pathway)
        self.assertNotIn("external_evidence_note", pathway)
        self.assertNotIn("external_evidence_provenance", pathway)


if __name__ == "__main__":
    unittest.main()
