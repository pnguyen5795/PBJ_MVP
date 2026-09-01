import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.rendering import FFmpegRenderer, PlanValidationError
from app.decision import OpenAIDecisionEngine
from app.storage import JsonStore
from app.provenance import canonical_sha256, diff_plans, source_time_decisions


def make_plan(project, style_id):
    video = {"source_file_id": "raw-001", "source_start": 0, "source_end": 15, "timeline_start": 0, "timeline_end": 15, "crop_mode": "center_crop", "focal_x": .5, "focal_y": .5, "zoom_start": 1, "zoom_end": 1, "speed": 1, "transition": "cut", "transition_duration": 0, "style_reasons": ["fast opening"]}
    audio = {"source_file_id": "raw-001", "source_start": 0, "source_end": 15, "timeline_start": 0, "timeline_end": 15, "speed": 1, "normalize": True, "noise_reduction": False}
    return {"schema_version": "1.0", "project_id": project["project_id"], "style_id": style_id, "provider": "gemini", "decision_model": "fake", "title": "Rough cut", "creative_summary": "Test", "target_duration_seconds": 15, "video_segments": [video], "audio_segments": [audio], "warnings": [], "selection": {}}


class RenderingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.store = JsonStore(self.root / "data")
        ref = self.root / "ref.mp4"; ref.write_bytes(b"ref")
        self.style = self.store.create_style("Style", [ref], {})
        self.store.update_style(self.style["style_id"], style_analysis={"summary": "style"}, actionable_traits=[], status="approved", approval={"approved": True, "approved_at": "now"})
        raw = self.root / "raw.mp4"; raw.write_bytes(b"raw")
        self.project = self.store.create_project("Project", self.style["style_id"], "gemini", "Edit", 15, [raw], {str(raw): {"duration_seconds": 15}})
        self.project = self.store.update_project(self.project["project_id"], status="footage_analyzed", content_map={"all_segments": [], "candidates_by_role": {}})

    def tearDown(self): self.temp.cleanup()

    def test_plan_validation_rejects_unknown_sources_and_gaps(self):
        renderer = FFmpegRenderer(self.store); plan = make_plan(self.project, self.style["style_id"])
        renderer.validate(self.project, plan)
        plan["video_segments"][0]["source_file_id"] = "raw-999"
        with self.assertRaises(PlanValidationError): renderer.validate(self.project, plan)

    def test_crossfade_plan_validates_and_builds_xfade_filter(self):
        renderer = FFmpegRenderer(self.store); plan = make_plan(self.project, self.style["style_id"])
        first = dict(plan["video_segments"][0], source_end=8, timeline_end=8)
        second = dict(plan["video_segments"][0], source_start=7, source_end=15, timeline_start=7, timeline_end=15, transition="crossfade", transition_duration=1)
        plan["video_segments"] = [first, second]
        renderer.validate(self.project, plan)
        command = renderer.build_command(self.project, plan, self.root / "crossfade.mp4")
        self.assertIn("xfade=transition=fade:duration=1:offset=7", command[command.index("-filter_complex") + 1])

    def test_final_trims_outside_shortlist_are_recorded_as_warnings(self):
        plan = make_plan(self.project, self.style["style_id"])
        candidates = [{"candidate_id": "raw-001:segment-001", "source_file_id": "raw-001", "start_seconds": 0, "end_seconds": 15}]
        record = OpenAIDecisionEngine._validate_selected_ranges(plan, candidates)
        self.assertEqual(record[0]["candidate_id"], "raw-001:segment-001")
        plan["video_segments"][0]["source_start"] = 1
        plan["video_segments"][0]["source_end"] = 16
        record = OpenAIDecisionEngine._validate_selected_ranges(plan, candidates)
        self.assertEqual(record[0]["method"], "openai_trim_outside_shortlist_allowed_with_warning")

    def test_model_source_names_resolve_only_when_project_mapping_is_unique(self):
        plan = make_plan(self.project, self.style["style_id"])
        original_name = self.project["raw_files"][0]["original_name"]
        plan["video_segments"][0]["source_file_id"] = original_name
        plan["audio_segments"][0]["source_file_id"] = "model-invented-name.mov"

        repaired = OpenAIDecisionEngine._repair_source_ids(plan, self.project)

        self.assertEqual(repaired["video_segments"][0]["source_file_id"], "raw-001")
        self.assertEqual(repaired["audio_segments"][0]["source_file_id"], "raw-001")
        self.assertEqual(len(repaired["source_id_repairs"]), 2)

        second = dict(self.project["raw_files"][0], file_id="raw-002")
        ambiguous_project = {**self.project, "raw_files": [self.project["raw_files"][0], second]}
        ambiguous_plan = make_plan(self.project, self.style["style_id"])
        ambiguous_plan["video_segments"][0]["source_file_id"] = "unknown.mov"
        OpenAIDecisionEngine._repair_source_ids(ambiguous_plan, ambiguous_project)
        self.assertEqual(ambiguous_plan["video_segments"][0]["source_file_id"], "unknown.mov")

    def test_empty_selection_uses_only_single_available_analyzer_segment(self):
        selection = {"selected_candidates": [], "warnings": []}
        candidate = {"candidate_id": "raw-001:segment-001"}
        repaired = OpenAIDecisionEngine._ensure_single_available_candidate(
            selection,
            {"all_segments": [candidate]},
        )
        self.assertEqual(
            repaired["selected_candidates"][0]["candidate_id"],
            "raw-001:segment-001",
        )
        untouched = OpenAIDecisionEngine._ensure_single_available_candidate(
            {"selected_candidates": []},
            {"all_segments": [candidate, {"candidate_id": "raw-002:segment-001"}]},
        )
        self.assertEqual(untouched["selected_candidates"], [])

    def test_explicit_named_footage_is_added_and_verified(self):
        candidate = {"candidate_id": "raw-001:segment-ipad", "source_file_id": "raw-001",
                     "start_seconds": 0, "end_seconds": 15, "confidence": .9,
                     "visual_description": "Pilot using an iPad", "transcript": "", "audio_description": "",
                     "subjects": ["pilot"], "actions": ["uses iPad"], "editorial_roles": ["b_roll"]}
        selection = {"story_strategy": "test", "selected_candidates": [], "warnings": []}
        requirements = [{"requirement_id": "include_ipad_clip", "type": "content", "term": "ipad clip",
                         "description": "Include footage showing ipad clip", "required": True}]
        selected = OpenAIDecisionEngine._ensure_required_candidates(selection, {"all_segments": [candidate]}, requirements)
        self.assertEqual(selected["selected_candidates"][0]["candidate_id"], candidate["candidate_id"])
        plan = make_plan(self.project, self.style["style_id"])
        checks = OpenAIDecisionEngine._verify_requirements(plan, [candidate], requirements)
        self.assertEqual(checks[0]["status"], "satisfied")

    def test_plan_diff_and_source_decisions_are_deterministic(self):
        old = make_plan(self.project, self.style["style_id"])
        new = make_plan(self.project, self.style["style_id"])
        new["video_segments"][0]["source_start"] = 1
        new["video_segments"][0]["source_end"] = 16
        new["video_segments"][0]["timeline_end"] = 15
        diff = diff_plans(old, new)
        self.assertEqual(diff["summary"]["modified"], 1)
        self.assertIn("source_range", diff["changes"][0]["attributes"])
        decisions = source_time_decisions(new)
        self.assertEqual(decisions[0]["decision"], "keep")
        self.assertEqual(canonical_sha256(new), diff["plan_hash"])

    def test_structural_qa_distinguishes_required_failures_and_silence_evidence(self):
        renderer = FFmpegRenderer(self.store)
        stderr = "black_start:1 black_end:2 freeze_start:4 freeze_end:9 silence_start:10 silence_end:14"
        with patch("app.rendering.subprocess.run", return_value=SimpleNamespace(returncode=0, stderr=stderr)):
            checks = renderer._structural_checks(self.root / "output.mp4", 15)
        self.assertEqual(checks["black_frames"]["status"], "failed")
        self.assertTrue(checks["black_frames"]["required"])
        self.assertEqual(checks["frozen_video"]["status"], "failed")
        self.assertEqual(checks["long_silence"]["status"], "failed")
        self.assertFalse(checks["long_silence"]["required"])

    def test_structural_qa_fails_closed_when_scan_cannot_run(self):
        renderer = FFmpegRenderer(self.store)
        with patch("app.rendering.subprocess.run", side_effect=OSError("missing")):
            checks = renderer._structural_checks(self.root / "output.mp4", 15)
        self.assertEqual(checks["structural_scan"]["status"], "not_evaluated")
        self.assertTrue(checks["structural_scan"]["required"])

if __name__ == "__main__": unittest.main()
