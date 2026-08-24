# Security Policy

## Supported versions

Security fixes are applied to the latest release and the `main` branch. Older releases may not receive patches.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for `YSQ-boop/paper-lens` when it is available. If private reporting is not enabled, contact the maintainer through the repository profile without publishing exploit details. Expect an acknowledgement within 72 hours and an initial severity assessment within 7 days.

Do not include private papers, access tokens, API keys, or personal data in a report. A minimal synthetic PDF or archive is preferred.

## Security boundary

Paper Lens processes untrusted PDFs and arXiv source archives locally. The pipeline limits network response size, archive member count, individual member size, and total selected expansion. It rejects path traversal and normalizes extracted report images to PNG. These controls reduce risk but do not make arbitrary documents trusted.

The project:

- does not execute TeX or files from source archives;
- does not run code contained in a paper repository;
- does not bypass encryption, paywalls, or access controls;
- does not provide OCR;
- does not upload local PDF binaries to a Paper Lens service or include telemetry (Codex model processing is described separately in `PRIVACY.md`);
- cannot guarantee that third-party PDF/parser libraries have no vulnerabilities.

Run Paper Lens with least privilege on sensitive inputs. Keep dependencies current and avoid opening unexpected generated assets outside a sandbox.
