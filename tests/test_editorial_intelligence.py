import unittest

from app.editorial_intelligence import (
    approval_outcomes, classify_feedback, interpret_brief, match_recipe,
    retrieve_approved_examples,
)


class EditorialIntelligenceTests(unittest.TestCase):
    def style(self, style_id, summary, default=False):
        return {
            "style_id": style_id, "label": summary, "recipe_version": "1.0.0",
            "system_default": default, "updated_at": "2026-08-26",
            "approval": {"approved": True},
            "recipe": {"summary": summary, "creative_principles": [], "rules": []},
        }

    def test_brief_is_interpreted_and_matching_is_invisible_and_auditable(self):
        intent = interpret_brief("Fast energetic opening with reactions", 45)
        matched = match_recipe(intent, [
            self.style("style-20260826-aaaaaa", "calm reflective story", True),
            self.style("style-20260826-bbbbbb", "fast energetic reaction driven opening"),
        ])
        self.assertEqual(intent["pacing"], "fast")
        self.assertEqual(matched["selected_recipe_id"], "style-20260826-bbbbbb")
        self.assertTrue(matched["reasons"])

    def test_examples_never_cross_recipe_boundary(self):
        intent = interpret_brief("Fast flight reaction", 60)
        examples = [
            {"example_id": "right", "style_id": "recipe-a", "project_prompt": "fast flight reaction", "target_duration_seconds": 60, "revision_number": 1},
            {"example_id": "wrong", "style_id": "recipe-b", "project_prompt": "fast flight reaction", "target_duration_seconds": 60, "revision_number": 1},
        ]
        retrieved = retrieve_approved_examples(examples, intent, "recipe-a", 60)
        self.assertEqual([item["example_id"] for item in retrieved], ["right"])

    def test_examples_never_cross_device_boundary(self):
        intent = interpret_brief("Fast flight reaction", 60)
        examples = [
            {"example_id": "mine", "style_id": "recipe-a", "device_id": "device-a", "project_prompt": "fast flight reaction", "target_duration_seconds": 60, "revision_number": 1},
            {"example_id": "theirs", "style_id": "recipe-a", "device_id": "device-b", "project_prompt": "fast flight reaction", "target_duration_seconds": 60, "revision_number": 1},
        ]
        retrieved = retrieve_approved_examples(examples, intent, "recipe-a", 60, device_id="device-a")
        self.assertEqual([item["example_id"] for item in retrieved], ["mine"])

    def test_feedback_is_applied_only_to_project(self):
        result = classify_feedback("I always prefer a faster opening")
        self.assertEqual(result["applied_scope"], "project_only")
        self.assertEqual(result["suggested_scope"], "user_preference_candidate")
        self.assertTrue(result["requires_confirmation"])

    def test_feedback_polarity_distinguishes_correction_confirmation_and_neutral(self):
        self.assertEqual(classify_feedback("Make the pacing faster")["feedback_polarity"], "corrective")
        self.assertEqual(classify_feedback("This is great, keep this pacing")["feedback_polarity"], "positive")
        self.assertEqual(classify_feedback("Please review this")["feedback_polarity"], "neutral")

    def test_approval_metrics_measure_source_time_retention(self):
        initial = {"video_segments": [
            {"source_file_id": "raw-001", "source_start": 0, "source_end": 10},
            {"source_file_id": "raw-002", "source_start": 0, "source_end": 10},
        ]}
        approved = {"video_segments": [
            {"source_file_id": "raw-001", "source_start": 0, "source_end": 5},
            {"source_file_id": "raw-003", "source_start": 0, "source_end": 5},
        ]}
        metrics = approval_outcomes(initial, approved, 2)
        self.assertEqual(metrics["first_cut_retention_ratio"], .25)
        self.assertTrue(metrics["opening_retained"])
        self.assertFalse(metrics["ending_retained"])


if __name__ == "__main__":
    unittest.main()
