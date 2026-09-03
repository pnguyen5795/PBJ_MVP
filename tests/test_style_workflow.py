import asyncio
import tempfile
import unittest
from pathlib import Path

from app.providers.base import ProviderReadiness
from app.providers.pegasus import PegasusAnalyzer
from app.contracts import VIDEO_ANALYSIS_JSON_SCHEMA
from app.storage import JsonStore
from app.workflows import ProjectAnalysisWorkflow, StyleWorkflow, failure_fields


def analysis(file_id, provider="gemini"):
    return {
        "schema_version": "1.0", "file_id": file_id, "provider": provider,
        "model": "test-model", "remote_asset": {"id": provider + "-asset", "status": "ready", "retained": True},
        "usage": {},
        "analysis": {
            "summary": "A quick finished edit", "content_type": "short",
            "speakers": ["speaker"], "story_beats": ["hook", "payoff"],
            "segments": [{
                "segment_id": "segment-001", "start_seconds": 0, "end_seconds": 1,
                "transcript": "Hello", "visual_description": "Speaker smiles",
                "audio_description": "Clean dialogue", "subjects": ["speaker"],
                "actions": ["smiles"], "shot_type": "close-up", "camera_movement": "static",
                "emotional_tone": "energetic", "editorial_roles": ["hook"],
                "quality": "strong", "duplicate_group": None, "confidence": 0.9,
            }],
            "editing_observations": {key: [] for key in ["opening", "pacing", "shot_pattern", "cut_pattern", "reframing", "b_roll", "transitions", "speed", "audio_continuity", "ending", "other"]},
            "uncertainties": [],
        },
    }


class FakeAnalyzer:
    def __init__(self, provider):
        self.provider = provider
        self.calls = 0

    def readiness(self):
        return ProviderReadiness(self.provider, True, "Ready")

    def cache_identity(self):
        return {"model": "test-model", "prompt_version": "video-analysis-v1"}

    async def analyze(self, path, file_id, purpose):
        self.calls += 1
        return analysis(file_id, self.provider)


class FlakyAnalyzer(FakeAnalyzer):
    async def analyze(self, path, file_id, purpose):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary provider failure")
        return analysis(file_id, self.provider)


class InvalidAnalyzer(FakeAnalyzer):
    async def analyze(self, path, file_id, purpose):
        self.calls += 1
        result = analysis(file_id, self.provider)
        result["analysis"]["segments"][0]["confidence"] = 2
        return result


class MinimumDurationAnalyzer(FakeAnalyzer):
    minimum_duration_seconds = 4.0


class ProviderApiError(Exception):
    def __init__(self):
        super().__init__("headers: {'authorization': 'secret'}, status_code: 400, body: video too short")
        self.status_code = 400
        self.body = {
            "code": "video_duration_too_short",
            "message": "The video is too short. Please use a video with duration at least 4 seconds. Current duration is 0.5 seconds.",
        }
        self.headers = {"authorization": "secret", "x-trace-id": "trace-123"}


class FakeDecisionEngine:
    async def synthesize_style(self, analyses):
        rule = {
            "rule_id": "rule-001", "category": "structure", "name": "Fast hook",
            "description": "Starts immediately", "instruction": "Open on the strongest moment",
            "classification": "core", "condition": "At the opening", "exceptions": [],
            "renderer_support": "supported", "supporting_reference_count": 1,
            "total_reference_count": 1, "confidence": 0.9,
            "evidence": [{"reference_file_id": "reference-001", "segment_id": "segment-001", "start_seconds": 0, "end_seconds": 1, "observation": "The finished edit opens immediately."}],
            "conflicts": [],
        }
        return {"summary": "Fast, direct editing", "creative_principles": ["Start strong"], "structure_summary": "Hook then payoff", "compatibility": ["Short videos"], "avoid": ["Slow openings"], "rules": [rule], "unsupported_observations": [], "uncertainties": [], "synthesis": {"provider": "fake"}}

    async def revise_style(self, style_analysis, feedback):
        revised = dict(style_analysis)
        revised["summary"] = "Revised: " + feedback
        return revised


class StyleWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = JsonStore(self.root / "data")
        reference = self.root / "reference.mp4"
        reference.write_bytes(b"reference")
        self.style = self.store.create_style("Style", [reference], {str(reference): {"duration_seconds": 2}})
        self.gemini = FakeAnalyzer("gemini")
        self.pegasus = FakeAnalyzer("pegasus")
        self.workflow = StyleWorkflow(self.store, {"gemini": self.gemini, "pegasus": self.pegasus}, FakeDecisionEngine())

    def tearDown(self):
        self.temp.cleanup()

    def test_analyzes_synthesizes_caches_and_approves(self):
        result = asyncio.run(self.workflow.analyze(self.style["style_id"], ["gemini", "pegasus"]))
        self.assertEqual(result["status"], "ready_for_review")
        self.assertEqual(result["style_analysis"]["summary"], "Fast, direct editing")
        self.assertEqual(result["recipe_version"], "1.0.0")
        self.assertEqual(result["recipe_status"], "testing")
        self.assertEqual(len(self.store.style_analyses(self.style["style_id"])), 2)
        self.assertEqual(len(self.store.read_json(self.store.style_dir(self.style["style_id"]) / "remote_assets.json")["assets"]), 2)
        asyncio.run(self.workflow.analyze(self.style["style_id"], ["gemini", "pegasus"]))
        self.assertEqual(self.gemini.calls, 1)
        self.assertEqual(self.pegasus.calls, 1)
        approved = self.workflow.approve(self.style["style_id"])
        self.assertTrue(approved["approval"]["approved"])
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["recipe_status"], "validated")
        self.assertTrue((self.store.style_dir(self.style["style_id"]) / "versions" / "1.0.0.json").exists())
        signal_types = {item["type"] for item in self.store.list_learning_signals(self.style["style_id"])}
        self.assertIn("reference_analysis", signal_types)
        self.assertIn("recipe_version_approved", signal_types)

    def test_identical_reference_reuses_checksum_cache_across_recipes(self):
        asyncio.run(self.workflow.analyze(self.style["style_id"], ["gemini"]))
        shared_reference = self.store.resolve_data_path(self.style["reference_files"][0]["stored_path"])
        second = self.store.create_style(
            "Second recipe", [shared_reference],
            {str(shared_reference): {"duration_seconds": 2}},
        )
        result = asyncio.run(self.workflow.analyze(second["style_id"], ["gemini"]))
        self.assertEqual(self.gemini.calls, 1)
        saved = self.store.style_analyses(result["style_id"])
        self.assertTrue(saved[0]["cache"]["hit"])
        self.assertNotIn("remote_asset", saved[0])

    def test_revises_style_from_feedback_and_preserves_history(self):
        asyncio.run(self.workflow.analyze(self.style["style_id"], ["gemini"]))
        revised = asyncio.run(self.workflow.revise(self.style["style_id"], "Prioritize pacing"))
        self.assertEqual(revised["status"], "ready_for_review")
        self.assertEqual(revised["style_analysis"]["summary"], "Revised: Prioritize pacing")
        self.assertEqual(revised["revision_history"][0]["feedback"], "Prioritize pacing")
        self.assertEqual(revised["recipe_version"], "1.1.0")
        self.assertFalse(revised["approval"]["approved"])
        corrections = [item for item in self.store.list_learning_signals(self.style["style_id"]) if item["type"] == "recipe_correction"]
        self.assertEqual(corrections[0]["instruction"], "Prioritize pacing")

    def test_recipe_repairs_unknown_segment_only_when_timestamps_prove_one_match(self):
        class InventedEvidenceEngine(FakeDecisionEngine):
            async def synthesize_style(self, analyses):
                recipe = await super().synthesize_style(analyses)
                recipe["rules"][0]["evidence"][0]["segment_id"] = "segment-999"
                return recipe

        workflow = StyleWorkflow(self.store, {"gemini": self.gemini}, InventedEvidenceEngine())
        result = asyncio.run(workflow.analyze(self.style["style_id"], ["gemini"]))
        evidence = result["recipe"]["rules"][0]["evidence"][0]
        self.assertEqual(evidence["segment_id"], "segment-001")
        repairs = result["recipe"]["synthesis"]["evidence_repairs"]
        self.assertEqual(repairs[0]["method"], "unique_timestamp_containment")

    def test_recipe_rejects_unknown_segment_when_timestamps_are_ambiguous(self):
        analyzed = analysis("reference-001")
        analyzed["analysis"]["segments"] = [
            {**analyzed["analysis"]["segments"][0], "segment_id": "segment-001", "start_seconds": 0, "end_seconds": 1},
            {**analyzed["analysis"]["segments"][0], "segment_id": "segment-002", "start_seconds": 0, "end_seconds": 1},
        ]
        recipe = {"rules": [{"evidence": [{
            "reference_file_id": "reference-001", "segment_id": "segment-999",
            "start_seconds": 0, "end_seconds": 1,
        }]}]}
        StyleWorkflow._normalize_recipe_evidence(recipe, self.style, [analyzed])
        self.assertEqual(recipe["rules"][0]["evidence"][0]["segment_id"], "segment-999")

    def test_recipe_evidence_boundary_drift_is_clamped_to_real_segment(self):
        recipe = {
            "rules": [{"evidence": [{"reference_file_id": "reference-001", "segment_id": "segment-001", "start_seconds": -2, "end_seconds": 9}]}]
        }
        StyleWorkflow._normalize_recipe_evidence(recipe, self.style, [analysis("reference-001")])
        self.assertEqual(recipe["rules"][0]["evidence"][0]["start_seconds"], 0.0)
        self.assertEqual(recipe["rules"][0]["evidence"][0]["end_seconds"], 1.0)

    def test_rejects_out_of_range_timestamps_and_records_failure(self):
        bad = analysis("reference-001")
        bad["analysis"]["segments"][0]["end_seconds"] = 20

        class BadAnalyzer(FakeAnalyzer):
            async def analyze(self, path, file_id, purpose):
                return bad

        workflow = StyleWorkflow(self.store, {"gemini": BadAnalyzer("gemini")}, FakeDecisionEngine())
        with self.assertRaises(ValueError):
            asyncio.run(workflow.analyze(self.style["style_id"], ["gemini"]))
        saved = self.store.style(self.style["style_id"])
        self.assertEqual(saved["status"], "analysis_failed")
        self.assertIn("outside", saved["last_error"])

    def test_pegasus_schema_removes_constraints_from_number_fields(self):
        schema = PegasusAnalyzer.compatible_schema(VIDEO_ANALYSIS_JSON_SCHEMA)
        segment = schema["properties"]["segments"]["items"]
        self.assertNotIn("minimum", segment["properties"]["start_seconds"])
        self.assertNotIn("maximum", segment["properties"]["confidence"])
        self.assertIn("minimum", VIDEO_ANALYSIS_JSON_SCHEMA["properties"]["segments"]["items"]["properties"]["start_seconds"])

    def test_rejects_invalid_confidence_locally(self):
        bad = analysis("reference-001")
        bad["duration_seconds"] = 2
        bad["analysis"]["segments"][0]["confidence"] = 2
        with self.assertRaises(ValueError):
            StyleWorkflow._validate_analysis(bad)

    def test_remote_asset_is_in_deletion_inventory_when_validation_fails(self):
        invalid = InvalidAnalyzer("gemini")
        workflow = StyleWorkflow(self.store, {"gemini": invalid}, FakeDecisionEngine())
        with self.assertRaises(ValueError):
            asyncio.run(workflow.analyze(self.style["style_id"], ["gemini"]))
        assets = self.store.read_json(self.store.style_dir(self.style["style_id"]) / "remote_assets.json")["assets"]
        self.assertEqual([item["id"] for item in assets], ["gemini-asset"])

    def test_openai_quota_error_is_actionable_but_preserves_details(self):
        error = RuntimeError("429 insufficient_quota: exceeded your current quota")
        fields = failure_fields(error)
        self.assertIn("Add billing or credits", fields["last_error"])
        self.assertIn("insufficient_quota", fields["last_error_details"]["message"])

    def test_provider_api_error_is_user_friendly_and_does_not_store_headers(self):
        fields = failure_fields(ProviderApiError())
        self.assertIn("4-second minimum", fields["last_error"])
        self.assertEqual(fields["last_error_details"]["provider_code"], "video_duration_too_short")
        self.assertEqual(fields["last_error_details"]["trace_id"], "trace-123")
        self.assertNotIn("authorization", str(fields))
        self.assertNotIn("secret", str(fields))


class ProjectAnalysisWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = JsonStore(self.root / "data")
        ref = self.root / "reference.mp4"; ref.write_bytes(b"reference")
        style = self.store.create_style("Style", [ref], {})
        raw_one = self.root / "one.mp4"; raw_one.write_bytes(b"one")
        raw_two = self.root / "two.mp4"; raw_two.write_bytes(b"two")
        self.project = self.store.create_project("Project", style["style_id"], "gemini", "Make it fast", 30, [raw_one, raw_two], {str(raw_one): {"duration_seconds": 2}, str(raw_two): {"duration_seconds": 2}})
        self.analyzer = FakeAnalyzer("gemini")
        self.workflow = ProjectAnalysisWorkflow(self.store, {"gemini": self.analyzer})

    def tearDown(self):
        self.temp.cleanup()

    def test_analyzes_each_file_builds_map_and_reuses_cache(self):
        result = asyncio.run(self.workflow.analyze(self.project["project_id"]))
        self.assertEqual(result["status"], "footage_analyzed")
        self.assertEqual(result["content_map"]["source_file_count"], 2)
        self.assertEqual(result["content_map"]["segment_count"], 2)
        self.assertEqual(len(result["content_map"]["candidates_by_role"]["hook"]), 2)
        self.assertTrue(all(item["analysis_status"] == "complete" for item in result["raw_files"]))
        asyncio.run(self.workflow.analyze(self.project["project_id"]))
        self.assertEqual(self.analyzer.calls, 2)

    def test_skips_clips_below_provider_minimum_without_failing_batch(self):
        analyzer = MinimumDurationAnalyzer("gemini")
        workflow = ProjectAnalysisWorkflow(self.store, {"gemini": analyzer})
        project = self.store.project(self.project["project_id"])
        project["raw_files"][0]["metadata"]["duration_seconds"] = 0.5
        project["raw_files"][1]["metadata"]["duration_seconds"] = 5
        self.store.update_project(project["project_id"], raw_files=project["raw_files"])

        result = asyncio.run(workflow.analyze(project["project_id"]))

        self.assertEqual(result["status"], "footage_analyzed")
        self.assertEqual(result["content_map"]["source_file_count"], 1)
        self.assertEqual(analyzer.calls, 1)
        self.assertEqual(result["raw_files"][0]["analysis_status"], "skipped_too_short")
        self.assertEqual(result["raw_files"][0]["analysis_skip_reason"]["minimum_duration_seconds"], 4.0)
        self.assertEqual(result["raw_files"][1]["analysis_status"], "complete")

    def test_identical_raw_footage_reuses_checksum_cache_across_projects(self):
        first = asyncio.run(self.workflow.analyze(self.project["project_id"]))
        source = self.store.resolve_data_path(first["raw_files"][0]["stored_path"])
        second = self.store.create_project(
            "Second project", first["style_id"], "gemini", "Make it fast", 30,
            [source], {str(source): {"duration_seconds": 2}},
        )
        result = asyncio.run(self.workflow.analyze(second["project_id"]))
        self.assertEqual(self.analyzer.calls, 2)
        saved = self.store.project_analyses(result["project_id"], "gemini")
        self.assertTrue(saved[0]["cache"]["hit"])
        self.assertNotIn("remote_asset", saved[0])

    def test_raw_footage_cache_does_not_cross_device_boundary(self):
        first = self.store.update_project(self.project["project_id"], device_id="device-one")
        first = asyncio.run(self.workflow.analyze(first["project_id"]))
        source = self.store.resolve_data_path(first["raw_files"][0]["stored_path"])
        second = self.store.create_project(
            "Other device", first["style_id"], "gemini", "Make it fast", 30,
            [source], {str(source): {"duration_seconds": 2}}, device_id="device-two",
        )
        result = asyncio.run(self.workflow.analyze(second["project_id"]))
        self.assertEqual(self.analyzer.calls, 3)
        saved = self.store.project_analyses(result["project_id"], "gemini")
        self.assertFalse((saved[0].get("cache") or {}).get("hit", False))

    def test_retries_transient_failure_and_records_attempt_count(self):
        flaky = FlakyAnalyzer("gemini")
        workflow = ProjectAnalysisWorkflow(self.store, {"gemini": flaky}, retry_delays=(0,))
        result = asyncio.run(workflow.analyze(self.project["project_id"]))
        saved = self.store.project_analyses(self.project["project_id"], "gemini")
        self.assertEqual(result["status"], "footage_analyzed")
        self.assertEqual(saved[0]["attempt_count"], 2)
        self.assertEqual(flaky.calls, 3)


if __name__ == "__main__":
    unittest.main()
