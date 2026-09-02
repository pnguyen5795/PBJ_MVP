from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent


class HostedDemoConfigTests(unittest.TestCase):
    def test_blueprint_is_free_and_has_no_paid_disk(self):
        blueprint = (ROOT / "render.yaml").read_text()
        self.assertIn("name: pbj", blueprint)
        self.assertIn("plan: free", blueprint)
        self.assertNotIn("disk:", blueprint)
        self.assertIn("value: /tmp/pbj-data", blueprint)

    def test_blueprint_keeps_secrets_out_of_git(self):
        blueprint = (ROOT / "render.yaml").read_text()
        for key in ("PBJ_ACCESS_CODE", "PBJ_OWNER_CODE", "OPENAI_API_KEY", "TWELVE_LABS_API_KEY"):
            self.assertIn("key: %s\n        sync: false" % key, blueprint)

    def test_container_binds_render_port_with_one_worker(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("--port ${PORT:-10000} --workers 1", dockerfile)
        self.assertIn("ffmpeg", dockerfile)


if __name__ == "__main__":
    unittest.main()
