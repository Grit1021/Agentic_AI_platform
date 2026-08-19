import contextlib
import io
import os
import unittest
import warnings

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


class MessageSession:
    def __init__(self):
        self.retained_pathways = []
        self.messages = []

    def add_message(self, message_type, content, data=None):
        self.messages.append({"type": message_type, "content": content, "data": data})


class ValidationMetricTests(unittest.TestCase):
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
