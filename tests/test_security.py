import json
import os
import unittest
from base64 import b64decode, b64encode
from dataclasses import replace
from unittest.mock import patch

from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

import app.main as main_module
from app.config import LOCAL_SESSION_SECRET, Settings, settings, validate_settings
from app.security import LoginRateLimiter, MAX_SECRET_BYTES, exact_secret_match


class HostedSettingsSecurityTests(unittest.TestCase):
    def valid_hosted(self, **changes):
        values = {
            "hosted_mode": True,
            "https_only": True,
            "access_code": "PrivateBetaCode",
            "session_secret": "s" * 32,
        }
        values.update(changes)
        return replace(settings, **values)

    def test_valid_hosted_settings_pass(self):
        validate_settings(self.valid_hosted())

    def test_hosted_settings_require_access_code(self):
        with self.assertRaisesRegex(RuntimeError, "PBJ_ACCESS_CODE"):
            validate_settings(self.valid_hosted(access_code=""))

    def test_hosted_settings_reject_default_or_short_session_secret(self):
        for secret in (LOCAL_SESSION_SECRET, "too-short"):
            with self.subTest(secret_length=len(secret)):
                with self.assertRaisesRegex(RuntimeError, "PBJ_SESSION_SECRET"):
                    validate_settings(self.valid_hosted(session_secret=secret))

    def test_hosted_settings_require_secure_cookie_transport(self):
        with self.assertRaisesRegex(RuntimeError, "PBJ_HTTPS_ONLY"):
            validate_settings(self.valid_hosted(https_only=False))

    def test_demo_lifecycle_configuration_fails_closed(self):
        valid = self.valid_hosted(
            demo_lifecycle_enabled=True,
            demo_controller_url="https://pbnj-launcher.onrender.com",
            demo_control_token="c" * 32,
            demo_idle_seconds=900,
        )
        validate_settings(valid)
        for changes, message in (
            ({"demo_controller_url": "http://controller.example"}, "PBJ_DEMO_CONTROLLER_URL"),
            ({"demo_control_token": "short"}, "PBJ_DEMO_CONTROL_TOKEN"),
            ({"demo_idle_seconds": 599}, "PBJ_DEMO_IDLE_SECONDS"),
        ):
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(RuntimeError, message):
                    validate_settings(replace(valid, **changes))

    def test_configured_codes_use_the_same_utf8_byte_limit_as_login(self):
        validate_settings(self.valid_hosted(
            access_code="é" * (MAX_SECRET_BYTES // 2),
            owner_code="x" * MAX_SECRET_BYTES,
        ))
        for field_name, value in (
            ("access_code", "é" * (MAX_SECRET_BYTES // 2 + 1)),
            ("owner_code", "x" * (MAX_SECRET_BYTES + 1)),
        ):
            with self.subTest(field_name=field_name):
                with self.assertRaisesRegex(RuntimeError, "at most 256 bytes"):
                    validate_settings(self.valid_hosted(**{field_name: value}))

    def test_render_marker_forces_hosted_validation_for_any_app_flag(self):
        for configured_flag in (None, "false", "not-a-boolean"):
            environment = {"RENDER": "true"}
            if configured_flag is not None:
                environment["PBJ_HOSTED_MODE"] = configured_flag
            with self.subTest(configured_flag=configured_flag):
                with patch.dict(os.environ, environment, clear=False):
                    if configured_flag is None:
                        os.environ.pop("PBJ_HOSTED_MODE", None)
                    candidate = Settings(
                        access_code="", session_secret="s" * 32, https_only=True,
                    )
                    self.assertTrue(candidate.hosted_mode)
                    with self.assertRaisesRegex(RuntimeError, "PBJ_ACCESS_CODE"):
                        validate_settings(candidate)


class LoginLimiterTests(unittest.TestCase):
    def test_client_limit_expires_and_success_clears_client_bucket(self):
        now = [100.0]
        limiter = LoginRateLimiter(
            client_limit=2, global_limit=20, window_seconds=10,
            clock=lambda: now[0],
        )
        self.assertEqual(limiter.record_failure("client", "access"), 0)
        self.assertEqual(limiter.record_failure("client", "access"), 10)
        self.assertEqual(limiter.retry_after("client", "access"), 10)
        limiter.record_success("client", "access")
        self.assertEqual(limiter.retry_after("client", "access"), 0)
        limiter.record_failure("client", "access")
        now[0] = 111.0
        self.assertEqual(limiter.retry_after("client", "access"), 0)

    def test_endpoint_buckets_are_separate_and_client_map_is_bounded(self):
        limiter = LoginRateLimiter(
            client_limit=1, global_limit=20, window_seconds=10,
            max_clients=2, clock=lambda: 100.0,
        )
        self.assertEqual(limiter.record_failure("one", "access"), 10)
        self.assertEqual(limiter.retry_after("one", "owner"), 0)
        limiter.record_failure("two", "access")
        limiter.record_failure("three", "access")
        self.assertLessEqual(len(limiter._clients), 2)

    def test_global_limit_blocks_across_clients(self):
        limiter = LoginRateLimiter(
            client_limit=10, global_limit=2, window_seconds=10,
            clock=lambda: 100.0,
        )
        self.assertEqual(limiter.record_failure("one", "access"), 0)
        self.assertEqual(limiter.record_failure("two", "owner"), 10)
        self.assertEqual(limiter.retry_after("three", "access"), 10)


class PrivateBetaSecurityRouteTests(unittest.TestCase):
    def setUp(self):
        main_module.login_rate_limiter.reset()
        self.test_settings = replace(
            settings,
            hosted_mode=False,
            https_only=False,
            shared_workspace=False,
            access_code="ExactCode",
            owner_code="OwnerCode",
        )
        self.settings_patch = patch.object(main_module, "settings", self.test_settings)
        self.settings_patch.start()
        self.client = TestClient(main_module.app, base_url="https://testserver")

    def tearDown(self):
        self.client.close()
        self.settings_patch.stop()
        main_module.login_rate_limiter.reset()

    def signed_session(self, payload):
        return TimestampSigner(settings.session_secret).sign(
            b64encode(json.dumps(payload).encode())
        ).decode()

    def decoded_session(self):
        value = self.client.cookies.get("session")
        unsigned = TimestampSigner(settings.session_secret).unsign(value)
        return json.loads(b64decode(unsigned))

    def test_access_and_owner_codes_are_exact_and_have_distinct_privileges(self):
        for wrong in ("exactcode", " ExactCode", "ExactCode ", "ＥxactCode"):
            with self.subTest(wrong=wrong):
                response = self.client.post(
                    "/access", data={"code": wrong}, follow_redirects=False,
                )
                self.assertEqual(response.status_code, 303)
                self.assertIn("error=true", response.headers["location"])

        response = self.client.post(
            "/access", data={"code": "ExactCode"}, follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertFalse(self.decoded_session()["owner"])

        self.client.cookies.clear()
        response = self.client.post(
            "/access", data={"code": "OwnerCode"}, follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(self.decoded_session()["owner"])

    def test_secret_helper_rejects_non_strings_and_oversized_values(self):
        self.assertTrue(exact_secret_match("same", "same"))
        self.assertFalse(exact_secret_match(None, "same"))
        self.assertFalse(exact_secret_match("x" * 257, "x" * 257))
        self.assertFalse(exact_secret_match("same", "x" * 257))

    def test_internal_suspend_confirmation_requires_token_and_current_idle_state(self):
        demo_settings = replace(
            self.test_settings,
            demo_lifecycle_enabled=True,
            demo_controller_url="https://controller.example",
            demo_control_token="c" * 32,
            demo_idle_seconds=900,
        )
        with patch.object(main_module, "settings", demo_settings):
            denied = self.client.post("/internal/demo/can-suspend")
            self.assertEqual(denied.status_code, 401)
            headers = {"Authorization": "Bearer " + demo_settings.demo_control_token}
            with patch.object(main_module.demo_activity, "snapshot", return_value=(901, 0, False)), patch.object(main_module, "has_active_demo_work", return_value=False):
                allowed = self.client.post("/internal/demo/can-suspend", headers=headers)
            self.assertEqual(allowed.status_code, 200)
            self.assertEqual(allowed.json(), {"allowed": True})
            with patch.object(main_module.demo_activity, "snapshot", return_value=(901, 1, False)), patch.object(main_module, "has_active_demo_work", return_value=False):
                active = self.client.post("/internal/demo/can-suspend", headers=headers)
            self.assertEqual(active.json(), {"allowed": False})

    def test_access_forms_reject_oversized_bodies_before_secret_comparison(self):
        oversized = b"code=" + (b"x" * main_module.ACCESS_FORM_MAX_BYTES)
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        with patch.object(main_module, "exact_secret_match") as secret_match:
            response = self.client.post(
                "/access", content=oversized, headers=headers,
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 413)
            secret_match.assert_not_called()

            self.client.cookies.set("session", self.signed_session({
                "authorized": True, "owner": False, "device_id": "device-stable",
            }), domain="testserver.local", path="/")
            response = self.client.post(
                "/owner-access", content=oversized, headers=headers,
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 413)
            secret_match.assert_not_called()

    def test_access_form_rejects_malformed_content_length_before_comparison(self):
        with patch.object(main_module, "exact_secret_match") as secret_match:
            for value in ("not-a-number", "-1"):
                with self.subTest(content_length=value):
                    response = self.client.post(
                        "/access", content=b"code=ExactCode",
                        headers={
                            "Content-Type": "application/x-www-form-urlencoded",
                            "Content-Length": value,
                        },
                        follow_redirects=False,
                    )
                    self.assertEqual(response.status_code, 400)
            secret_match.assert_not_called()

    def test_chunked_access_form_is_bounded_without_content_length(self):
        def oversized_chunks():
            yield b"code="
            yield b"x" * main_module.ACCESS_FORM_MAX_BYTES

        with patch.object(main_module, "exact_secret_match") as secret_match:
            response = self.client.post(
                "/access", content=oversized_chunks(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                follow_redirects=False,
            )
        self.assertNotIn("content-length", response.request.headers)
        self.assertEqual(response.status_code, 413)
        secret_match.assert_not_called()

    def test_route_throttling_returns_retry_after_without_echoing_code(self):
        limiter = LoginRateLimiter(client_limit=2, global_limit=20, window_seconds=60)
        with patch.object(main_module, "login_rate_limiter", limiter):
            first = self.client.post(
                "/access", data={"code": "not-the-code"}, follow_redirects=False,
            )
            second = self.client.post(
                "/access", data={"code": "not-the-code"}, follow_redirects=False,
            )
        self.assertEqual(first.status_code, 303)
        self.assertEqual(second.status_code, 429)
        self.assertIn("Retry-After", second.headers)
        self.assertNotIn("not-the-code", second.text)

    def test_logout_removes_privileges_and_preserves_local_device_identity(self):
        self.client.cookies.set("session", self.signed_session({
            "authorized": True, "owner": True, "device_id": "device-stable",
            "project_draft": {"description": "private"},
            "active_upload_session_id": "upload-private",
        }), domain="testserver.local", path="/")
        response = self.client.post("/logout", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/access")
        session = self.decoded_session()
        self.assertEqual(session, {"device_id": "device-stable"})
        blocked = self.client.get("/projects", follow_redirects=False)
        self.assertEqual(blocked.status_code, 303)
        self.assertEqual(blocked.headers["location"], "/access")

    def test_hosted_mutations_require_same_origin_metadata(self):
        hosted = replace(
            self.test_settings, hosted_mode=True, https_only=True,
            session_secret="h" * 32,
        )
        with patch.object(main_module, "settings", hosted):
            missing = self.client.post(
                "/access", data={"code": "ExactCode"}, follow_redirects=False,
            )
            cross_site = self.client.post(
                "/access", data={"code": "ExactCode"},
                headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
                follow_redirects=False,
            )
            allowed = self.client.post(
                "/access", data={"code": "ExactCode"},
                headers={"Origin": "https://testserver", "Sec-Fetch-Site": "same-origin"},
                follow_redirects=False,
            )
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(cross_site.status_code, 403)
        self.assertEqual(allowed.status_code, 303)

    def test_cross_site_mutation_cannot_use_an_authenticated_session(self):
        self.client.cookies.set("session", self.signed_session({
            "authorized": True, "owner": True, "device_id": "device-stable",
        }), domain="testserver.local", path="/")
        response = self.client.post(
            "/logout",
            headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.decoded_session()["authorized"])

    def test_security_headers_cover_dynamic_redirects_and_public_assets(self):
        access = self.client.get("/access")
        self.assertEqual(access.headers["x-frame-options"], "DENY")
        self.assertEqual(access.headers["x-content-type-options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", access.headers["content-security-policy"])
        self.assertEqual(access.headers["cache-control"], "private, no-store")

        redirect = self.client.post(
            "/access", data={"code": "wrong"}, follow_redirects=False,
        )
        self.assertEqual(redirect.headers["cache-control"], "private, no-store")
        css = self.client.get("/ui.css")
        self.assertIn("public", css.headers["cache-control"])

        hosted = replace(
            self.test_settings, hosted_mode=True, https_only=True,
            session_secret="h" * 32,
        )
        with patch.object(main_module, "settings", hosted):
            hosted_access = self.client.get("/access")
        self.assertEqual(
            hosted_access.headers["strict-transport-security"], "max-age=31536000",
        )

    def test_unhandled_500_has_full_security_headers_and_safe_body(self):
        hosted = replace(
            self.test_settings, hosted_mode=True, https_only=True,
            session_secret="h" * 32,
        )
        with patch.object(main_module, "settings", hosted):
            with patch.object(
                main_module.templates, "TemplateResponse",
                side_effect=RuntimeError("sensitive internal detail"),
            ):
                with TestClient(
                    main_module.app, base_url="https://testserver",
                    raise_server_exceptions=False,
                ) as client:
                    response = client.get("/access")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.text, "Internal Server Error")
        self.assertNotIn("sensitive internal detail", response.text)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["referrer-policy"], "same-origin")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertEqual(
            response.headers["permissions-policy"],
            "camera=(), microphone=(), geolocation=()",
        )
        self.assertEqual(
            response.headers["strict-transport-security"], "max-age=31536000",
        )


if __name__ == "__main__":
    unittest.main()
