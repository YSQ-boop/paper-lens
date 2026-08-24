from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "evals" / "run_evals.py"
SPEC = importlib.util.spec_from_file_location("paper_lens_evals", RUNNER_PATH)
evals = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(evals)


class EvalHarnessTests(unittest.TestCase):
    def test_default_case_mix_and_selection(self) -> None:
        cases = evals.load_cases()
        self.assertEqual(sum(case["kind"] == "positive" for case in cases), 5)
        self.assertEqual(sum(case["kind"] == "negative" for case in cases), 3)
        selected = evals.select_cases(
            cases, ["transformer-en-quick", "scanned-local-pdf"]
        )
        self.assertEqual(
            [case["id"] for case in selected],
            ["transformer-en-quick", "scanned-local-pdf"],
        )
        with self.assertRaisesRegex(evals.EvalError, "Unknown evaluation"):
            evals.select_cases(cases, ["missing-case"])

    def test_judge_thresholds_reject_unsupported_or_weak_results(self) -> None:
        passing = {
            "grounding": 4,
            "coverage": 4,
            "uncertainty": 4,
            "formula_table_accuracy": 4,
            "overall": 4,
            "unsupported_claims": [],
        }
        self.assertTrue(evals.judge_passed(passing))
        self.assertFalse(
            evals.judge_passed({**passing, "unsupported_claims": ["invented result"]})
        )
        self.assertFalse(evals.judge_passed({**passing, "grounding": 3}))
        self.assertFalse(evals.judge_passed({**passing, "coverage": 3}))

    def test_secret_scrubbing(self) -> None:
        secret = "test-secret-value-do-not-log"
        scrubbed = evals.scrub(f"CODEX_API_KEY={secret} and {secret}", [secret])
        self.assertNotIn(secret, scrubbed)
        self.assertIn("[REDACTED]", scrubbed)

    def test_offline_suite_executes_negatives_and_synthetic_preparation(self) -> None:
        cases = evals.load_cases()
        selected_ids = {
            "synthetic-local-en-quick",
            "invalid-non-arxiv-url",
            "encrypted-local-pdf",
            "scanned-local-pdf",
        }
        selected = [case for case in cases if case["id"] in selected_ids]
        with tempfile.TemporaryDirectory() as directory:
            results = evals.offline_preflight(selected, Path(directory) / "output")
        self.assertEqual(len(results), 4)
        self.assertTrue(all(result["passed"] is True for result in results), results)


if __name__ == "__main__":
    unittest.main()
