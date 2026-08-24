# Contributing to Paper Lens

Paper Lens welcomes bug reports, paper-format edge cases, report-quality examples, documentation fixes, and focused pull requests. English and Chinese contributions are both welcome.

## Before opening an issue

- Remove or replace confidential PDFs, unpublished manuscripts, API keys, and personal data.
- Do not attach copyrighted paper PDFs unless you have the right to redistribute them. Prefer a public arXiv ID or a minimal synthetic fixture.
- For incorrect analysis, include the claim, its expected source location, the mode, and a redacted validation result.
- Search existing issues first.

Use the supplied issue forms for bugs and quality reports. Security vulnerabilities belong in the private process described in [SECURITY.md](SECURITY.md).

## Local development

Paper Lens supports Python 3.10 and later. Bootstrap its isolated environment:

```bash
bash skills/paper-lens/scripts/bootstrap.sh
```

Run the test and static checks with the Python path printed by that command:

```bash
~/.cache/paper-lens/venv/bin/python -m unittest discover -s tests -v
~/.cache/paper-lens/venv/bin/python -m compileall -q skills evals tests
bash -n skills/paper-lens/scripts/bootstrap.sh
```

Validate the Codex skill and plugin when the matching development tools are installed:

```bash
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/paper-lens
python3 ~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py .
```

## Pull requests

Keep changes narrow and explain the user-visible failure or capability. Add deterministic tests for pipeline changes. For changes to report behavior, include a public or synthetic example and describe the source anchors you checked. Do not commit generated `paper-reports/`, evaluator runs, downloaded PDFs, arXiv source archives, caches, or secrets.

Pull requests must keep the following aligned:

- `.codex-plugin/plugin.json` version and pipeline version;
- `SKILL.md`, report templates, and validator expectations;
- README claims and actual behavior;
- security limits and their tests.

Model-assisted code review may be run manually by a maintainer. It is advisory; a human maintainer owns every merge decision.

## Optional model evaluations

The deterministic suite never needs an API key. The optional end-to-end suite uses the locally installed `codex` command and requires a model name plus `CODEX_API_KEY` in the process environment:

```bash
CODEX_API_KEY=... python3 evals/run_evals.py --model '<model-id>'
```

Use `--offline` for case/schema checks and local negative fixtures. Evaluator outputs go to `evals/runs/` and are ignored by Git. Publish only aggregate results after manual inspection; never publish prompts or artifacts containing private paper content.

## Contributor conduct

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). By contributing, you agree that intentionally submitted contributions are provided under Apache-2.0, consistent with section 5 of the license.
