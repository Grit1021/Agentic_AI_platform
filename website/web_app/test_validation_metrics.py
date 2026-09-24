import contextlib
import io
import os
import sys
import types
import unittest
import warnings
from unittest.mock import MagicMock, patch

import jinja2
import markupsafe
import pandas as pd

# The workstation's legacy Flask test runtime predates Jinja 3.  Keep this
# compatibility shim test-only; production uses the pinned Beanstalk runtime.
if not hasattr(jinja2, "escape"):
    jinja2.escape = markupsafe.escape
if not hasattr(jinja2, "Markup"):
    jinja2.Markup = markupsafe.Markup
if not hasattr(markupsafe, "soft_unicode"):
    markupsafe.soft_unicode = markupsafe.soft_str

os.environ["AUTH_ENABLED"] = "false"
os.environ["QUOTA_ENABLED"] = "false"

warnings.filterwarnings("ignore")
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    import server
    import cell_context
    import pathway_narrative


class MessageSession:
    def __init__(self):
        self.retained_pathways = []
        self.messages = []

    def add_message(self, message_type, content, data=None):
        self.messages.append({"type": message_type, "content": content, "data": data})


class ValidationMetricTests(unittest.TestCase):
    def test_result_conversion_retains_all_validated_pathways_and_contexts(self):
        rows = []
        category_counts = {
            "GO:BP": 8,
            "GO:MF": 4,
            "GO:CC": 4,
            "KEGG": 4,
            "REAC": 4,
        }
        for category, count in category_counts.items():
            for index in range(count):
                rows.append({
                    "name": f"{category} pathway {index + 1}",
                    "native": f"{category}:{index + 1}",
                    "source": category,
                    "p_value": 0.001 * (index + 1),
                    "description": f"Description {index + 1}",
                    "intersections": ["GENE1", "GENE2"],
                    "intersection_size": 2,
                    "term_size": 20,
                    "query_size": 100,
                    "gpt_rank": index + 1,
                    "gpt_validated": True,
                })

        with (
            patch.object(server.cell_context_module, "attach_cell_context") as attach_context,
            patch.object(server.cell_context_module, "attach_cell_context_evidence") as attach_context_evidence,
            patch.object(server, "attach_pathway_narratives") as attach_narratives,
            patch.object(server.external_evidence, "attach_external_evidence_genes") as attach_external,
        ):
            records = server.convert_pathways_to_output_format(
                pd.DataFrame(rows),
                "Test disease",
                input_genes=["GENE1", "GENE2"],
            )

        self.assertEqual(len(records), 24)
        self.assertEqual(
            sum(record["category"] == "GO:BP" for record in records),
            8,
        )
        highlighted = [
            record for record in records
            if record["has_detailed_interpretation"]
        ]
        self.assertEqual(len(highlighted), 20)
        self.assertEqual(
            sum(record["category"] == "GO:BP" for record in highlighted),
            4,
        )
        self.assertEqual(len(attach_context.call_args.args[0]), 24)
        self.assertEqual(len(attach_context_evidence.call_args.args[0]), 24)
        self.assertEqual(len(attach_narratives.call_args.args[0]), 20)
        self.assertEqual(len(attach_external.call_args.args[0]), 20)

    def test_iterative_output_attaches_post_fdr_cell_context_and_external_evidence(self):
        pathways = pd.DataFrame([{
            "name": "test pathway",
            "native": "GO:0000001",
            "source": "GO:BP",
            "p_value": 0.001,
            "description": "A test pathway.",
            "intersections": ["GENE1"],
            "intersection_size": 1,
            "term_size": 10,
            "query_size": 3,
            "related_literature": [{
                "pmid": "12345678",
                "title": "GENE2 in test disease",
            }],
        }])

        with (
            patch.object(server.cell_context_module, "attach_cell_context") as attach_context,
            patch.object(server, "attach_pathway_narratives") as attach_narratives,
            patch.object(server.external_evidence, "attach_external_evidence_genes") as attach_external,
        ):
            records = server.convert_pathways_to_output_format(
                pathways,
                "Test disease",
                input_genes=["GENE1", "GENE3", "GENE4"],
            )

        self.assertEqual(len(records), 1)
        attach_context.assert_called_once_with(
            records,
            "Test disease",
            genes=["GENE1", "GENE3", "GENE4"],
            progress=None,
        )
        attach_narratives.assert_called_once_with(records, "Test disease", progress=None)
        attach_external.assert_called_once_with(
            records,
            input_genes=["GENE1", "GENE3", "GENE4"],
        )

    def test_iterative_result_contract_contains_context_and_auditable_external_gene(self):
        pathways = pd.DataFrame([{
            "name": "test pathway",
            "native": "GO:0000001",
            "source": "GO:BP",
            "p_value": 0.001,
            "description": "A test pathway.",
            "intersections": ["GENE1"],
            "intersection_size": 1,
            "term_size": 10,
            "query_size": 3,
            "related_literature": [{
                "pmid": "12345678",
                "title": "GENE2 in test disease",
            }],
        }])

        with (
            patch.object(
                server.cell_context_module,
                "generate_pathway_cell_context",
                return_value={"test pathway": "Disease-relevant test cells."},
            ),
            patch.object(server, "attach_pathway_narratives"),
            patch.object(
                server.external_evidence,
                "fetch_pubtator_gene_annotations",
                return_value={"12345678": ["GENE1", "GENE2"]},
            ),
        ):
            records = server.convert_pathways_to_output_format(
                pathways,
                "Test disease",
                input_genes=["GENE1", "GENE3", "GENE4"],
            )

        self.assertEqual(records[0]["cell_context"], "Disease-relevant test cells.")
        self.assertEqual(
            records[0]["cell_context_provenance"]["stage"],
            "post-validation",
        )
        self.assertEqual(
            [entry["gene"] for entry in records[0]["external_evidence_genes"]],
            ["GENE2"],
        )
        self.assertEqual(
            records[0]["external_evidence_genes"][0]["pmids"],
            ["12345678"],
        )

    def test_driver_genes_remain_in_their_functional_clusters(self):
        clusters = pathway_narrative.dedupe_narrative_clusters(
            [
                {
                    "label": "microglial and lysosomal immune-regulatory cluster",
                    "genes": ["GRN", "CTSC"],
                },
                {
                    "label": "proteolytic extracellular matrix remodeling cluster",
                    "genes": ["MMP8", "MMP9"],
                },
                {
                    "label": "myeloid chemoattractant and vascular activation cluster",
                    "genes": ["AZU1"],
                },
            ],
            driver_genes=["GRN", "MMP9", "CTSC"],
        )

        self.assertEqual(clusters[0]["genes"], ["GRN", "CTSC"])
        self.assertEqual(clusters[1]["genes"], ["MMP8", "MMP9"])
        self.assertEqual(clusters[2]["genes"], ["AZU1"])

    def test_functional_cluster_deduplication_is_only_cross_cluster(self):
        clusters = pathway_narrative.dedupe_narrative_clusters(
            [
                {"label": "A", "genes": ["GRN", "CTSC"]},
                {"label": "B", "genes": ["GRN", "MMP8"]},
            ],
            driver_genes=["GRN"],
        )

        self.assertEqual(
            clusters,
            [
                {"label": "A", "genes": ["GRN", "CTSC"]},
                {"label": "B", "genes": ["MMP8"]},
            ],
        )

    def test_narrative_paragraph_pmids_require_real_title_overlap(self):
        mappings = pathway_narrative.map_narrative_paragraph_pmids(
            [
                "IL2RA signaling helps regulate T cell activation.",
                "The enrichment statistic is reported separately.",
            ],
            [
                {
                    "pmid": "12345",
                    "title": "IL2RA control of T cell activation in autoimmunity",
                },
                {
                    "pmid": "67890",
                    "title": "Lipid metabolism in hepatocytes",
                },
            ],
        )

        self.assertEqual(mappings[0], ["12345"])
        self.assertEqual(mappings[1], [])

    def test_large_narrative_prompt_uses_full_intersection_count(self):
        genes = [f"GENE{index}" for index in range(1, 234)]
        prompt = pathway_narrative.build_pathway_narrative_prompt({
            "name": "protein ubiquitination",
            "pathway_id": "GO:0016567",
            "source": "GO:BP",
            "intersection_size": 233,
            "intersection_genes": genes,
        }, "Rheumatoid Arthritis")

        self.assertIn("Full intersection size: 233", prompt)
        self.assertIn("must be 233", prompt)
        self.assertIn("Only the first 60 resolved symbols", prompt)
        self.assertNotIn("must be 60", prompt)

    def test_truncated_narrative_json_recovers_complete_paragraphs(self):
        parsed = pathway_narrative.parse_narrative_reply(
            '{"paragraphs":["Opening paragraph.","Protein paragraph.","Closing paragraph."'
        )

        self.assertEqual(len(parsed["paragraphs"]), 3)
        self.assertTrue(parsed["_recovered_from_truncation"])

    def test_narrative_sanitizer_removes_model_protocol_leakage(self):
        polluted = (
            "6 submitted disease-associated genes were significantly enriched in this pathway. "
            'driver_genes":[],"clusters":[]} ``` **Note**: incorrectly formatted '
            "due to constraints in this environment."
        )
        clean = pathway_narrative.sanitize_narrative_paragraph(polluted)
        self.assertEqual(
            clean,
            "6 submitted disease-associated genes were significantly enriched in this pathway.",
        )
        self.assertNotIn("driver_genes", clean)

    def test_narrative_sanitizer_polishes_formulaic_closing_prose(self):
        clean = pathway_narrative.sanitize_narrative_paragraph(
            "Taken together, enrichment of GRN and MMP9 indicates that this term "
            "captures a substantial component of neuroinflammation. The association "
            "appears to be primarily driven by GRN and MMP9. Overall, these proteins "
            "link immune regulation and matrix remodeling."
        )

        self.assertTrue(clean.startswith("Enrichment of GRN and MMP9 highlights"))
        self.assertIn("The principal driver genes are GRN and MMP9.", clean)
        self.assertIn("These genes link immune regulation", clean)
        self.assertNotIn("Taken together", clean)
        self.assertNotIn("Overall", clean)

    def test_takeaway_does_not_add_overall_or_taken_together(self):
        takeaway = server.polish_takeaway_text(
            "Overall, taken together, enrichment of GRN and MMP9 supports a "
            "neuroinflammatory interpretation. A second direct sentence follows."
        )

        self.assertEqual(
            takeaway,
            "Enrichment of GRN and MMP9 supports a neuroinflammatory interpretation. "
            "A second direct sentence follows.",
        )

    def test_cell_context_pmids_are_not_treated_as_claim_level_evidence(self):
        pathway = {
            "cell_context": "Relevant to microglia and cortex.",
            "cell_context_pmids": ["39062547"],
        }
        self.assertEqual(server.normalize_cell_context_claim_evidence(pathway), [])

        pathway["cell_context_evidence"] = [{
            "label": "Microglia",
            "claim": "Plaque-associated microglia show this program.",
            "pmids": ["39062547"],
        }]
        self.assertEqual(
            server.normalize_cell_context_claim_evidence(pathway),
            [{
                "claim": "Plaque-associated microglia show this program.",
                "labels": ["Microglia"],
                "genes": [],
                "pmids": ["39062547"],
            }],
        )

    def test_cell_context_label_extraction_matches_browser_contract(self):
        labels = cell_context.extract_cell_context_labels(
            "Plaque-associated microglia and reactive astrocytes in hippocampal "
            "and cortical regions are most relevant."
        )
        self.assertEqual(labels, ["Microglia", "Astrocytes", "Hippocampus", "Cortex"])

    def test_cell_context_references_are_mapped_to_labels_and_genes(self):
        records = [{
            "name": "neuroinflammatory response",
            "cell_context": "Most relevant to microglia and astrocytes in the hippocampus.",
            "intersection_genes": ["GRN", "MMP9"],
        }]
        papers = [{
            "pmid": "30862089",
            "title": "Microglial progranulin in Alzheimer disease",
            "journal": "Cells",
            "year": "2019",
            "matched_labels": ["Microglia"],
            "matched_genes": ["GRN"],
            "query_basis": "disease-cell-gene",
        }]
        with patch.object(
            server.pubmed_search,
            "search_pubmed_for_cell_context_standalone",
            return_value=("Found 1 cell-context reference", papers),
        ) as search:
            cell_context.attach_cell_context_evidence(
                records,
                "Alzheimer's Disease",
                # Archived inputs can remain Ensembl IDs while the validated
                # pathway intersection is already normalized to HGNC symbols.
                genes=["ENSG00000030582", "ENSG00000100985"],
            )

        search.assert_called_once_with(
            ["Microglia", "Astrocytes", "Hippocampus"],
            "Alzheimer's Disease",
            ["GRN", "MMP9"],
            pathway_name="neuroinflammatory response",
            max_results=3,
        )
        self.assertEqual(records[0]["cell_context_evidence"], [{
            "labels": ["Microglia"],
            "genes": ["GRN"],
            "pmids": ["30862089"],
            "query_basis": "disease-cell-gene",
        }])
        self.assertEqual(records[0]["cell_context_literature"][0]["pmid"], "30862089")

    def test_narrative_generation_retries_transient_failure(self):
        record = {
            "name": "test pathway",
            "pathway_id": "GO:0000001",
            "source": "GO:BP",
            "intersection_size": 2,
            "intersection_genes": ["GENE1", "GENE2"],
        }
        candidate = {
            "paragraphs": [
                "2 disease-associated proteins were significantly enriched in test pathway (GO:0000001).",
                "GENE1 and GENE2 provide the supplied molecular support.",
                "GENE1 is the principal driver of this result.",
            ],
            "driver_genes": ["GENE1"],
            "clusters": [{"label": "Supplied support", "genes": ["GENE2"]}],
            "discussed_genes": ["GENE1", "GENE2"],
            "generated": True,
        }
        original_key = pathway_narrative.OPENAI_API_KEY
        fake_openai = types.SimpleNamespace(OpenAI=lambda api_key: object())
        pathway_narrative.OPENAI_API_KEY = "test-key"
        try:
            with (
                patch.dict(sys.modules, {"openai": fake_openai}),
                patch.object(
                    pathway_narrative,
                    "_request_pathway_narrative",
                    side_effect=[RuntimeError("temporary upstream failure"), candidate],
                ),
            ):
                narratives = pathway_narrative.generate_pathway_narratives(
                    [record], "Test disease", max_pathways=1
                )
        finally:
            pathway_narrative.OPENAI_API_KEY = original_key

        payload = narratives["GO:0000001"]
        self.assertTrue(payload["generated"])
        self.assertEqual(payload["generation_attempts"], 2)

    def test_gpt5_narrative_request_uses_default_temperature(self):
        completion = MagicMock()
        completion.create.return_value = types.SimpleNamespace(
            choices=[types.SimpleNamespace(
                finish_reason="stop",
                message=types.SimpleNamespace(content=(
                    '{"paragraphs":["2 disease-associated proteins were significantly enriched '
                    'in test pathway (GO:0000001).","GENE1 and GENE2 provide the supplied molecular '
                    'support.","GENE1 is the principal driver of this result."],'
                    '"driver_genes":["GENE1"],"clusters":[{"label":"Supplied support",'
                    '"genes":["GENE2"]}],"discussed_genes":["GENE1","GENE2"]}'
                )),
            )]
        )
        client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=completion)
        )
        pathway_narrative._request_pathway_narrative(
            client,
            {
                "name": "test pathway",
                "pathway_id": "GO:0000001",
                "source": "GO:BP",
                "intersection_size": 2,
                "intersection_genes": ["GENE1", "GENE2"],
            },
            "Test disease",
            [],
        )

        request_kwargs = completion.create.call_args.kwargs
        self.assertNotIn("temperature", request_kwargs)
        self.assertEqual(request_kwargs["response_format"]["type"], "json_schema")

    def test_narrative_safety_repair_rephrases_background_symbols(self):
        record = {
            "name": "test pathway",
            "pathway_id": "REAC:R-HSA-0000001",
            "source": "REAC",
            "intersection_size": 2,
            "intersection_genes": ["GENE1", "GENE2"],
        }
        candidate = {
            "paragraphs": [
                "2 submitted disease-associated proteins were enriched in test pathway.",
                "GENE1 links IL-2 and CD4 signalling to GENE2 in this record.",
                "GENE1 is the principal driver of the pathway association.",
            ],
            "driver_genes": ["GENE1"],
            "clusters": [{"label": "Supplied support", "genes": ["GENE2"]}],
            "discussed_genes": ["GENE1", "GENE2"],
            "generated": True,
        }

        repaired = pathway_narrative.repair_narrative_candidate(
            candidate,
            record,
            "Test disease",
        )

        self.assertEqual(pathway_narrative.validate_narrative(repaired, record), [])
        self.assertIn("interleukin-2", repaired["paragraphs"][1])
        self.assertIn("cluster-of-differentiation 4", repaired["paragraphs"][1])
        self.assertEqual(
            repaired["deterministic_repair"]["unsupported_symbols_rephrased"],
            ["IL-2", "CD4"],
        )

    def test_narrative_safety_repair_restores_disjoint_cluster(self):
        record = {
            "name": "test pathway",
            "pathway_id": "GO:0000001",
            "source": "GO:BP",
            "intersection_size": 2,
            "intersection_genes": ["GENE1", "GENE2"],
        }
        candidate = {
            "paragraphs": [
                "2 submitted disease-associated proteins were enriched in test pathway.",
                "GENE1 and GENE2 provide the supplied intersection evidence.",
                "GENE1 is the principal driver of the pathway association.",
            ],
            "driver_genes": ["GENE1"],
            "clusters": [],
            "discussed_genes": ["GENE1", "GENE2"],
            "generated": True,
        }

        repaired = pathway_narrative.repair_narrative_candidate(
            candidate,
            record,
            "Test disease",
        )

        self.assertEqual(pathway_narrative.validate_narrative(repaired, record), [])
        self.assertEqual(
            repaired["clusters"],
            [{"label": "Additional intersection support", "genes": ["GENE2"]}],
        )

    def test_narrative_safety_repair_sanitizes_pathway_name_in_opening(self):
        record = {
            "name": "JAK-STAT signaling pathway",
            "pathway_id": "KEGG:04630",
            "source": "KEGG",
            "intersection_size": 2,
            "intersection_genes": ["GENE1", "GENE2"],
        }
        candidate = {
            "paragraphs": [
                "2 submitted disease-associated proteins were enriched in this pathway.",
                "GENE1 and GENE2 provide the supplied intersection evidence.",
                "GENE1 is the principal driver of the pathway association.",
            ],
            "driver_genes": ["GENE1"],
            "clusters": [{"label": "Supplied support", "genes": ["GENE2"]}],
            "generated": True,
        }

        repaired = pathway_narrative.repair_narrative_candidate(
            candidate,
            record,
            "Test disease",
        )

        self.assertEqual(pathway_narrative.validate_narrative(repaired, record), [])
        self.assertNotIn("JAK-STAT", repaired["paragraphs"][0])
        self.assertIn("cytokine-receptor signal transduction", repaired["paragraphs"][0])

    def test_cell_context_retries_only_pathways_missing_from_first_pass(self):
        pathways = [
            {"name": f"Pathway {index}", "source": "GO:BP", "genes": ["GENE1"]}
            for index in range(1, 10)
        ]
        calls = []
        original_complete = cell_context._complete
        original_key = cell_context.OPENAI_API_KEY

        def partial_then_complete(prompt, disease_name, max_tokens):
            names = [
                line.split(". ", 1)[1]
                for line in prompt.splitlines()
                if line.startswith("P") and line[1:2].isdigit() and ". " in line
            ]
            calls.append(names)
            if len(calls) <= 2:
                names = names[:-1]
            return "\n".join(
                f"- P{index}: Relevant disease cell context."
                for index, name in enumerate(names, 1)
            )

        cell_context.OPENAI_API_KEY = "test-key"
        cell_context._complete = partial_then_complete
        try:
            resolved = cell_context.generate_pathway_cell_context(pathways, "Test disease")
        finally:
            cell_context._complete = original_complete
            cell_context.OPENAI_API_KEY = original_key

        self.assertEqual(set(resolved), {pathway["name"] for pathway in pathways})
        self.assertEqual(calls[:2], [
            [f"Pathway {index}" for index in range(1, 9)],
            ["Pathway 9"],
        ])
        self.assertEqual(calls[2], ["Pathway 8", "Pathway 9"])

    def test_cell_context_parser_maps_stable_pathway_ids(self):
        resolved = cell_context.parse_cell_context_lines(
            "- **P1**: Intestinal epithelial cells.\n- P2 — Lamina propria macrophages.",
            ["Long pathway name (GO:123)", "Another pathway"],
        )

        self.assertEqual(resolved, {
            "Long pathway name (GO:123)": "Intestinal epithelial cells.",
            "Another pathway": "Lamina propria macrophages.",
        })

    def test_pathway_interpretation_extracts_cell_context_as_separate_field(self):
        interpretation = (
            "Biological context: Calcium signaling supports synaptic function.\n"
            "Gene-level support: CALM1 is in the input-pathway intersection.\n"
            "Disease relevance: Calcium dyshomeostasis is relevant to Alzheimer's disease.\n"
            "Cell/tissue context: Excitatory neurons in the hippocampus and cortex. [PMID:12345]"
        )

        points = server.parse_pathway_interpretation(interpretation)

        self.assertEqual(len(points), 4)
        self.assertEqual(points[-1]["label"], "Cell/tissue context")
        self.assertEqual(
            server.extract_pathway_cell_context(interpretation),
            "Excitatory neurons in the hippocampus and cortex.",
        )

    def test_pathway_interpretation_supports_five_plus_one_output_labels(self):
        interpretation = (
            "Disease pathology and relevance: Relevant to Alzheimer's disease.\n"
            "Intersection-gene interpretation: CALM1 supports the pathway.\n"
            "PubMed literature synthesis: Two pathway-disease records were retrieved.\n"
            "Cell/tissue context: Hippocampal excitatory neurons."
        )

        points = server.parse_pathway_interpretation(interpretation)

        self.assertEqual(
            [point["label"] for point in points],
            [
                "Disease pathology and relevance",
                "Intersection-gene interpretation",
                "PubMed literature synthesis",
                "Cell/tissue context",
            ],
        )
        self.assertEqual(
            server.extract_pathway_cell_context(interpretation),
            "Hippocampal excitatory neurons.",
        )

    def test_normalized_pathway_record_keeps_cell_context_out_of_standard_points(self):
        records = server.normalize_pathway_records([{
            "name": "calcium ion binding",
            "description": (
                "Biological context: Calcium-dependent signaling.\n"
                "Gene-level support: CALM1.\n"
                "Disease relevance: Relevant to AD.\n"
                "Cell context: Hippocampal excitatory neurons."
            ),
        }])

        self.assertEqual(records[0]["cell_context"], "Hippocampal excitatory neurons.")
        self.assertEqual(
            [point["label"] for point in records[0]["interpretation_points"]],
            ["Biological context", "Gene-level support", "Disease relevance"],
        )

    def test_validation_rate_uses_unique_matched_hypotheses_as_denominator(self):
        self.assertEqual(server.hypothesis_validation_rate(7, 10), 70.0)
        self.assertEqual(server.hypothesis_validation_rate(0, 0), 0.0)
        with self.assertRaises(ValueError):
            server.hypothesis_validation_rate(11, 10)

    def test_multiple_term_records_count_as_one_hypothesis(self):
        details = {
            "vesicle transport": {"id": "", "source": "GO:BP"},
        }
        enrichment = pd.DataFrame([
            {
                "name": "vesicle transport",
                "native": "GO:0016192",
                "source": "GO:BP",
                "p_value": 0.01,
            },
            {
                "name": "vesicle transport",
                "native": "GO:0006886",
                "source": "GO:BP",
                "p_value": 0.20,
            },
        ])

        matched, stats = server.match_gpt_with_gprofiler_detailed(
            ["vesicle transport"], details, enrichment
        )

        self.assertEqual(len(matched), 2)
        self.assertEqual(stats["GO:BP"]["predicted"], 1)
        self.assertEqual(stats["GO:BP"]["matched"], 1)
        self.assertEqual(stats["GO:BP"]["fdr_filtered"], 1)
        self.assertEqual(stats["GO:BP"]["matched_records"], 2)
        self.assertEqual(stats["GO:BP"]["fdr_records"], 1)

    def test_matching_is_restricted_to_the_same_database(self):
        details = {
            "autophagy": {"id": "", "source": "GO:BP"},
        }
        enrichment = pd.DataFrame([
            {
                "name": "autophagy",
                "native": "GO:0006914",
                "source": "GO:BP",
                "p_value": 0.01,
            },
            {
                "name": "autophagy",
                "native": "GO:0003674",
                "source": "GO:MF",
                "p_value": 0.01,
            },
        ])

        matched, stats = server.match_gpt_with_gprofiler_detailed(
            ["autophagy"], details, enrichment
        )

        self.assertEqual(len(matched), 1)
        self.assertEqual(stats["GO:BP"]["matched"], 1)
        self.assertEqual(stats["GO:MF"]["matched"], 0)

    def test_aliases_with_the_same_database_id_are_one_unique_hypothesis(self):
        details = {
            "autophagy": {"id": "GO:0006914", "source": "GO:BP"},
            "autophagic process": {"id": "GO:0006914", "source": "GO:BP"},
        }
        enrichment = pd.DataFrame([{
            "name": "autophagy",
            "native": "GO:0006914",
            "source": "GO:BP",
            "p_value": 0.01,
        }])

        _, stats = server.match_gpt_with_gprofiler_detailed(
            list(details), details, enrichment
        )

        self.assertEqual(stats["GO:BP"]["predicted"], 2)
        self.assertEqual(stats["GO:BP"]["matched"], 1)
        self.assertEqual(stats["GO:BP"]["fdr_filtered"], 1)

    def test_unmatched_enrichment_records_are_not_hypothesis_validations(self):
        details = {
            "autophagy": {"id": "GO:0006914", "source": "GO:BP"},
        }
        enrichment = pd.DataFrame([{
            "name": "calcium ion binding",
            "native": "GO:0005509",
            "source": "GO:MF",
            "p_value": 0.001,
        }])

        matched, stats = server.match_gpt_with_gprofiler_detailed(
            list(details), details, enrichment
        )

        self.assertTrue(matched.empty)
        self.assertEqual(stats["GO:BP"]["matched"], 0)
        self.assertEqual(stats["GO:MF"]["fdr_filtered"], 0)

    def test_second_round_rate_uses_newly_matched_hypotheses(self):
        session = MessageSession()
        category_stats = {
            category: {
                "predicted": 0,
                "matched": 0,
                "fdr_filtered": 0,
                "new_matched": 0,
                "new_fdr": 0,
                "matched_records": 0,
                "fdr_records": 0,
                "new_matched_records": 0,
                "new_fdr_records": 0,
            }
            for category in ["GO:BP", "GO:MF", "GO:CC", "KEGG", "REAC"]
        }
        category_stats["GO:BP"].update({
            "predicted": 4,
            "matched": 3,
            "fdr_filtered": 2,
            "new_matched": 2,
            "new_fdr": 1,
            "matched_records": 6,
            "fdr_records": 4,
            "new_matched_records": 4,
            "new_fdr_records": 2,
        })

        summary = server.display_iteration_stats(
            session, 2, category_stats, 0, 4, 6, 4
        )

        self.assertEqual(summary["matched_hypotheses"], 2)
        self.assertEqual(summary["statistically_validated_hypotheses"], 1)
        self.assertEqual(summary["validation_rate"], 50.0)
        self.assertIn(
            "4 generated → 2 matched → 1 statistically validated (50.0% of matched hypotheses)",
            session.messages[-1]["content"],
        )


if __name__ == "__main__":
    unittest.main()
