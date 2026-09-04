from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from app.storage import JsonStore
from app.timeline.contracts import (
    asset_from_raw, empty_timeline, refresh_hash, samples_from_frames,
)
from app.timeline.migration import migrate_legacy_project, timeline_from_edit_plan
from app.timeline.preview import preview_state_at_frame
from app.timeline.storage import TimelineStore
from app.timeline.validation import TimelineValidationError, validate_timeline


class TimelineDomainTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = JsonStore(Path(self.temp.name))
        self.project_id = "project-20260827-abc123"
        project_dir = self.store.projects_dir / self.project_id
        project_dir.mkdir(parents=True)
        raw = {
            "file_id": "raw-001", "original_name": "one.mov",
            "stored_path": "projects/%s/raw/one.mov" % self.project_id,
            "sha256": "a" * 64, "analysis_status": "complete",
            "metadata": {
                "duration_seconds": 30, "has_audio": True,
                "width": 1080, "height": 1920,
            },
        }
        self.project = {
            "project_id": self.project_id,
            "style_id": "style-20260827-abc123",
            "recipe_version": "1.0.0", "raw_files": [raw], "runs": [],
            "status": "footage_analyzed",
        }
        self.store.write_json(project_dir / "manifest.json", self.project)
        self.timeline = empty_timeline(self.project_id, [asset_from_raw(raw)])
        self.timeline["tracks"][0]["clips"] = [{
            "clip_id": "clip-1", "kind": "video", "asset_id": "raw-001",
            "source_in_us": 0, "source_out_us": 5_000_000,
            "timeline_start_frame": 0, "duration_frames": 150,
            "playback_rate": 1.0, "linked_group_id": None,
            "transform": {"mode": "fill", "x": .5, "y": .5, "scale": 1.0},
        }]
        refresh_hash(self.timeline)

    def tearDown(self):
        self.temp.cleanup()

    def test_plan_frame_boundaries_do_not_create_rounding_gaps(self):
        plan = {
            "target": {"width": 1080, "height": 1920},
            "video_segments": [
                {
                    "source_file_id": "raw-001", "source_start": 0,
                    "source_end": 7.6, "timeline_start": 0,
                    "timeline_end": 7.6, "speed": 1,
                },
                {
                    "source_file_id": "raw-001", "source_start": 0,
                    "source_end": 17.5, "timeline_start": 7.6,
                    "timeline_end": 25.1, "speed": 1,
                },
                {
                    "source_file_id": "raw-001", "source_start": 0,
                    "source_end": 6.1666667, "timeline_start": 25.1,
                    "timeline_end": 31.2666667, "speed": 1,
                },
            ],
            "audio_segments": [],
        }
        timeline = timeline_from_edit_plan(self.project, plan)
        clips = timeline["tracks"][0]["clips"]
        self.assertEqual(
            clips[0]["timeline_start_frame"] + clips[0]["duration_frames"],
            clips[1]["timeline_start_frame"],
        )
        self.assertEqual(
            clips[1]["timeline_start_frame"] + clips[1]["duration_frames"],
            clips[2]["timeline_start_frame"],
        )
        validate_timeline(timeline, for_export=True)

    def test_integer_timing_and_source_bounds_are_enforced(self):
        validate_timeline(self.timeline, for_export=True)
        invalid = deepcopy(self.timeline)
        invalid["tracks"][0]["clips"][0]["source_out_us"] = 40_000_000
        refresh_hash(invalid)
        with self.assertRaises(TimelineValidationError):
            validate_timeline(invalid)

    def test_ai_revision_preserves_initial_snapshot_and_hash_chained_events(self):
        timelines = TimelineStore(self.store)
        initial = timelines.initialize(self.project_id, self.timeline)
        revised = deepcopy(initial)
        revised["tracks"][0]["clips"][0].update(
            source_out_us=4_000_000, duration_frames=120,
        )
        refresh_hash(revised)

        saved = timelines.replace_with_ai_revision(
            self.project_id, revised, "Shorten the opening",
        )

        self.assertEqual(saved["revision"], 1)
        self.assertEqual(
            timelines.load(self.project_id)["timeline_hash"], saved["timeline_hash"],
        )
        snapshot = self.store.read_json(
            timelines.root(self.project_id) / "snapshots" / "initial-ai.json",
        )
        self.assertEqual(snapshot["timeline_hash"], initial["timeline_hash"])
        events = timelines.events(self.project_id)
        self.assertEqual([item["type"] for item in events], [
            "timeline.initialized", "timeline.ai_revision",
        ])
        self.assertEqual(events[1]["previous_event_hash"], events[0]["event_hash"])

    def test_legacy_plan_migrates_without_analysis_or_render(self):
        plan = {
            "target": {"width": 1080, "height": 1920},
            "decision_model": "test",
            "video_segments": [{
                "source_file_id": "raw-001", "source_start": 1, "source_end": 6,
                "timeline_start": 0, "timeline_end": 5, "speed": 1,
                "crop_mode": "center_crop", "focal_x": .5, "focal_y": .5,
                "zoom_start": 1, "zoom_end": 1, "transition": "cut",
                "transition_duration": 0, "style_reasons": [],
            }],
            "audio_segments": [{
                "source_file_id": "raw-001", "source_start": 1, "source_end": 6,
                "timeline_start": 0, "timeline_end": 5, "speed": 1,
            }],
        }
        run_dir = (
            self.store.project_dir(self.project_id) / "runs" /
            "run-20260827-aaa111"
        )
        plan_path = run_dir / "edit_plan.json"
        self.store.write_json(plan_path, plan)
        run = {
            "run_id": "run-20260827-aaa111",
            "plan_path": str(plan_path.relative_to(self.store.data_dir)),
        }
        self.store.update_project(self.project_id, runs=[run], latest_run=run)
        timeline = migrate_legacy_project(self.store, self.project_id)
        self.assertEqual(
            timeline["tracks"][0]["clips"][0]["source_in_us"], 1_000_000,
        )
        self.assertEqual(
            timeline["tracks"][2]["clips"][0]["duration_samples"],
            samples_from_frames(150),
        )
        self.assertEqual(
            migrate_legacy_project(self.store, self.project_id)["timeline_hash"],
            timeline["timeline_hash"],
        )

    def test_preview_state_uses_the_same_source_mapping_as_export(self):
        clip = self.timeline["tracks"][0]["clips"][0]
        clip.update(
            source_in_us=1_000_000, source_out_us=5_000_000,
            duration_frames=120, playback_rate=1.0, linked_group_id="sync-1",
        )
        self.timeline["tracks"][2]["clips"] = [{
            "clip_id": "audio-1", "kind": "audio", "asset_id": "raw-001",
            "source_in_us": 1_000_000, "source_out_us": 5_000_000,
            "timeline_start_frame": 0, "duration_frames": 120,
            "timeline_start_sample": 0,
            "duration_samples": samples_from_frames(120),
            "playback_rate": 1.0, "linked_group_id": "sync-1",
            "volume": .8, "muted": False,
            "fades": {"in_frames": 30, "out_frames": 30},
        }]
        refresh_hash(self.timeline)
        validate_timeline(self.timeline)
        state = preview_state_at_frame(self.timeline, 15)
        self.assertEqual(state["video"][0]["source_us"], 1_500_000)
        self.assertEqual(state["audio"][0]["source_us"], 1_500_000)
        self.assertAlmostEqual(state["audio"][0]["gain"], .4)


if __name__ == "__main__":
    import unittest

    unittest.main()
