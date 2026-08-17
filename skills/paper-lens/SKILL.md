---
name: paper-lens
description: Read and critically analyze one academic paper from an arXiv URL/ID or a local PDF, producing a source-grounded Markdown report that can grow from a quick read into a reviewer-level deep review. Use when the user asks to quick-read, summarize, explain, deeply review, critique, inspect formulas or experiments, assess reproducibility, or continue a prior Paper Lens report. Do not use for multi-paper surveys, literature-wide knowledge bases, OCR of scanned PDFs, or unsupported free-form claims without a paper source.
---

# Paper Lens

Create one durable `report.md` for one paper. Default to quick mode. Upgrade that same report when the user asks for a deep read; never create a parallel deep report.

## Resolve the request

1. Set the mode to `deep` only when the user explicitly asks for deep reading, reviewer-level analysis, comprehensive critique, formula derivation, experiment audit, or says to continue/deepen the current report. Otherwise use `quick`.
2. Set the report language to the user's language. Keep paper titles, method names, variable names, and established technical terms in their original form where useful.
3. Accept only an arXiv URL/ID or an existing local `.pdf` path.
4. For “continue/deepen this paper,” reuse the unambiguous Paper Lens workspace referenced in the current task. If no paper or workspace can be identified safely, ask for the input or report path.
5. Treat follow-up questions as conversation-only. Modify `report.md` only when the user explicitly asks to write, add, revise, or save the answer into the report.

## Load the applicable contracts

- Always read [report-contract.md](references/report-contract.md).
- For quick mode, read [quick-template.md](references/quick-template.md).
- For deep mode, read [quick-template.md](references/quick-template.md), [deep-template.md](references/deep-template.md), and [evidence-policy.md](references/evidence-policy.md).
- For a later follow-up that does not modify the report, answer from the report, metadata, and cached paper text without rerunning preparation unless required evidence is missing.

## Prepare deterministic artifacts

Resolve `SKILL_ROOT` as the directory containing this `SKILL.md`. Run:

```bash
python3 "$SKILL_ROOT/scripts/paper_pipeline.py" prepare \
  --input "<arXiv URL, arXiv ID, or absolute PDF path>" \
  --mode <quick|deep> \
  --output-root "$PWD/paper-reports" \
  --language <zh|en|auto>
```

If Python reports missing `fitz`, `requests`, or `bs4`, run `bash "$SKILL_ROOT/scripts/bootstrap.sh"`, then repeat the command with the Python executable printed by the bootstrap script. Do not install packages into the project environment.

The command prints JSON containing the workspace and artifact paths. Read at least:

- `metadata.json`
- `cache/pages.json`
- `cache/paper.txt`
- `report.md`

In deep mode also inspect `cache/source.tex` and `cache/figures.json` when present. Use `assets/` only for clean figures extracted from the original PDF or arXiv source. Do not use paper webpage screenshots as final figures.

## Write the report

1. Fill the existing `report.md`; do not replace its Paper Lens marker comments.
2. Ground quick mode only in the paper. Cite page, section, equation, figure, or table locations for substantive claims.
3. Preserve the completed quick section during a deep upgrade.
4. In deep mode, search the web for related evidence only after understanding the paper. Prefer primary research papers, official proceedings, publisher pages, and arXiv records.
5. Add `<!-- paper-lens:external-evidence:complete -->` when external claims were verified. If search is unavailable or insufficient, add `<!-- paper-lens:external-evidence:partial -->`, identify the unverified scope, and continue with source-only analysis.
6. Insert extracted figures and transcribed key tables next to the analysis they support. Explain every inserted item. Do not claim a figure/table was inspected unless it was.
7. Use `$...$` for inline mathematics and `$$ ... $$` for display mathematics. Put equation numbers in prose, not `\tag{}`.
8. Never invent authors, institutions, experimental values, citations, code availability, or conclusions. State “not reported,” “not verified,” or the equivalent in the selected language when evidence is absent.

## Validate and finish

Run:

```bash
python3 "$SKILL_ROOT/scripts/paper_pipeline.py" validate \
  --workspace "<workspace path from prepare>" \
  --mode <quick|deep>
```

Fix every validation error and rerun. A successful deep validation may still record `partial` when the external-evidence marker says verification was incomplete.

Return a concise outcome, the report's absolute path as a clickable link, the mode/status, and any material warnings. Do not expose cache files as separate deliverables unless the user requests them.
