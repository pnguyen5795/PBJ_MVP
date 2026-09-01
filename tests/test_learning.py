import unittest

from app.learning import consolidate_signals, extract_requirements, permission_scoped_signals, relevant_signals, summarize_run_evidence


class LearningLoopTests(unittest.TestCase):
    def test_extracts_enforceable_project_requirements(self):
        requirements = extract_requirements("Keep this chronological, include the iPad clip, and use B-roll.")
        identifiers = {item["requirement_id"] for item in requirements}
        self.assertIn("chronological", identifiers)
        self.assertIn("b_roll", identifiers)
        self.assertIn("include_ipad_clip", identifiers)

    def test_repeated_projects_promote_only_after_threshold(self):
        signals = [{"type": "cut_revision", "project_id": "project-%d" % index,
                    "focus": ["Pacing"], "instruction": "Keep the faster pacing",
                    "feedback_classification": {"feedback_polarity": "positive"}}
                   for index in range(5)]
        state = consolidate_signals(signals)
        pacing = next(item for item in state["insights"] if item["category"] == "pacing")
        self.assertEqual(pacing["status"], "promoted_overlay")
        self.assertEqual(pacing["project_count"], 5)

    def test_corrective_revisions_do_not_count_as_positive_recipe_support(self):
        signals = [{"type": "cut_revision", "project_id": "project-%d" % index,
                    "focus": ["Pacing"], "instruction": "Make the pacing faster",
                    "feedback_classification": {"feedback_polarity": "corrective"}}
                   for index in range(5)]
        state = consolidate_signals(signals)
        pacing = next(item for item in state["insights"] if item["category"] == "pacing")
        self.assertEqual(pacing["status"], "candidate")
        self.assertEqual(pacing["supporting_project_count"], 0)

    def test_retrieval_prefers_same_project_and_matching_prompt(self):
        signals = [
            {"signal_id": "other", "type": "approved_cut", "project_id": "p2", "instruction": "Use quiet audio"},
            {"signal_id": "same", "type": "cut_revision", "project_id": "p1", "instruction": "Keep chronological order"},
        ]
        selected = relevant_signals(signals, "Make this chronological", "p1")
        self.assertEqual(selected[0]["signal_id"], "same")

    def test_project_learning_does_not_cross_device_boundary(self):
        signals = [
            {"signal_id": "same-project", "project_id": "p1", "device_id": "device-a"},
            {"signal_id": "same-device", "project_id": "p2", "device_id": "device-a"},
            {"signal_id": "other-device", "project_id": "p3", "device_id": "device-b"},
            {"signal_id": "shared-reference", "type": "reference_analysis"},
        ]
        allowed = permission_scoped_signals(signals, "p1", "device-a")
        self.assertEqual(
            {item["signal_id"] for item in allowed},
            {"same-project", "same-device", "shared-reference"},
        )

    def test_run_evidence_is_compact_and_does_not_promote_style(self):
        evidence = summarize_run_evidence(
            {"run_id": "run-1", "revision_number": 2, "feedback": "Open faster", "plan_path": "plan.json"},
            {"change_count": 2, "summary": {"added": 1, "removed": 1, "modified": 0, "retained": 2}},
            {"decisions": [
                {"source_file_id": "raw-1", "timeline_start": 0, "timeline_end": 3},
                {"source_file_id": "raw-2", "timeline_start": 3, "timeline_end": 8},
            ]},
            {"plan_hash": "p", "compiled_command_hash": "c", "output": {"sha256": "o"},
             "recipe_version": "1.0.0", "verification": {"checks": {"black_frames": {"status": "passed", "required": True}}}},
        )
        self.assertEqual(evidence["decision_count"], 2)
        self.assertEqual(evidence["selected_timeline_duration_seconds"], 8)
        self.assertEqual(evidence["selected_segments_by_source"], {"raw-1": 1, "raw-2": 1})
        state = consolidate_signals([{"type": "rough_cut_run", "project_id": "p1", "run_evidence": evidence}])
        self.assertEqual(state["insights"], [])


if __name__ == "__main__":
    unittest.main()
