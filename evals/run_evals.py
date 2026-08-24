"""Run deterministic preflight checks and optional Codex/Judge evaluations."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "evals" / "cases.json"
JUDGE_SCHEMA = ROOT / "evals" / "judge.schema.json"
PIPELINE_PATH = ROOT / "skills" / "paper-lens" / "scripts" / "paper_pipeline.py"
SKILL_PATH = ROOT / "skills" / "paper-lens"
SCORE_FIELDS = (
    "grounding",
    "coverage",
    "uncertainty",
    "formula_table_accuracy",
    "overall",
)
CODEX_TIMEOUT_SECONDS = 20 * 60

SPEC = importlib.util.spec_from_file_location("paper_lens_eval_pipeline", PIPELINE_PATH)
pipeline = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pipeline)


class EvalError(RuntimeError):
    """A reproducible evaluation setup or execution failure."""


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def load_cases() -> list[dict[str, Any]]:
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("cases"), list):
        raise EvalError(
            "evals/cases.json must contain schema_version 1 and a cases list."
        )
    cases = payload["cases"]
    identifiers = [case.get("id") for case in cases]
    if any(
        not isinstance(identifier, str) or not identifier for identifier in identifiers
    ):
        raise EvalError("Every evaluation case needs a non-empty string id.")
    if len(set(identifiers)) != len(identifiers):
        raise EvalError("Evaluation case ids must be unique.")
    if sum(case.get("kind") == "positive" for case in cases) != 5:
        raise EvalError("The default suite must contain exactly five positive cases.")
    if sum(case.get("kind") == "negative" for case in cases) != 3:
        raise EvalError("The default suite must contain exactly three negative cases.")
    return cases


def select_cases(
    cases: list[dict[str, Any]], selected: list[str]
) -> list[dict[str, Any]]:
    if not selected:
        return cases
    by_id = {case["id"]: case for case in cases}
    unknown = sorted(set(selected) - set(by_id))
    if unknown:
        raise EvalError(f"Unknown evaluation case(s): {', '.join(unknown)}")
    return [by_id[identifier] for identifier in selected]


def make_text_pdf(path: Path) -> None:
    pipeline.require_pdf_support()
    document = pipeline.fitz.open()
    try:
        for index in range(4):
            page = document.new_page()
            text = (
                f"Page {index + 1}. Section {index + 1}. Synthetic Paper Lens evaluation. "
                "The method compares a bounded deterministic baseline with a proposed transformation. "
                "Table 1 reports synthetic accuracy and Figure 1 describes the data flow. "
                "Limitations include the small synthetic sample and absence of external validation. "
            ) * 12
            page.insert_textbox(pipeline.fitz.Rect(50, 50, 545, 790), text, fontsize=10)
        document.set_metadata(
            {"title": "Synthetic Grounding Fixture", "author": "Paper Lens test suite"}
        )
        document.save(path)
    finally:
        document.close()


def make_encrypted_pdf(path: Path) -> None:
    pipeline.require_pdf_support()
    document = pipeline.fitz.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), "Encrypted evaluation fixture")
        document.save(
            path,
            encryption=pipeline.fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="eval-secret",
        )
    finally:
        document.close()


def make_scanned_pdf(path: Path) -> None:
    pipeline.require_pdf_support()
    document = pipeline.fitz.open()
    try:
        document.new_page()
        document.save(path)
    finally:
        document.close()


def fixture_path(kind: str, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{kind}.pdf"
    if kind == "synthetic-text":
        make_text_pdf(path)
    elif kind == "encrypted":
        make_encrypted_pdf(path)
    elif kind == "scanned":
        make_scanned_pdf(path)
    else:
        raise EvalError(f"Unknown fixture kind: {kind}")
    return path


def run_negative_case(case: dict[str, Any], directory: Path) -> dict[str, Any]:
    input_value = str(case["input"])
    if case["input_kind"] == "fixture":
        input_value = str(fixture_path(input_value, directory))
    try:
        pipeline.prepare_paper(input_value, output_root=directory / "reports")
    except pipeline.PipelineError as exc:
        expected = str(case["expected_error"])
        matched = expected.lower() in str(exc).lower()
        return {
            "id": case["id"],
            "kind": "negative",
            "passed": matched,
            "error": str(exc),
        }
    return {
        "id": case["id"],
        "kind": "negative",
        "passed": False,
        "error": "Input unexpectedly succeeded.",
    }


def prefetch_positive(case: dict[str, Any], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{case['id']}.pdf"
    if case["input_kind"] == "fixture":
        make_text_pdf(destination)
        pipeline.prepare_paper(
            str(destination),
            case["mode"],
            directory / "preflight-reports",
            case["language"],
        )
        return destination
    if case["input_kind"] != "arxiv":
        raise EvalError(f"Unsupported positive input kind: {case['input_kind']}")
    workspace, _ = pipeline.prepare_paper(
        case["input"],
        "quick",
        directory / "prefetch-reports",
        case["language"],
        refresh=True,
    )
    shutil.copy2(workspace / "raw" / "paper.pdf", destination)
    return destination


def scrub(text: str, secrets: Iterable[str]) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = re.sub(r"(?i)(api[_-]?key\s*[:=]\s*)\S+", r"\1[REDACTED]", redacted)
    return redacted


def codex_environment(api_key: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment["CODEX_API_KEY"] = api_key
    runtime_bin = str(Path(sys.executable).resolve().parent)
    environment["PATH"] = runtime_bin + os.pathsep + environment.get("PATH", "")
    return environment


def run_command(
    command: list[str], cwd: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            text=True,
            capture_output=True,
            timeout=CODEX_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise EvalError(
            f"Command exceeded {CODEX_TIMEOUT_SECONDS} seconds: {command[0]}"
        ) from exc


def initialize_eval_repo(directory: Path, pdf_path: Path) -> Path:
    repo = directory / "repo"
    skill_target = repo / ".agents" / "skills" / "paper-lens"
    skill_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SKILL_PATH, skill_target)
    input_target = repo / "inputs" / "paper.pdf"
    input_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf_path, input_target)
    for command in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "paper-lens-eval@example.invalid"],
        ["git", "config", "user.name", "Paper Lens Eval"],
        ["git", "add", "."],
        ["git", "commit", "-qm", "evaluation fixture"],
    ):
        completed = subprocess.run(
            command,
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode:
            raise EvalError(
                f"Could not initialize temporary git repository: {completed.stderr.strip()}"
            )
    return repo


def codex_prompt(case: dict[str, Any], input_path: Path) -> str:
    language = "Chinese" if case["language"] == "zh" else "English"
    source_rule = (
        "Do not browse or use external literature. Mark external evidence partial and complete a source-only review."
        if case.get("source_only")
        else "Use only the supplied paper; do not browse external literature."
    )
    return (
        f"Use $paper-lens in {case['mode']} mode on {input_path}. Write the report in {language}. "
        f"{source_rule} Complete the generated report, run its deterministic validator, fix every error, "
        "and finish only when validation succeeds."
    )


def parse_jsonl_usage(output: str) -> dict[str, int]:
    totals: dict[str, int] = {}
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        usage = event.get("usage") if isinstance(event, dict) else None
        if not isinstance(usage, dict):
            continue
        for key, value in usage.items():
            if isinstance(value, int):
                totals[key] = max(totals.get(key, 0), value)
    return totals


def judge_passed(judgment: dict[str, Any]) -> bool:
    try:
        scores = [int(judgment[field]) for field in SCORE_FIELDS]
    except (KeyError, TypeError, ValueError):
        return False
    unsupported = judgment.get("unsupported_claims")
    return (
        isinstance(unsupported, list)
        and not unsupported
        and judgment["grounding"] >= 4
        and judgment["uncertainty"] >= 4
        and min(scores) >= 3
        and sum(scores) / len(scores) >= 4
    )


def run_judge(
    repo: Path,
    report_path: Path,
    judge_model: str,
    api_key: str,
) -> tuple[dict[str, Any], str, dict[str, int]]:
    source_path = report_path.parent / "cache" / "paper.txt"
    output_path = repo / "judge-result.json"
    prompt = (
        f"Evaluate {report_path} strictly against the original extracted paper text at {source_path}. "
        "Do not use the network or modify files. Score grounding, coverage, explicit uncertainty, "
        "formula/table accuracy, and overall quality from 1 to 5. List every major unsupported factual "
        "claim; use an empty list only when none exists. Output only the required JSON object."
    )
    command = [
        "codex",
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--sandbox",
        "read-only",
        "--json",
        "--model",
        judge_model,
        "--output-schema",
        str(JUDGE_SCHEMA),
        "-o",
        str(output_path),
        prompt,
    ]
    completed = run_command(command, repo, codex_environment(api_key))
    trace = scrub(completed.stdout + "\n" + completed.stderr, [api_key])
    if completed.returncode:
        raise EvalError(
            f"Judge Codex run failed with exit code {completed.returncode}: {trace[-2000:]}"
        )
    try:
        judgment = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalError(
            f"Judge did not produce valid structured output: {exc}"
        ) from exc
    return judgment, trace, parse_jsonl_usage(completed.stdout)


def run_positive_case(
    case: dict[str, Any],
    prefetched_pdf: Path,
    case_output: Path,
    model: str,
    judge_model: str,
    api_key: str,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="paper-lens-eval-") as directory:
        repo = initialize_eval_repo(Path(directory), prefetched_pdf)
        input_path = (repo / "inputs" / "paper.pdf").resolve()
        command = [
            "codex",
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--sandbox",
            "workspace-write",
            "--json",
            "--model",
            model,
            codex_prompt(case, input_path),
        ]
        completed = run_command(command, repo, codex_environment(api_key))
        author_trace = scrub(completed.stdout + "\n" + completed.stderr, [api_key])
        case_output.mkdir(parents=True, exist_ok=True)
        (case_output / "author-trace.jsonl").write_text(author_trace, encoding="utf-8")
        if completed.returncode:
            raise EvalError(
                f"Author Codex run failed with exit code {completed.returncode}: {author_trace[-2000:]}"
            )
        reports = sorted(repo.glob("paper-reports/*/report.md"))
        if len(reports) != 1:
            raise EvalError(f"Expected one generated report, found {len(reports)}.")
        report_path = reports[0]
        validation = pipeline.validate_workspace(report_path.parent, case["mode"])
        write_json(case_output / "validation.json", validation)
        shutil.copy2(report_path, case_output / "report.md")
        judgment, judge_trace, judge_usage = run_judge(
            repo, report_path, judge_model, api_key
        )
        (case_output / "judge-trace.jsonl").write_text(judge_trace, encoding="utf-8")
        write_json(case_output / "judgment.json", judgment)
        passed = bool(validation["ok"]) and judge_passed(judgment)
        return {
            "id": case["id"],
            "kind": "positive",
            "passed": passed,
            "deterministic_validation": bool(validation["ok"]),
            "judgment": judgment,
            "usage": {
                "author": parse_jsonl_usage(completed.stdout),
                "judge": judge_usage,
            },
        }


def offline_preflight(
    cases: list[dict[str, Any]], output: Path
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="paper-lens-offline-") as directory:
        fixture_root = Path(directory)
        for case in cases:
            if case["kind"] == "negative":
                results.append(run_negative_case(case, fixture_root / case["id"]))
            elif case["input_kind"] == "fixture":
                try:
                    prefetch_positive(case, fixture_root / case["id"])
                    results.append(
                        {
                            "id": case["id"],
                            "kind": "positive",
                            "passed": True,
                            "scope": "preparation-only",
                        }
                    )
                except Exception as exc:
                    results.append(
                        {
                            "id": case["id"],
                            "kind": "positive",
                            "passed": False,
                            "error": str(exc),
                        }
                    )
            else:
                results.append(
                    {
                        "id": case["id"],
                        "kind": "positive",
                        "passed": None,
                        "scope": "skipped-online-case",
                    }
                )
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case", action="append", default=[], help="Case id; repeat to select multiple"
    )
    parser.add_argument("--model", help="Required author model id for an online run")
    parser.add_argument("--judge-model", help="Judge model id; defaults to --model")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run schemas, fixtures, and negative cases only",
    )
    parser.add_argument(
        "--output", type=Path, help="Output directory (default: evals/runs/<UTC>)"
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        cases = select_cases(load_cases(), args.case)
        output = (args.output or (ROOT / "evals" / "runs" / utc_stamp())).resolve()
        output.mkdir(parents=True, exist_ok=False)
        if args.offline:
            results = offline_preflight(cases, output)
            failed = [result for result in results if result.get("passed") is False]
            summary = {
                "schema_version": 1,
                "mode": "offline",
                "created_at": utc_stamp(),
                "results": results,
                "passed": not failed,
                "note": "Online model cases were not scored.",
            }
            write_json(output / "summary.json", summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0 if not failed else 1

        if not args.model:
            raise EvalError("--model is required unless --offline is used.")
        api_key = os.environ.get("CODEX_API_KEY", "")
        if not api_key:
            raise EvalError("CODEX_API_KEY is required for an online evaluation run.")
        if shutil.which("codex") is None:
            raise EvalError("The codex executable is not available on PATH.")
        judge_model = args.judge_model or args.model

        results: list[dict[str, Any]] = []
        with tempfile.TemporaryDirectory(prefix="paper-lens-inputs-") as directory:
            prefetch_root = Path(directory)
            prefetched: dict[str, Path] = {}
            for case in cases:
                if case["kind"] == "positive":
                    case_root = prefetch_root / case["id"]
                    case_root.mkdir(parents=True, exist_ok=True)
                    prefetched[case["id"]] = prefetch_positive(case, case_root)
            for case in cases:
                try:
                    if case["kind"] == "negative":
                        case_root = prefetch_root / case["id"]
                        case_root.mkdir(parents=True, exist_ok=True)
                        result = run_negative_case(case, case_root)
                    else:
                        result = run_positive_case(
                            case,
                            prefetched[case["id"]],
                            output / case["id"],
                            args.model,
                            judge_model,
                            api_key,
                        )
                except Exception as exc:
                    result = {
                        "id": case["id"],
                        "kind": case["kind"],
                        "passed": False,
                        "error": scrub(str(exc), [api_key]),
                    }
                results.append(result)
                write_json(output / case["id"] / "result.json", result)

        summary = {
            "schema_version": 1,
            "mode": "online",
            "created_at": utc_stamp(),
            "git_commit": subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            ).stdout.strip(),
            "codex_version": subprocess.run(
                ["codex", "--version"], text=True, capture_output=True, check=False
            ).stdout.strip(),
            "model": args.model,
            "judge_model": judge_model,
            "results": results,
            "passed": all(result.get("passed") is True for result in results),
        }
        write_json(output / "summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["passed"] else 1
    except (EvalError, OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
