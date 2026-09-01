from copy import deepcopy
from unittest import TestCase

from app.timeline.contracts import empty_timeline, refresh_hash
from app.timeline.learning import timeline_outcome_metrics


class TimelineLearningMetricTests(TestCase):
    def _timeline(self, clip_id="initial", source_in=0, source_out=5_000_000):
        timeline = empty_timeline("project-20260827-learning", [{
            "asset_id": "raw-001", "kind": "video", "original_name": "source.mov",
            "stored_path": "projects/example/raw/source.mov", "sha256": "a" * 64,
            "duration_us": 10_000_000, "has_audio": False, "analyzed": True,
            "analysis_status": "complete", "permission_scope": "project_private",
        }])
        timeline["tracks"][0]["clips"] = [{
            "clip_id": clip_id, "kind": "video", "asset_id": "raw-001",
            "source_in_us": source_in, "source_out_us": source_out,
            "timeline_start_frame": 0, "duration_frames": round((source_out-source_in)/1_000_000*30),
            "playback_rate": 1.0, "linked_group_id": None,
            "transform": {"mode": "fill", "x": .5, "y": .5, "scale": 1.0},
        }]
        refresh_hash(timeline)
        return timeline

    def test_retention_uses_source_time_not_generated_clip_ids(self):
        initial = self._timeline()
        approved = self._timeline("replacement", 1_000_000, 5_000_000)
        metrics = timeline_outcome_metrics(initial, approved, [], [], 12)
        self.assertEqual(metrics["first_cut_retention"], 0)
        self.assertEqual(metrics["source_time_retention"], .8)
        self.assertTrue(metrics["opening_retained"])

    def test_applied_then_undone_proposal_is_not_counted_as_surviving(self):
        initial = self._timeline(); approved = deepcopy(initial)
        proposal = {"status":"applied", "transaction":{"transaction_id":"tx-undone"}}
        metrics = timeline_outcome_metrics(initial, approved, [], [proposal], 12, active_transaction_ids=[])
        self.assertEqual(metrics["ai_proposal_applied_count"], 1)
        self.assertEqual(metrics["ai_proposal_surviving_count"], 0)
        self.assertEqual(metrics["ai_proposal_reverted_count"], 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
