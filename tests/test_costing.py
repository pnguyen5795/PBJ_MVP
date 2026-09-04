import unittest

from app.costing import analysis_cost_summary


class CostingTests(unittest.TestCase):
    def test_pegasus_estimate_uses_minutes_and_output_tokens(self):
        summary = analysis_cost_summary([{"file_id": "raw-001", "provider": "pegasus", "model": "pegasus1.5", "duration_seconds": 60, "usage": {"output_tokens": 1000}}])
        self.assertAlmostEqual(summary["estimated_usd"], 0.0367)

    def test_cached_analysis_has_no_new_provider_cost(self):
        summary = analysis_cost_summary([{
            "file_id": "raw-001", "provider": "pegasus", "model": "pegasus1.5",
            "duration_seconds": 60, "usage": {}, "cache": {"hit": True},
        }])
        self.assertEqual(summary["estimated_usd"], 0)
        self.assertIn("cache", summary["records"][0]["basis"].lower())


if __name__ == "__main__": unittest.main()
