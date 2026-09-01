import json
from pathlib import Path
from unittest import TestCase

from app.config import ROOT_DIR


class OpenReelGateATests(TestCase):
    def test_gate_a_records_the_pinned_source_and_authority_boundary(self):
        manifest = json.loads(
            (ROOT_DIR / "docs" / "third_party_sources.json").read_text()
        )
        source = next(
            item
            for item in manifest["reviewed_sources"]
            if item["name"] == "OpenReel Video"
        )

        self.assertEqual(
            source["revision"],
            "5f3c85e5fc223c86060bf4b12e1b4dec58e9b8a9",
        )
        self.assertEqual(source["status"], "adapted_integration_overlay")
        adaptation = next(
            item for item in manifest["adapted_sources"]
            if item["name"] == "OpenReel Video"
        )
        self.assertEqual(adaptation["revision"], source["revision"])
        for relative_path in adaptation["pbj_files"]:
            self.assertTrue((ROOT_DIR / relative_path).exists(), relative_path)
        self.assertIn("No editing feature is reimplemented", adaptation["modifications"])

        contract = (ROOT_DIR / "docs" / "OPENREEL_ADAPTER_CONTRACT.md").read_text()
        for required_boundary in (
            "whole-project snapshot",
            "OpenReel owns the editor",
            "There is no per-tool PBJ transaction requirement",
            "unpermissioned media is rejected",
            "The backend final-approval gate is implemented",
        ):
            self.assertIn(required_boundary, contract)

    def test_evaluation_checkout_is_ignored(self):
        ignore_rules = (ROOT_DIR / ".gitignore").read_text().splitlines()
        self.assertIn(".evaluations/", ignore_rules)


if __name__ == "__main__":
    import unittest

    unittest.main()
