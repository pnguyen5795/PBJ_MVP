import unittest

from app.demo_lifecycle import DemoActivityTracker, DemoLifecycleManager


class DemoActivityTrackerTests(unittest.TestCase):
    def test_touch_and_request_counts_are_separate(self):
        now = [10.0]
        tracker = DemoActivityTracker(clock=lambda: now[0])
        now[0] = 25.0
        tracker.request_started()
        self.assertEqual(tracker.snapshot(), (15.0, 1, False))
        tracker.request_finished()
        tracker.touch()
        self.assertEqual(tracker.snapshot(), (0.0, 0, False))

    def test_request_count_never_becomes_negative(self):
        tracker = DemoActivityTracker(clock=lambda: 1.0)
        tracker.request_finished()
        self.assertEqual(tracker.snapshot()[1], 0)


class DemoLifecycleManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_suspend_requires_idle_no_requests_and_no_active_work(self):
        now = [0.0]
        tracker = DemoActivityTracker(clock=lambda: now[0])
        active = [False]
        calls = []

        async def suspend():
            calls.append(True)
            return True

        manager = DemoLifecycleManager(
            enabled=True, controller_url="https://controller.example",
            control_token="x" * 32, idle_seconds=900, tracker=tracker,
            has_active_work=lambda: active[0], post_suspend=suspend,
        )
        now[0] = 901.0
        tracker.request_started()
        self.assertFalse(await manager.attempt_suspend_if_idle())
        tracker.request_finished()
        active[0] = True
        self.assertFalse(await manager.attempt_suspend_if_idle())
        active[0] = False
        self.assertTrue(await manager.attempt_suspend_if_idle())
        self.assertEqual(len(calls), 1)
        self.assertFalse(await manager.attempt_suspend_if_idle())

    async def test_failed_controller_call_is_retryable(self):
        now = [901.0]
        tracker = DemoActivityTracker(clock=lambda: 0.0)
        results = [False, True]

        async def suspend():
            return results.pop(0)

        manager = DemoLifecycleManager(
            enabled=True, controller_url="https://controller.example",
            control_token="x" * 32, idle_seconds=900, tracker=tracker,
            has_active_work=lambda: False, post_suspend=suspend,
        )
        tracker._clock = lambda: now[0]
        self.assertFalse(await manager.attempt_suspend_if_idle())
        self.assertTrue(await manager.attempt_suspend_if_idle())

    async def test_disabled_manager_never_calls_controller(self):
        called = []

        async def suspend():
            called.append(True)
            return True

        tracker = DemoActivityTracker(clock=lambda: 1000.0)
        manager = DemoLifecycleManager(
            enabled=False, controller_url="", control_token="", idle_seconds=900,
            tracker=tracker, has_active_work=lambda: False, post_suspend=suspend,
        )
        self.assertFalse(await manager.attempt_suspend_if_idle())
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
