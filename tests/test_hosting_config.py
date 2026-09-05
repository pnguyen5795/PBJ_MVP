from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parent.parent


class HostedDemoConfigTests(unittest.TestCase):
    def test_blueprint_uses_two_gigabyte_compute_and_has_no_paid_disk(self):
        blueprint = (ROOT / "render.yaml").read_text()
        self.assertIn("name: pbnj", blueprint)
        self.assertIn("plan: 1c-2g", blueprint)
        self.assertNotIn("disk:", blueprint)
        self.assertIn("value: /tmp/pbj-data", blueprint)
        self.assertIn("key: PBJ_LOW_MEMORY_MODE\n        value: \"true\"", blueprint)
        self.assertNotIn("pbnj-launcher", blueprint)

    def test_blueprint_keeps_secrets_out_of_git(self):
        blueprint = (ROOT / "render.yaml").read_text()
        for key in ("PBJ_ACCESS_CODE", "PBJ_OWNER_CODE", "OPENAI_API_KEY", "TWELVE_LABS_API_KEY"):
            self.assertIn("key: %s\n        sync: false" % key, blueprint)
        self.assertIn("key: PBJ_SESSION_SECRET\n        generateValue: true", blueprint)
        self.assertNotRegex(blueprint, r"rnd_[A-Za-z0-9]")
        self.assertNotIn("PBJ_RENDER_API_KEY", blueprint)
        self.assertNotIn("PBJ_DEMO_CONTROL_TOKEN", blueprint)

    def test_deploys_wait_for_checks_and_use_render_maximum_shutdown_window(self):
        blueprint = (ROOT / "render.yaml").read_text()
        self.assertIn("autoDeployTrigger: checksPass", blueprint)
        self.assertIn("maxShutdownDelaySeconds: 300", blueprint)
        self.assertNotIn("autoDeployTrigger: commit", blueprint)

    def test_ci_runs_complete_checks_and_pins_third_party_actions(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("pull_request:", workflow)
        self.assertIn("- codex/hosted-demo", workflow)
        self.assertIn("python -m unittest discover -s tests", workflow)
        uses = re.findall(r"uses:\s+([^\s#]+)", workflow)
        self.assertTrue(uses)
        for action in uses:
            self.assertRegex(action, r"^[^@]+@[0-9a-f]{40}$")

    def test_container_binds_render_port_with_one_worker(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("--port ${PORT:-10000} --workers 1", dockerfile)
        self.assertIn("--no-server-header", dockerfile)
        self.assertIn("--timeout-graceful-shutdown 240", dockerfile)
        self.assertIn("ffmpeg", dockerfile)

    def test_app_lifespan_gates_and_cancels_media_processes(self):
        import app.main as main_module

        self.assertIn(main_module.start_media_process_runtime, main_module.app.router.on_startup)
        self.assertIn(main_module.shutdown_media_process_runtime, main_module.app.router.on_shutdown)


if __name__ == "__main__":
    unittest.main()
