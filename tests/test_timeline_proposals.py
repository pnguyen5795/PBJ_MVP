from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase

from app.storage import JsonStore
from app.timeline.contracts import asset_from_raw, empty_timeline, refresh_hash
from app.timeline.proposals import TimelineProposalService
from app.timeline.storage import TimelineStore


class FakeProposalEngine:
    def __init__(self):
        self.contexts = []

    async def propose(self, context):
        self.contexts.append(context)
        clip = context["current_timeline"]["tracks"][0]["clips"][0]
        return {
            "summary": "Tighten the opening",
            "operations": [{
                "type": "clip.trim", "reason": "Remove one second",
                "payload_json": '{"clip_id":"%s","source_out_us":4000000,"duration_frames":120}' % clip["clip_id"],
            }],
            "model": "fixture", "response_id": "response-fixture", "usage": {},
        }


class FakeRepairProposalEngine(FakeProposalEngine):
    def __init__(self):
        super().__init__(); self.repairs = []

    async def propose(self, context):
        result = await super().propose(context)
        result["operations"][0]["payload_json"] = result["operations"][0]["payload_json"].replace("4000000", "12000000")
        return result

    async def repair(self, context, failed_result, validation_error):
        self.repairs.append(validation_error)
        result = await FakeProposalEngine().propose(context)
        result.update({
            "agent_key": "repair", "agent_name": "PB&J Timeline Repair Agent",
            "agent_role_version": "timeline-repair-agent-v1", "model": "gpt-5.6-luna",
            "reasoning_effort": "medium", "response_id": "repair-response",
            "repair_prompt_version": "timeline-proposal-repair-v1",
        })
        return result


