# Report and workspace contract

Use this contract for every Paper Lens run.

## Workspace

Write under `<output-root>/<paper-key>_<title-slug>/`:

```text
report.md
metadata.json
raw/
assets/
cache/
logs/
```

Use the base arXiv ID as `paper-key`. For local PDFs, use the first 12 hexadecimal characters of the PDF SHA-256. Reuse an existing workspace with the same key.

Do not edit or delete the source PDF. Keep copied/downloaded inputs in `raw/`, extracted page text and manifests in `cache/`, and report-ready figures in `assets/`.

## Report invariants

- Maintain exactly one `report.md`.
- Preserve these machine markers:
  - `paper-lens:quick:start` and `paper-lens:quick:end`
  - `paper-lens:deep:start` and `paper-lens:deep:end` in deep mode
  - each deep subsection marker created by the pipeline
- Remove all `{{...}}` placeholders before validation.
- Keep the quick section unchanged during a deep upgrade except for explicit corrections.
- Use relative paths such as `assets/figure-01.png` for embedded figures.
- Use Markdown links for external literature and enough bibliographic information to identify each work.

## Metadata states

Treat `metadata.json` as machine-owned except for pipeline commands. The lifecycle is:

```text
prepared -> quick_complete -> deep_prepared -> deep_complete
                                      \-> partial
```

The validator records `partial` only for deep reports explicitly marked as having incomplete external evidence. A validation failure leaves the report incomplete and records errors in `logs/validation.json`.

## Privacy

Never upload a local PDF to arXiv, translation sites, document converters, OCR services, or other third parties. Deep-mode literature search may reveal the paper title or search terms to the search provider; do not send the PDF itself.
