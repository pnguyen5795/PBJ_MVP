import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from launcher.main import LauncherSettings, create_app, exact_secret_match, validate_settings


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeAsyncClient:
    state = "suspended"
    actions = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, **kwargs):
        if url.startswith("https://api.render.com/"):
            return FakeResponse(200, {"suspended": self.state})
        return FakeResponse(200)

    async def post(self, url, **kwargs):
        if url.endswith("/internal/demo/can-suspend"):
            return FakeResponse(200, {"allowed": True})
        action = url.rsplit("/", 1)[-1]
        self.actions.append(action)
        type(self).state = "suspended" if action == "suspend" else "not_suspended"
        return FakeResponse(202)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        FakeAsyncClient.state = "suspended"
        FakeAsyncClient.actions = []
        self.settings = LauncherSettings(
            target_service_id="srv-dacba3afngtc73cq6hm0",
            target_url="https://pbnj.onrender.com",
            render_api_key="rnd_" + "r" * 32,
            control_token="c" * 32,
            access_code="ExactDemoCode",
            session_secret="s" * 32,
        )
        self.http_patch = patch("launcher.main.httpx.AsyncClient", FakeAsyncClient)
        self.http_patch.start()
        self.client = TestClient(
            create_app(self.settings), base_url="https://launcher.example",
        )
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.http_patch.stop()

    def log_in(self):
        return self.client.post(
            "/access", data={"code": "ExactDemoCode"}, follow_redirects=False,
        )

    def test_login_is_exact_and_start_resumes_target(self):
        wrong = self.client.post(
            "/access", data={"code": "exactdemocode"}, follow_redirects=False,
        )
        self.assertEqual(wrong.headers["location"], "/?error=1")
        accepted = self.log_in()
        self.assertEqual(accepted.headers["location"], "/start")
        page = self.client.get("/start")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Starting PBJ", page.text)
        self.assertEqual(FakeAsyncClient.actions, ["resume"])

    def test_status_requires_login(self):
        self.assertEqual(self.client.get("/status").status_code, 401)
        self.log_in()
        self.assertEqual(self.client.get("/status").json(), {"ready": True})

    def test_internal_suspend_requires_shared_bearer_secret(self):
        self.assertEqual(self.client.post("/internal/suspend").status_code, 401)
        FakeAsyncClient.state = "not_suspended"
        response = self.client.post(
            "/internal/suspend",
            headers={"Authorization": "Bearer " + self.settings.control_token},
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(FakeAsyncClient.actions, ["suspend"])

    def test_internal_suspend_honors_final_target_veto(self):
        FakeAsyncClient.state = "not_suspended"
        original_post = FakeAsyncClient.post

        async def veto(client, url, **kwargs):
            if url.endswith("/internal/demo/can-suspend"):
                return FakeResponse(200, {"allowed": False})
            return await original_post(client, url, **kwargs)

        with patch.object(FakeAsyncClient, "post", veto):
            response = self.client.post(
                "/internal/suspend",
                headers={"Authorization": "Bearer " + self.settings.control_token},
            )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(FakeAsyncClient.actions, [])

    def test_security_headers_and_body_limit(self):
        response = self.client.get("/")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        oversized = "code=" + "x" * 1024
        response = self.client.post(
            "/access", content=oversized,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(response.status_code, 413)

    def test_configuration_and_secret_validation(self):
        validate_settings(self.settings)
        self.assertTrue(exact_secret_match("same", "same"))
        self.assertFalse(exact_secret_match("Same", "same"))
        with self.assertRaisesRegex(RuntimeError, "PBJ_TARGET_URL"):
            validate_settings(LauncherSettings(
                **{**self.settings.__dict__, "target_url": "http://pbnj.example"}
            ))


if __name__ == "__main__":
    unittest.main()
