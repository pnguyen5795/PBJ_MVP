import tempfile
import unittest
from pathlib import Path

from app.decision import OpenAIDecisionEngine
from app.storage import JsonStore


def make_plan(project, style_id):
    video = {
        "source_file_id": "raw-001", "source_start": 0, "source_end": 15,
        "timeline_start": 0, "timeline_end": 15, "crop_mode": "center_crop",
        "focal_x": .5, "focal_y": .5, "zoom_start": 1, "zoom_end": 1,
        "speed": 1, "transition": "cut", "transition_duration": 0,
        "style_reasons": ["fast opening"],
    }
    audio = {
        "source_file_id": "raw-001", "source_start": 0, "source_end": 15,
        "timeline_start": 0, "timeline_end": 15, "speed": 1,
        "normalize": True, "noise_reduction": False,
    }
    return {
        "schema_version": "1.0", "project_id": project["project_id"],
        "style_id": style_id, "provider": "pegasus", "decision_model": "fake",
        "title": "Rough cut", "creative_summary": "Test",
        "target_duration_seconds": 15, "video_segments": [video],
        "audio_segments": [audio], "warnings": [], "selection": {},
    }


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        store = JsonStore(root / "data")
        reference = root / "ref.mp4"
        reference.write_bytes(b"ref")
        style = store.create_style("Style", [reference], {})
        raw = root / "raw.mp4"
        raw.write_bytes(b"raw")
        self.project = store.create_project(
            "Project", style["style_id"], "pegasus", "Edit", 15, [raw],
            {str(raw): {"duration_seconds": 15}},
        )
        self.style_id = style["style_id"]

    def tearDown(self):
        self.temp.cleanup()

    def test_final_trims_outside_shortlist_are_recorded_as_warnings(self):
        plan = make_plan(self.project, self.style_id)
        candidates = [{
            "candidate_id": "raw-001:segment-001", "source_file_id": "raw-001",
            "start_seconds": 0, "end_seconds": 15,
        }]
        record = OpenAIDecisionEngine._validate_selected_ranges(plan, candidates)
        self.assertEqual(record[0]["candidate_id"], "raw-001:segment-001")
        plan["video_segments"][0]["source_start"] = 1
        plan["video_segments"][0]["source_end"] = 16
        record = OpenAIDecisionEngine._validate_selected_ranges(plan, candidates)
        self.assertEqual(
            record[0]["method"],
            "openai_trim_outside_shortlist_allowed_with_warning",
        )

    def test_model_source_names_resolve_only_when_project_mapping_is_unique(self):
        plan = make_plan(self.project, self.style_id)
        original_name = self.project["raw_files"][0]["original_name"]
        plan["video_segments"][0]["source_file_id"] = original_name
        plan["audio_segments"][0]["source_file_id"] = "model-invented-name.mov"

        repaired = OpenAIDecisionEngine._repair_source_ids(plan, self.project)

        self.assertEqual(repaired["video_segments"][0]["source_file_id"], "raw-001")
        self.assertEqual(repaired["audio_segments"][0]["source_file_id"], "raw-001")
        self.assertEqual(len(repaired["source_id_repairs"]), 2)

        second = dict(self.project["raw_files"][0], file_id="raw-002")
        ambiguous_project = {
            **self.project,
            "raw_files": [self.project["raw_files"][0], second],
        }
        ambiguous_plan = make_plan(self.project, self.style_id)
        ambiguous_plan["video_segments"][0]["source_file_id"] = "unknown.mov"
        OpenAIDecisionEngine._repair_source_ids(ambiguous_plan, ambiguous_project)
        self.assertEqual(
            ambiguous_plan["video_segments"][0]["source_file_id"], "unknown.mov",
        )

    def test_empty_selection_uses_only_single_available_analyzer_segment(self):
        candidate = {"candidate_id": "raw-001:segment-001"}
        repaired = OpenAIDecisionEngine._ensure_single_available_candidate(
            {"selected_candidates": [], "warnings": []},
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
        candidate = {
            "candidate_id": "raw-001:segment-ipad", "source_file_id": "raw-001",
            "start_seconds": 0, "end_seconds": 15, "confidence": .9,
            "visual_description": "Pilot using an iPad", "transcript": "",
            "audio_description": "", "subjects": ["pilot"],
            "actions": ["uses iPad"], "editorial_roles": ["b_roll"],
        }
        requirements = [{
            "requirement_id": "include_ipad_clip", "type": "content",
            "term": "ipad clip", "description": "Include footage showing ipad clip",
            "required": True,
        }]
        selected = OpenAIDecisionEngine._ensure_required_candidates(
            {"story_strategy": "test", "selected_candidates": [], "warnings": []},
            {"all_segments": [candidate]}, requirements,
        )
        self.assertEqual(
            selected["selected_candidates"][0]["candidate_id"],
            candidate["candidate_id"],
        )
        checks = OpenAIDecisionEngine._verify_requirements(
            make_plan(self.project, self.style_id), [candidate], requirements,
        )
        self.assertEqual(checks[0]["status"], "satisfied")


if __name__ == "__main__":
    unittest.main()
