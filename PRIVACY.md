# Privacy

Paper Lens has no account system, hosted backend, analytics, tracking identifier, or telemetry endpoint.

## What stays local

The deterministic pipeline downloads public arXiv material or copies a user-selected PDF into `paper-reports/`. It extracts text, metadata, and report-ready PNG figures on the local machine. Paper Lens does not send the PDF binary to an OCR, translation, conversion, analytics, or Paper Lens-operated service.

Generated workspaces remain on disk until the user removes them. They can contain the original PDF, arXiv source, extracted text, figures, hashes, local paths, reports, and logs. They are ignored by this repository but are not encrypted by Paper Lens.

## Codex model processing

Paper Lens is a Codex skill. To analyze a paper, Codex reads relevant extracted paper text, metadata, prompts, and the evolving report. That content may be processed by OpenAI or another model provider according to the user's Codex configuration, account, organization settings, and applicable data controls. “Local PDF” therefore means the binary is handled by the local pipeline; it does not mean the paper's content is invisible to the configured model.

Users should confirm their data policy before analyzing confidential, unpublished, regulated, or personally identifiable material. Use a source-only deep review to avoid related-literature browsing, but note that this does not disable the model processing needed to write the report.

## Network requests

- arXiv input fetches the public abstract page and PDF; deep mode also attempts the public source archive.
- Quick mode does not search for related literature.
- Deep mode may search for primary literature unless the user requests source-only operation or network access is unavailable.
- External sites receive ordinary request metadata such as IP address and the Paper Lens user agent; no project telemetry identifier is added.

## Evaluations

The committed evaluator cases use public arXiv papers and generated fixtures. Online evaluator traces and reports are written under ignored `evals/runs/`. The runner passes `CODEX_API_KEY` only to Codex child processes and scrubs the literal key from captured output. Users must not add private papers to the committed case set or publish unreviewed traces.