class TimelineProposalTests(IsolatedAsyncioTestCase):
    async def test_proposal_is_previewed_then_applied_without_render_or_analysis(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data")
            style_id = "style-20260827-aa11bb"; style_root = store.styles_dir / style_id; style_root.mkdir(parents=True)
            store.write_json(style_root / "profile.json", {"style_id": style_id, "recipe": {"rules": []}, "recipe_version": "1.0.0"})
            project_id = "project-20260827-cc22dd"; project_root = store.projects_dir / project_id; project_root.mkdir(parents=True)
            raw = {"file_id": "raw-001", "original_name": "one.mov", "stored_path": "projects/%s/raw/one.mov" % project_id, "sha256": "a" * 64, "analysis_status": "complete", "metadata": {"duration_seconds": 10, "has_audio": True}}
            store.write_json(project_root / "manifest.json", {"project_id": project_id, "style_id": style_id, "recipe_version": "1.0.0", "raw_files": [raw], "provider": "pegasus", "prompt": "Fast opening", "target_duration_seconds": 5, "content_map": {}, "timeline_revision_prompts": []})
            timeline = empty_timeline(project_id, [asset_from_raw(raw)])
            timeline["tracks"][0]["clips"] = [{"clip_id": "video-1", "kind": "video", "asset_id": "raw-001", "source_in_us": 0, "source_out_us": 5_000_000, "timeline_start_frame": 0, "duration_frames": 150, "playback_rate": 1.0, "linked_group_id": None, "transform": {"mode": "fill", "x": .5, "y": .5, "scale": 1}}]
            refresh_hash(timeline); TimelineStore(store).initialize(project_id, timeline)
            engine = FakeProposalEngine(); service = TimelineProposalService(store, engine=engine)
            proposal = await service.create(project_id, "Make the opening faster")
            self.assertIn("diff", proposal)
            self.assertEqual(store.project(project_id).get("timeline_revision_prompts", []), [])
            self.assertEqual(TimelineStore(store).load(project_id)["timeline_hash"], timeline["timeline_hash"])
            result = service.apply(project_id, proposal["proposal_id"])
            self.assertEqual(result["timeline"]["tracks"][0]["clips"][0]["duration_frames"], 120)
            self.assertFalse((project_root / "exports").exists())
            self.assertEqual(store.project(project_id).get("runs", []), [])
            self.assertEqual(store.project(project_id)["timeline_revision_prompts"], ["Make the opening faster"])

    async def test_rejected_prompt_is_evidence_but_not_positive_context(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data")
            style_id = "style-20260827-ab12cd"; root = store.styles_dir / style_id; root.mkdir(parents=True)
            store.write_json(root / "profile.json", {"style_id": style_id, "recipe": {"rules": []}})
            project_id = "project-20260827-ab12cd"; project_root = store.projects_dir / project_id; project_root.mkdir(parents=True)
            raw = {"file_id": "raw-001", "stored_path": "projects/%s/raw/one.mov" % project_id,
                   "analysis_status": "complete", "metadata": {"duration_seconds": 10}}
            store.write_json(project_root / "manifest.json", {"project_id": project_id, "style_id": style_id,
                             "raw_files": [raw], "provider": "pegasus", "prompt": "Edit", "target_duration_seconds": 5})
            timeline = empty_timeline(project_id, [asset_from_raw(raw)])
            timeline["tracks"][0]["clips"] = [{"clip_id":"video-1","kind":"video","asset_id":"raw-001",
                "source_in_us":0,"source_out_us":5_000_000,"timeline_start_frame":0,"duration_frames":150,
                "playback_rate":1.0,"linked_group_id":None,"transform":{"mode":"fill","x":.5,"y":.5,"scale":1}}]
            refresh_hash(timeline); TimelineStore(store).initialize(project_id, timeline)
            engine = FakeProposalEngine(); service = TimelineProposalService(store, engine=engine)
            first = await service.create(project_id, "Bad direction"); service.reject(project_id, first["proposal_id"])
            await service.create(project_id, "Try another direction")
            self.assertEqual(engine.contexts[-1]["previous_applied_revision_prompts"], [])
            self.assertEqual(store.project(project_id)["timeline_revision_history"][0]["status"], "rejected")

    async def test_invalid_revision_transaction_is_repaired_before_preview(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data")
            style_id = "style-20260827-aa11cc"; (store.styles_dir / style_id).mkdir(parents=True)
            store.write_json(store.styles_dir / style_id / "profile.json", {"style_id": style_id, "recipe": {"rules": []}})
            project_id = "project-20260827-dd22bb"; root = store.projects_dir / project_id; root.mkdir(parents=True)
            raw = {"file_id": "raw-001", "stored_path": "projects/%s/raw/one.mov" % project_id,
                   "analysis_status": "complete", "metadata": {"duration_seconds": 10}}
            store.write_json(root / "manifest.json", {"project_id": project_id, "style_id": style_id,
                             "raw_files": [raw], "provider": "pegasus", "prompt": "Edit", "target_duration_seconds": 5})
            timeline = empty_timeline(project_id, [asset_from_raw(raw)])
            timeline["tracks"][0]["clips"] = [{"clip_id": "video-1", "kind": "video", "asset_id": "raw-001",
                "source_in_us": 0, "source_out_us": 5_000_000, "timeline_start_frame": 0, "duration_frames": 150,
                "playback_rate": 1.0, "linked_group_id": None, "transform": {"mode": "fill", "x": .5, "y": .5, "scale": 1}}]
            refresh_hash(timeline); TimelineStore(store).initialize(project_id, timeline)
            engine = FakeRepairProposalEngine()
            proposal = await TimelineProposalService(store, engine=engine).create(project_id, "Shorten it")
            self.assertEqual(len(engine.repairs), 1)
            self.assertEqual(proposal["repair_attempts"][0]["agent_role_version"], "timeline-repair-agent-v1")

    async def test_ai_cannot_change_unanalyzed_media(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data")
            style_id = "style-20260827-ee33ff"; (store.styles_dir / style_id).mkdir(parents=True)
            store.write_json(store.styles_dir / style_id / "profile.json", {"style_id": style_id, "recipe": {"rules": []}})
            project_id = "project-20260827-0011aa"; root = store.projects_dir / project_id; root.mkdir(parents=True)
            raw = {"file_id": "raw-001", "stored_path": "projects/%s/raw/one.mov" % project_id, "metadata": {"duration_seconds": 10}, "analysis_status": "not_requested"}
            store.write_json(root / "manifest.json", {"project_id": project_id, "style_id": style_id, "raw_files": [raw], "provider": "pegasus", "prompt": "Edit", "target_duration_seconds": 5})
            timeline = empty_timeline(project_id, [asset_from_raw(raw, analyzed=False)])
            timeline["tracks"][0]["clips"] = [{"clip_id": "video-1", "kind": "video", "asset_id": "raw-001", "source_in_us": 0, "source_out_us": 5_000_000, "timeline_start_frame": 0, "duration_frames": 150, "playback_rate": 1.0, "linked_group_id": None, "transform": {"mode": "fill", "x": .5, "y": .5, "scale": 1}}]
            refresh_hash(timeline); TimelineStore(store).initialize(project_id, timeline)
            with self.assertRaisesRegex(ValueError, "unanalyzed"):
                await TimelineProposalService(store, engine=FakeProposalEngine()).create(project_id, "Change it")


if __name__ == "__main__":
    import unittest
    unittest.main()
