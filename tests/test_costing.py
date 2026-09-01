import unittest

from app.costing import analysis_cost_summary


class CostingTests(unittest.TestCase):
    def test_pegasus_estimate_uses_minutes_and_output_tokens(self):
        summary = analysis_cost_summary([{"file_id": "raw-001", "provider": "pegasus", "model": "pegasus1.5", "duration_seconds": 60, "usage": {"output_tokens": 1000}}])
        self.assertAlmostEqual(summary["estimated_usd"], 0.0367)

    def test_gemini_estimate_includes_thinking_tokens(self):
        summary = analysis_cost_summary([{"file_id": "raw-001", "provider": "gemini", "model": "gemini-3.7-flash", "duration_seconds": 60, "usage": {"prompt_token_count": 1_000_000, "candidates_token_count": 100_000, "thoughts_token_count": 100_000}}])
        self.assertAlmostEqual(summary["estimated_usd"], 1.5)

    def test_cached_analysis_has_no_new_provider_cost(self):
        summary = analysis_cost_summary([{
            "file_id": "raw-001", "provider": "pegasus", "model": "pegasus1.5",
            "duration_seconds": 60, "usage": {}, "cache": {"hit": True},
        }])
        self.assertEqual(summary["estimated_usd"], 0)
        self.assertIn("cache", summary["records"][0]["basis"].lower())


if __name__ == "__main__": unittest.main()
