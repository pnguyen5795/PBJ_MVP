import unittest

from app.provenance import canonical_sha256, diff_plans, source_time_decisions


def make_plan():
    return {
        "schema_version": "1.0", "project_id": "project-test",
        "style_id": "style-test", "provider": "pegasus",
        "decision_model": "fake", "title": "Rough cut",
        "creative_summary": "Test", "target_duration_seconds": 15,
        "video_segments": [{
            "source_file_id": "raw-001", "source_start": 0, "source_end": 15,
            "timeline_start": 0, "timeline_end": 15, "crop_mode": "center_crop",
            "focal_x": .5, "focal_y": .5, "zoom_start": 1, "zoom_end": 1,
            "speed": 1, "transition": "cut", "transition_duration": 0,
            "style_reasons": ["fast opening"],
        }],
        "audio_segments": [{
            "source_file_id": "raw-001", "source_start": 0, "source_end": 15,
            "timeline_start": 0, "timeline_end": 15, "speed": 1,
            "normalize": True, "noise_reduction": False,
        }],
        "warnings": [], "selection": {},
    }


class ProvenanceTests(unittest.TestCase):
    def test_plan_diff_and_source_decisions_are_deterministic(self):
        old = make_plan()
        new = make_plan()
        new["video_segments"][0]["source_start"] = 1
        new["video_segments"][0]["source_end"] = 16
        diff = diff_plans(old, new)
        self.assertEqual(diff["summary"]["modified"], 1)
        self.assertIn("source_range", diff["changes"][0]["attributes"])
        self.assertEqual(source_time_decisions(new)[0]["decision"], "keep")
        self.assertEqual(canonical_sha256(new), diff["plan_hash"])


if __name__ == "__main__":
    unittest.main()
