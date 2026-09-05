import json
import tempfile
import unittest
from pathlib import Path

from archive_lock import apply_pinned_ad, load_pinned_ad, sync_bundled_archives


ROOT = Path(__file__).resolve().parent
PIN = ROOT / "web_app" / "pinned_ad_example.json"


class ArchiveLockTests(unittest.TestCase):
    def test_pin_is_the_approved_old_ad_example(self):
        example = load_pinned_ad(PIN)
        self.assertEqual(example["gene_count"], 140)
        self.assertEqual(example["pathway_count"], 16)
        self.assertEqual(example["result"]["pathways"][0]["name"], "neuroinflammatory response")

    def test_apply_pin_replaces_a_newer_ad_example(self):
        payload = {"default": "MS", "examples": {"AD": {"code": "AD", "gene_count": 152}}}
        apply_pinned_ad(payload, PIN)
        self.assertEqual(payload["default"], "AD")
        self.assertEqual(payload["examples"]["AD"]["gene_count"], 140)

    def test_sync_keeps_completed_and_demo_ad_identical(self):
        payload = {"default": "AD", "examples": {"AD": load_pinned_ad(PIN)}}
        with tempfile.TemporaryDirectory() as tmp:
            sync_bundled_archives(tmp, payload)
            completed = json.loads((Path(tmp) / "offline_completed_examples.json").read_text())
            demo = json.loads((Path(tmp) / "offline_demo_data.json").read_text())
            self.assertEqual(completed["examples"]["AD"]["result"], demo)


if __name__ == "__main__":
    unittest.main()
