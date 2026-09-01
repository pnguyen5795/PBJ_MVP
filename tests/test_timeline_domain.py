from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from app.storage import JsonStore
from app.timeline.contracts import asset_from_raw, empty_timeline, refresh_hash, samples_from_frames
from app.timeline.migration import migrate_legacy_project, timeline_from_edit_plan
from app.timeline.preview import preview_state_at_frame
from app.timeline.storage import StaleTimelineError, TimelineStore
from app.timeline.validation import TimelineValidationError, validate_timeline


class TimelineDomainTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.store = JsonStore(Path(self.temp.name))
        self.project_id = "project-20260827-abc123"
        project_dir = self.store.projects_dir / self.project_id
        project_dir.mkdir(parents=True)
        raw = {
            "file_id": "raw-001", "original_name": "one.mov", "stored_path": "projects/%s/raw/one.mov" % self.project_id,
            "sha256": "a" * 64, "analysis_status": "complete",
            "metadata": {"duration_seconds": 30, "has_audio": True, "width": 1080, "height": 1920},
        }
        self.project = {
            "project_id": self.project_id, "style_id": "style-20260827-abc123", "recipe_version": "1.0.0",
            "raw_files": [raw], "runs": [], "status": "footage_analyzed",
        }
        self.store.write_json(project_dir / "manifest.json", self.project)
        self.timeline = empty_timeline(self.project_id, [asset_from_raw(raw)])
        video = next(item for item in self.timeline["tracks"] if item["track_id"] == "video-main")
        video["clips"] = [{
            "clip_id": "clip-1", "kind": "video", "asset_id": "raw-001",
            "source_in_us": 0, "source_out_us": 5_000_000, "timeline_start_frame": 0,
            "duration_frames": 150, "playback_rate": 1.0, "linked_group_id": None,
            "transform": {"mode": "fill", "x": .5, "y": .5, "scale": 1.0},
        }]
        refresh_hash(self.timeline)

    def tearDown(self):
        self.temp.cleanup()

    def test_integer_timing_and_source_bounds_are_enforced(self):
        validate_timeline(self.timeline, for_export=True)
        invalid = deepcopy(self.timeline)
        invalid["tracks"][0]["clips"][0]["source_out_us"] = 40_000_000
        refresh_hash(invalid)
        with self.assertRaises(TimelineValidationError):
            validate_timeline(invalid)

    def test_transactions_are_atomic_persistent_and_reversible(self):
        timelines = TimelineStore(self.store)
        timelines.initialize(self.project_id, self.timeline)
        current = timelines.load(self.project_id)
        transaction = {
            "transaction_id": "tx-1", "base_revision": current["revision"],
            "base_timeline_hash": current["timeline_hash"], "origin": "manual", "reason": "Shorten the opening",
            "operations": [{"operation_id": "op-1", "type": "clip.trim", "payload": {
                "clip_id": "clip-1", "source_out_us": 4_000_000, "duration_frames": 120,
            }}],
        }
        result = timelines.transact(self.project_id, transaction)
        self.assertEqual(result["timeline"]["tracks"][0]["clips"][0]["duration_frames"], 120)
        self.assertEqual(TimelineStore(self.store).load(self.project_id)["revision"], 1)
        undone = timelines.undo(self.project_id)["timeline"]
        self.assertEqual(undone["tracks"][0]["clips"][0]["duration_frames"], 150)
        redone = timelines.redo(self.project_id)["timeline"]
        self.assertEqual(redone["tracks"][0]["clips"][0]["duration_frames"], 120)
        events = timelines.events(self.project_id)
        self.assertEqual(len(events), 4)
        self.assertEqual(events[1]["previous_event_hash"], events[0]["event_hash"])

    def test_linked_trim_ripples_video_and_audio_as_one_atomic_edit(self):
        video = self.timeline["tracks"][0]
        audio = self.timeline["tracks"][2]
        video["clips"][0]["linked_group_id"] = "sync-1"
        audio["clips"] = [{
            "clip_id": "audio-1", "kind": "audio", "asset_id": "raw-001",
            "source_in_us": 0, "source_out_us": 5_000_000, "timeline_start_frame": 0,
            "duration_frames": 150, "timeline_start_sample": 0,
            "duration_samples": samples_from_frames(150), "playback_rate": 1.0,
            "linked_group_id": "sync-1", "volume": 1.0, "muted": False,
            "fades": {"in_frames": 0, "out_frames": 0},
        }]
        second = deepcopy(video["clips"][0]); second.update(
            clip_id="clip-2", source_in_us=5_000_000, source_out_us=10_000_000,
            timeline_start_frame=150, linked_group_id="sync-2",
        )
        second_audio = deepcopy(audio["clips"][0]); second_audio.update(
            clip_id="audio-2", source_in_us=5_000_000, source_out_us=10_000_000,
            timeline_start_frame=150, timeline_start_sample=samples_from_frames(150),
            linked_group_id="sync-2",
        )
        video["clips"].append(second); audio["clips"].append(second_audio)
        refresh_hash(self.timeline)
        timelines = TimelineStore(self.store); timelines.initialize(self.project_id, self.timeline)
        current = timelines.load(self.project_id)
        result = timelines.transact(self.project_id, {
            "transaction_id": "tx-linked-trim", "base_revision": current["revision"],
            "base_timeline_hash": current["timeline_hash"], "origin": "manual",
            "operations": [{"operation_id": "op-linked-trim", "type": "clip.trim", "payload": {
                "clip_id": "clip-1", "source_out_us": 4_000_000,
                "duration_frames": 120, "ripple": True,
            }}],
        })["timeline"]
        by_id = {clip["clip_id"]: clip for track in result["tracks"] for clip in track["clips"]}
        self.assertEqual(by_id["audio-1"]["duration_frames"], 120)
        self.assertEqual(by_id["clip-2"]["timeline_start_frame"], 120)
        self.assertEqual(by_id["audio-2"]["timeline_start_frame"], 120)
        validate_timeline(result, for_export=True)
        restored = timelines.undo(self.project_id)["timeline"]
        restored_by_id = {clip["clip_id"]: clip for track in restored["tracks"] for clip in track["clips"]}
        self.assertEqual(restored_by_id["clip-2"]["timeline_start_frame"], 150)
        self.assertEqual(restored_by_id["audio-1"]["duration_frames"], 150)

    def test_split_creates_independent_linked_video_audio_pairs(self):
        video = self.timeline["tracks"][0]
        audio = self.timeline["tracks"][2]
        video["clips"][0]["linked_group_id"] = "sync-1"
        audio["clips"] = [{
            "clip_id": "audio-1", "kind": "audio", "asset_id": "raw-001",
            "source_in_us": 0, "source_out_us": 5_000_000, "timeline_start_frame": 0,
            "duration_frames": 150, "timeline_start_sample": 0,
            "duration_samples": samples_from_frames(150), "playback_rate": 1.0,
            "linked_group_id": "sync-1", "volume": 1.0, "muted": False,
            "fades": {"in_frames": 0, "out_frames": 0},
        }]
        refresh_hash(self.timeline)
        timelines = TimelineStore(self.store); timelines.initialize(self.project_id, self.timeline)
        current = timelines.load(self.project_id)
        split = timelines.transact(self.project_id, {
            "transaction_id": "tx-linked-split", "base_revision": current["revision"],
            "base_timeline_hash": current["timeline_hash"], "origin": "manual",
            "operations": [{"operation_id": "op-linked-split", "type": "clip.split", "payload": {
                "clip_id": "clip-1", "at_frame": 60, "new_clip_id": "clip-2",
            }}],
        })["timeline"]
        by_id = {clip["clip_id"]: clip for track in split["tracks"] for clip in track["clips"]}
        right_audio = by_id["clip-2-linked-audio-1"]
        self.assertEqual(by_id["clip-1"]["linked_group_id"], "sync-1")
        self.assertEqual(by_id["audio-1"]["linked_group_id"], "sync-1")
        self.assertEqual(by_id["clip-2"]["linked_group_id"], "clip-2-sync")
        self.assertEqual(right_audio["linked_group_id"], "clip-2-sync")

        sped = timelines.transact(self.project_id, {
            "transaction_id": "tx-speed-right", "base_revision": split["revision"],
            "base_timeline_hash": split["timeline_hash"], "origin": "manual",
            "operations": [{"operation_id": "op-speed-right", "type": "clip.speed.set", "payload": {
                "clip_id": "clip-2", "playback_rate": 2.0,
                "duration_frames": 45, "ripple": True,
            }}],
        })["timeline"]
        sped_by_id = {clip["clip_id"]: clip for track in sped["tracks"] for clip in track["clips"]}
        self.assertEqual(sped_by_id["clip-2"]["playback_rate"], 2.0)
        self.assertEqual(sped_by_id["clip-2"]["duration_frames"], 45)
        self.assertEqual(sped_by_id["clip-2-linked-audio-1"]["playback_rate"], 2.0)
        self.assertEqual(sped_by_id["clip-2-linked-audio-1"]["duration_frames"], 45)
        validate_timeline(sped, for_export=True)

        after_delete = timelines.transact(self.project_id, {
            "transaction_id": "tx-delete-right", "base_revision": sped["revision"],
            "base_timeline_hash": sped["timeline_hash"], "origin": "manual",
            "operations": [{"operation_id": "op-delete-right", "type": "clip.delete", "payload": {
                "clip_id": "clip-2", "ripple": True,
            }}],
        })["timeline"]
        remaining = {clip["clip_id"] for track in after_delete["tracks"] for clip in track["clips"]}
        self.assertIn("clip-1", remaining)
        self.assertIn("audio-1", remaining)
        self.assertNotIn("clip-2", remaining)
        self.assertNotIn("clip-2-linked-audio-1", remaining)
        validate_timeline(after_delete, for_export=True)

    def test_crossfade_creates_real_overlap_and_undo_restores_positions(self):
        video = self.timeline["tracks"][0]
        second = deepcopy(video["clips"][0]); second.update(
            clip_id="clip-2", source_in_us=5_000_000, source_out_us=10_000_000,
            timeline_start_frame=150,
        )
        video["clips"].append(second); refresh_hash(self.timeline)
        timelines = TimelineStore(self.store); timelines.initialize(self.project_id, self.timeline)
        current = timelines.load(self.project_id)
        updated = timelines.transact(self.project_id, {
            "transaction_id": "tx-transition", "base_revision": current["revision"],
            "base_timeline_hash": current["timeline_hash"], "origin": "manual",
            "operations": [{"operation_id": "op-transition", "type": "transition.set", "payload": {
                "transition": {"transition_id": "transition-1", "type": "crossfade",
                               "from_clip_id": "clip-1", "to_clip_id": "clip-2", "duration_frames": 15},
            }}],
        })["timeline"]
        self.assertEqual(updated["tracks"][0]["clips"][1]["timeline_start_frame"], 135)
        validate_timeline(updated, for_export=True)
        restored = timelines.undo(self.project_id)["timeline"]
        self.assertEqual(restored["tracks"][0]["clips"][1]["timeline_start_frame"], 150)

    def test_main_reorder_is_magnetic_and_reversible(self):
        video = self.timeline["tracks"][0]
        for index in (2, 3):
            clip = deepcopy(video["clips"][0]); clip.update(
                clip_id="clip-%d" % index, source_in_us=(index - 1) * 5_000_000,
                source_out_us=index * 5_000_000, timeline_start_frame=(index - 1) * 150,
            )
            video["clips"].append(clip)
        refresh_hash(self.timeline)
        timelines = TimelineStore(self.store); timelines.initialize(self.project_id, self.timeline)
        current = timelines.load(self.project_id)
        reordered = timelines.transact(self.project_id, {
            "transaction_id":"tx-reorder", "base_revision":current["revision"],
            "base_timeline_hash":current["timeline_hash"], "origin":"manual",
            "operations":[{"operation_id":"op-reorder","type":"clip.reorder",
                           "payload":{"clip_id":"clip-3","target_index":0}}],
        })["timeline"]
        self.assertEqual([clip["clip_id"] for clip in reordered["tracks"][0]["clips"]], ["clip-3", "clip-1", "clip-2"])
        self.assertEqual([clip["timeline_start_frame"] for clip in reordered["tracks"][0]["clips"]], [0, 150, 300])
        validate_timeline(reordered, for_export=True)
        restored = timelines.undo(self.project_id)["timeline"]
        self.assertEqual([clip["clip_id"] for clip in restored["tracks"][0]["clips"]], ["clip-1", "clip-2", "clip-3"])

    def test_invalid_transform_is_rejected_at_the_command_boundary(self):
        timelines = TimelineStore(self.store); timelines.initialize(self.project_id, self.timeline)
        current = timelines.load(self.project_id)
        with self.assertRaises(ValueError):
            timelines.transact(self.project_id, {
                "transaction_id": "tx-invalid-transform", "base_revision": current["revision"],
                "base_timeline_hash": current["timeline_hash"], "origin": "manual",
                "operations": [{"operation_id": "op-invalid-transform", "type": "video.transform.set",
                                "payload": {"clip_id": "clip-1", "transform": {"mode": "warp", "x": 8, "y": -1, "scale": -2}}}],
            })

    def test_selected_clip_crop_is_validated_persisted_and_reversible(self):
        timelines = TimelineStore(self.store); timelines.initialize(self.project_id, self.timeline)
        current = timelines.load(self.project_id)
        transform = {
            "mode": "fit", "x": .5, "y": .5, "scale": 1.0,
            "crop": {"preset": "1:1", "x": .21875, "y": 0, "width": .5625, "height": 1},
        }
        cropped = timelines.transact(self.project_id, {
            "transaction_id": "tx-crop", "base_revision": current["revision"],
            "base_timeline_hash": current["timeline_hash"], "origin": "manual",
            "operations": [{"operation_id": "op-crop", "type": "video.transform.set",
                            "payload": {"clip_id": "clip-1", "transform": transform}}],
        })["timeline"]
        self.assertEqual(cropped["tracks"][0]["clips"][0]["transform"]["crop"]["preset"], "1:1")
        validate_timeline(cropped, for_export=True)
        restored = timelines.undo(self.project_id)["timeline"]
        self.assertNotIn("crop", restored["tracks"][0]["clips"][0]["transform"])

        invalid = deepcopy(transform)
        invalid["crop"] = {"preset": "freeform", "x": .8, "y": 0, "width": .5, "height": 1}
        with self.assertRaises(ValueError):
            timelines.transact(self.project_id, {
                "transaction_id": "tx-invalid-crop", "base_revision": restored["revision"],
                "base_timeline_hash": restored["timeline_hash"], "origin": "manual",
                "operations": [{"operation_id": "op-invalid-crop", "type": "video.transform.set",
                                "payload": {"clip_id": "clip-1", "transform": invalid}}],
            })

    def test_transaction_id_remains_idempotent_after_undo(self):
        timelines = TimelineStore(self.store); timelines.initialize(self.project_id, self.timeline)
        current = timelines.load(self.project_id)
        transaction = {
            "transaction_id": "tx-once", "base_revision": current["revision"],
            "base_timeline_hash": current["timeline_hash"], "origin": "manual",
            "operations": [{"operation_id": "op-once", "type": "clip.trim",
                            "payload": {"clip_id": "clip-1", "source_out_us": 4_000_000, "duration_frames": 120}}],
        }
        timelines.transact(self.project_id, transaction)
        undone = timelines.undo(self.project_id)["timeline"]
        replay = deepcopy(transaction); replay.update(base_revision=undone["revision"], base_timeline_hash=undone["timeline_hash"])
        result = timelines.transact(self.project_id, replay)
        self.assertTrue(result["diff"]["idempotent"])
        self.assertEqual(result["timeline"]["tracks"][0]["clips"][0]["duration_frames"], 150)

    def test_stale_transaction_returns_current_timeline(self):
        timelines = TimelineStore(self.store)
        timelines.initialize(self.project_id, self.timeline)
        with self.assertRaises(StaleTimelineError) as raised:
            timelines.transact(self.project_id, {
                "transaction_id": "tx-stale", "base_revision": 99, "base_timeline_hash": "bad",
                "origin": "manual", "operations": [],
            })
        self.assertEqual(raised.exception.current["revision"], 0)

    def test_failed_optional_analysis_keeps_asset_available_for_manual_editing(self):
        timelines = TimelineStore(self.store)
        timelines.initialize(self.project_id, self.timeline)
        imported = asset_from_raw({
            "file_id": "raw-002",
            "original_name": "manual-only.mov",
            "stored_path": "projects/%s/raw/manual-only.mov" % self.project_id,
            "sha256": "b" * 64,
            "analysis_status": "pending",
            "metadata": {"duration_seconds": 12, "has_audio": True, "width": 1080, "height": 1920},
        })
        timelines.register_asset(self.project_id, imported)

        failed = timelines.mark_asset_analysis_failed(self.project_id, "raw-002", "provider unavailable")

        asset = next(item for item in failed["assets"] if item["asset_id"] == "raw-002")
        self.assertFalse(asset["analyzed"])
        self.assertEqual(asset["analysis_status"], "failed")
        self.assertEqual(asset["analysis_error"], "provider unavailable")
        self.assertEqual(timelines.events(self.project_id)[-1]["type"], "timeline.asset_analysis_failed")

    def test_legacy_plan_migrates_without_analysis_or_render(self):
        plan = {
            "target": {"width": 1080, "height": 1920}, "decision_model": "test",
            "video_segments": [{
                "source_file_id": "raw-001", "source_start": 1, "source_end": 6,
                "timeline_start": 0, "timeline_end": 5, "speed": 1,
                "crop_mode": "center_crop", "focal_x": .5, "focal_y": .5,
                "zoom_start": 1, "zoom_end": 1, "transition": "cut", "transition_duration": 0,
                "style_reasons": [],
            }],
            "audio_segments": [{
                "source_file_id": "raw-001", "source_start": 1, "source_end": 6,
                "timeline_start": 0, "timeline_end": 5, "speed": 1,
            }],
        }
        run_dir = self.store.project_dir(self.project_id) / "runs" / "run-20260827-aaa111"
        plan_path = run_dir / "edit_plan.json"
        self.store.write_json(plan_path, plan)
        run = {"run_id": "run-20260827-aaa111", "plan_path": str(plan_path.relative_to(self.store.data_dir))}
        self.store.update_project(self.project_id, runs=[run], latest_run=run)
        timeline = migrate_legacy_project(self.store, self.project_id)
        self.assertEqual(timeline["tracks"][0]["clips"][0]["source_in_us"], 1_000_000)
        self.assertEqual(timeline["tracks"][2]["clips"][0]["duration_samples"], samples_from_frames(150))
        self.assertEqual(migrate_legacy_project(self.store, self.project_id)["timeline_hash"], timeline["timeline_hash"])

    def test_preview_state_uses_the_same_source_mapping_as_export(self):
        clip = self.timeline["tracks"][0]["clips"][0]
        clip.update(source_in_us=1_000_000, source_out_us=5_000_000, duration_frames=120, playback_rate=1.0)
        audio = self.timeline["tracks"][2]
        audio["clips"] = [{
            "clip_id": "audio-1", "kind": "audio", "asset_id": "raw-001",
            "source_in_us": 1_000_000, "source_out_us": 5_000_000,
            "timeline_start_frame": 0, "duration_frames": 120,
            "timeline_start_sample": 0, "duration_samples": samples_from_frames(120),
            "playback_rate": 1.0, "linked_group_id": "sync-1", "volume": .8,
            "muted": False, "fades": {"in_frames": 30, "out_frames": 30},
        }]
        clip["linked_group_id"] = "sync-1"
        refresh_hash(self.timeline); validate_timeline(self.timeline)
        state = preview_state_at_frame(self.timeline, 15)
        self.assertEqual(state["video"][0]["source_us"], 1_500_000)
        self.assertEqual(state["audio"][0]["source_us"], 1_500_000)
        self.assertAlmostEqual(state["audio"][0]["gain"], .4)


if __name__ == "__main__":
    import unittest
    unittest.main()
