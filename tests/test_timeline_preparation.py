from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase

from app.storage import JsonStore
from app.workflows import TimelinePreparationWorkflow


class FakePlanner:
    async def plan_rough_cut(self, project, style, content_map):
        return {
            "target": {"width": 1080, "height": 1920}, "decision_model": "fixture",
            "video_segments": [{"source_file_id": "raw-001", "source_start": 0, "source_end": 2, "timeline_start": 0, "timeline_end": 2, "speed": 1, "crop_mode": "center_crop", "focal_x": .5, "focal_y": .5, "zoom_start": 1, "zoom_end": 1, "transition": "cut", "transition_duration": 0, "style_reasons": []}],
            "audio_segments": [{"source_file_id": "raw-001", "source_start": 0, "source_end": 2, "timeline_start": 0, "timeline_end": 2, "speed": 1}],
            "decision_metadata": {},
        }


class FakeRepairPlanner(FakePlanner):
    def __init__(self): self.repair_calls = []

    async def plan_rough_cut(self, project, style, content_map):
        plan = await super().plan_rough_cut(project, style, content_map)
        plan["video_segments"][0]["zoom_start"] = 5
        plan["video_segments"][0]["zoom_end"] = 5
        plan["selection"] = {"selected_candidates": []}
        return plan

    async def repair_rough_cut(self, project, plan, selected_candidates, validation_error):
        self.repair_calls.append(validation_error)
        repaired = await FakePlanner().plan_rough_cut(project, {}, {})
        repaired["repair_metadata"] = {
            "agent_key": "repair", "agent_name": "PB&J Timeline Repair Agent",
            "agent_role_version": "timeline-repair-agent-v1", "model": "gpt-5.6-luna",
            "reasoning_effort": "medium", "response_id": "repair-test", "usage": {},
            "prompt_version": "timeline-repair-v1",
        }
        return repaired


class TimelinePreparationTests(IsolatedAsyncioTestCase):
    async def test_first_pass_creates_populated_timeline_without_rendering_mp4(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data")
            style_id = "style-20260827-aabbcc"; style_root = store.styles_dir / style_id; style_root.mkdir(parents=True)
            store.write_json(style_root / "profile.json", {"style_id": style_id, "recipe": {"rules": []}, "recipe_version": "1.0.0"})
            project_id = "project-20260827-ddeeff"; root = store.projects_dir / project_id; root.mkdir(parents=True)
            raw = {"file_id": "raw-001", "original_name": "one.mov", "stored_path": "projects/%s/raw/one.mov" % project_id, "sha256": "a" * 64, "analysis_status": "complete", "metadata": {"duration_seconds": 5, "has_audio": True}}
            project = {"project_id": project_id, "style_id": style_id, "recipe_version": "1.0.0", "raw_files": [raw], "provider": "pegasus", "prompt": "Two second edit", "target_duration_seconds": 2, "content_map": {"files": []}, "status": "footage_analyzed"}
            store.write_json(root / "manifest.json", project)
            completed = await TimelinePreparationWorkflow(store, decision_engine=FakePlanner()).create(project_id)
            self.assertEqual(completed["status"], "timeline_ready")
            self.assertNotIn("proxy_report", completed)
            self.assertFalse((root / "proxies").exists())
            timeline = store.read_json(root / "timeline" / "current.json")
            self.assertTrue(timeline["tracks"][0]["clips"])
            self.assertFalse((root / "runs").exists())
            self.assertFalse((root / "exports").exists())

    async def test_invalid_initial_timeline_gets_bounded_agent_repair(self):
        with TemporaryDirectory() as folder:
            store = JsonStore(Path(folder) / "data")
            style_id = "style-20260827-aa22cc"; style_root = store.styles_dir / style_id; style_root.mkdir(parents=True)
            store.write_json(style_root / "profile.json", {"style_id": style_id, "recipe": {"rules": []}, "recipe_version": "1.0.0"})
            project_id = "project-20260827-dd33ee"; root = store.projects_dir / project_id; root.mkdir(parents=True)
            raw = {"file_id": "raw-001", "original_name": "one.mov", "stored_path": "projects/%s/raw/one.mov" % project_id, "sha256": "a" * 64, "analysis_status": "complete", "metadata": {"duration_seconds": 5, "has_audio": True}}
            project = {"project_id": project_id, "style_id": style_id, "recipe_version": "1.0.0", "raw_files": [raw], "provider": "pegasus", "prompt": "Two second edit", "target_duration_seconds": 2, "content_map": {"files": []}, "status": "footage_analyzed"}
            store.write_json(root / "manifest.json", project)
            planner = FakeRepairPlanner()
            completed = await TimelinePreparationWorkflow(store, decision_engine=planner).create(project_id)
            self.assertEqual(completed["status"], "timeline_ready")
            self.assertEqual(len(planner.repair_calls), 1)
            plan = store.read_json(root / "timeline" / "initial_edit_plan.json")
            self.assertEqual(plan["decision_metadata"]["repair_attempts"][0]["agent_role_version"], "timeline-repair-agent-v1")


if __name__ == "__main__":
    import unittest
    unittest.main()
