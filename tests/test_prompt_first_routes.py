import unittest

from fastapi.testclient import TestClient

from app.config import settings
import app.main as main_module


app = main_module.app


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
        self.assertIn('name="description"', response.text)
        self.assertIn(
            'maxlength="%d"' % main_module.PROJECT_DESCRIPTION_MAX_CHARS,
            response.text,
        )

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

    def test_largest_character_bounded_brief_keeps_session_cookie_below_browser_limit(self):
        response = self.client.post(
            "/projects/new/describe",
            data={
                "name": "N" * main_module.PROJECT_NAME_MAX_CHARS,
                "description": "D" * main_module.PROJECT_DESCRIPTION_MAX_CHARS,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        cookie = response.headers.get("set-cookie", "")
        self.assertTrue(cookie.startswith("session="))
        self.assertLess(len(cookie.encode("ascii")), 4096)

    def test_brief_character_limits_reject_oversized_ascii_and_unicode(self):
        cases = (
            {
                "name": "N" * (main_module.PROJECT_NAME_MAX_CHARS + 1),
                "description": "A useful brief",
            },
            {
                "name": "Project",
                "description": "x" * (main_module.PROJECT_DESCRIPTION_MAX_CHARS + 1),
            },
            {
                "name": "Project",
                "description": "🚀" * (main_module.PROJECT_DESCRIPTION_MAX_CHARS + 1),
            },
        )
        for payload in cases:
            with self.subTest(name_length=len(payload["name"]), description_length=len(payload["description"])):
                response = self.client.post("/projects/new/describe", data=payload)
                self.assertEqual(response.status_code, 400)

    def test_unicode_brief_must_also_fit_conservative_serialized_session_budget(self):
        description = "🚀" * 200
        self.assertLess(len(description), main_module.PROJECT_DESCRIPTION_MAX_CHARS)
        response = self.client.post(
            "/projects/new/describe",
            data={"name": "Unicode budget", "description": description},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("too long for this private demo", response.text)

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

    def test_retired_offline_cache_endpoints_are_absent(self):
        self.assertEqual(self.client.get("/offline").status_code, 404)
        self.assertEqual(self.client.get("/service-worker.js").status_code, 404)
        self.assertEqual(self.client.get("/static/service-worker.js").status_code, 404)


if __name__ == "__main__":
    unittest.main()
