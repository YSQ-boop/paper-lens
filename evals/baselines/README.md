# Evaluation baselines

No model score is committed until a maintainer has run the complete suite, inspected every report and unsupported-claim finding, and recorded the exact model IDs and Codex CLI version.

To create a candidate baseline:

```bash
CODEX_API_KEY=... python3 evals/run_evals.py --model '<model-id>'
```

Copy only the reviewed aggregate `summary.json` into this directory. The public contract is documented in [`summary.schema.json`](summary.schema.json) and is checked by the harness before an online run can finish. Do not commit evaluator run directories, PDFs, arXiv source archives, cached paper text, secrets, or raw private-paper prompts. A baseline must state the date, Paper Lens commit, Codex CLI version, author model, judge model, selected cases, pass/fail result, per-case scores, and aggregated author/judge/total token usage. Failed cases remain visible.

The deterministic contract check can be exercised without credentials:

```bash
python3 evals/run_evals.py --offline
python3 -m unittest tests.test_evals
```

Offline output is a preparation report only. It must not be copied here as an online model baseline.

The repository currently claims no online baseline. This explicit pending state prevents application materials from presenting unmeasured quality as evidence.
