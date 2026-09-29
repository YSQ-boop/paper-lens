from __future__ import annotations

import copy
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
    @staticmethod
    def complete_online_summary() -> dict:
        judgment = {
            "grounding": 4,
            "coverage": 4,
            "uncertainty": 4,
            "formula_table_accuracy": 4,
            "overall": 4,
            "unsupported_claims": [],
        }
        return {
            "schema_version": 1,
            "mode": "online",
            "created_at": "2026-09-29T05:00:00Z",
            "evaluation_date": "2026-09-29",
            "git_commit": "0123456789abcdef",
            "codex_version": "codex-cli 0.138.0",
            "model": "gpt-test-author",
            "judge_model": "gpt-test-judge",
            "selected_case_ids": ["synthetic-local-en-quick", "scanned-local-pdf"],
            "results": [
                {
                    "id": "synthetic-local-en-quick",
                    "kind": "positive",
                    "passed": True,
                    "deterministic_validation": True,
                    "judgment": judgment,
                    "usage": {
                        "author": {"input_tokens": 10, "output_tokens": 20},
                        "judge": {"input_tokens": 30, "output_tokens": 40},
                    },
                },
                {
                    "id": "scanned-local-pdf",
                    "kind": "negative",
                    "passed": True,
                    "error": "OCR is required",
                },
            ],
            "usage": {
                "author": {"input_tokens": 10, "output_tokens": 20},
                "judge": {"input_tokens": 30, "output_tokens": 40},
                "total": {"input_tokens": 40, "output_tokens": 60},
            },
            "passed": True,
        }

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

    def test_online_baseline_summary_contract_accepts_complete_payload(self) -> None:
        summary = self.complete_online_summary()
        self.assertEqual(evals.validate_baseline_summary(summary), [])

    def test_online_baseline_summary_contract_rejects_missing_metadata(self) -> None:
        summary = self.complete_online_summary()
        del summary["judge_model"]
        errors = evals.validate_baseline_summary(summary)
        self.assertTrue(any("judge_model" in error for error in errors), errors)

    def test_online_baseline_summary_contract_rejects_malformed_results(self) -> None:
        summary = self.complete_online_summary()
        malformed = copy.deepcopy(summary)
        malformed["results"][0]["judgment"]["grounding"] = 6
        malformed["results"][1]["id"] = "not-selected"
        malformed["passed"] = False
        errors = evals.validate_baseline_summary(malformed)
        self.assertTrue(any("grounding" in error for error in errors), errors)
        self.assertTrue(any("selected_case_ids" in error for error in errors), errors)
        self.assertTrue(any("deterministic result policy" in error for error in errors), errors)

    def test_summary_contract_rejects_unhashable_case_ids_without_crashing(self) -> None:
        summary = self.complete_online_summary()
        summary["selected_case_ids"] = [["nested-id"]]
        errors = evals.validate_baseline_summary(summary)
        self.assertTrue(any("selected_case_ids" in error for error in errors), errors)

    def test_online_run_summary_keeps_failed_case_without_scores(self) -> None:
        summary = self.complete_online_summary()
        failed = summary["results"][0]
        failed.clear()
        failed.update(
            {
                "id": "synthetic-local-en-quick",
                "kind": "positive",
                "passed": False,
                "error": "Codex timed out",
            }
        )
        summary["usage"] = {"author": {}, "judge": {}, "total": {}}
        summary["passed"] = False
        self.assertEqual(evals.validate_summary(summary, mode="online"), [])
        self.assertTrue(evals.validate_baseline_summary(summary))

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
