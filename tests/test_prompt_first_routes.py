import unittest

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


class PromptFirstProjectFlowTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        if settings.access_code:
            self.client.post("/access", data={"code": settings.access_code})

    def tearDown(self):
        self.client.close()

    def test_normal_flow_starts_with_a_plain_language_brief(self):
        response = self.client.get("/projects/new")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Describe the video you want", response.text)
        self.assertNotIn("Use a style", response.text)
        self.assertNotIn("Choose an editing style", response.text)

        response = self.client.post(
            "/projects/new/describe",
            data={"name": "Flow test", "description": "Make a fast chronological 45 second video."},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/projects/new/references")

        response = self.client.get("/projects/new/references")
        self.assertEqual(response.status_code, 200)
        self.assertIn("This step is optional", response.text)
        self.assertIn('for="reference-input"', response.text)
        self.assertIn("multiple required", response.text)
        self.assertIn("Tap to choose files", response.text)

        response = self.client.post(
            "/projects/new/references", data={"skip": "true"}, follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/projects/new/footage")

        response = self.client.get("/projects/new/footage")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Choose your footage", response.text)
        self.assertIn("length of your cut will come from your creative brief", response.text)
        self.assertNotIn("Choose an editing style", response.text)
        self.assertIn('for="footage-input"', response.text)

    def test_missing_reference_file_does_not_silently_skip(self):
        self.client.post(
            "/projects/new/describe",
            data={"name": "Reference test", "description": "Use the example's pacing."},
        )
        response = self.client.post("/projects/new/references", data={})
        self.assertEqual(response.status_code, 400)
        self.assertIn("The video was not attached", response.text)
        self.assertNotIn("Choose your footage", response.text)

    def test_retired_recipe_choice_urls_return_to_prompt_first_flow(self):
        for path in ("/projects/new/saved-style", "/projects/new/engine-decides"):
            response = self.client.get(path, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/projects/new")

    def test_offline_recovery_page_is_public_and_actionable(self):
        self.client.cookies.clear()
        response = self.client.get("/offline")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Your saved videos are safe", response.text)
        self.assertIn("Try connecting again", response.text)


if __name__ == "__main__":
    unittest.main()
