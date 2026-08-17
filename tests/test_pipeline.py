from __future__ import annotations

import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pymupdf as fitz


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills"
    / "paper-lens"
    / "scripts"
    / "paper_pipeline.py"
)
SPEC = importlib.util.spec_from_file_location("paper_pipeline", SCRIPT)
pipeline = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pipeline)


def make_text_pdf(path: Path, *, title: str = "A Test Paper", pages: int = 3) -> None:
    document = fitz.open()
    for index in range(pages):
        page = document.new_page()
        text = (
            f"Page {index + 1}. Section {index + 1}. Test method and experimental evidence. "
            "This sentence supplies enough extractable academic text for the Paper Lens pipeline. "
        ) * 12
        page.insert_textbox(fitz.Rect(50, 50, 545, 790), text, fontsize=10)
    document.set_metadata({"title": title, "author": "Ada Author; Ben Researcher"})
    document.save(path)
    document.close()


def make_encrypted_pdf(path: Path) -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Confidential paper text")
    document.save(
        path,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner",
        user_pw="secret",
    )
    document.close()


def make_source_tar() -> bytes:
    payload = io.BytesIO()
    tex = rb"\section{Method}\begin{figure}\includegraphics{figure.png}\caption{Method overview}\label{fig:method}\end{figure}"
    # A valid 1x1 PNG; source figures are preserved without PDF raster-size filtering.
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    with tarfile.open(fileobj=payload, mode="w:gz") as archive:
        for name, data in (("main.tex", tex), ("figure.png", png)):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return payload.getvalue()


def complete_quick_report(report: str) -> str:
    anchored = (
        "The paper defines the task in Section 1 and formalizes the method in Section 2. "
        "The main empirical comparison appears in Table 1 on p. 3, with the mechanism illustrated "
        "in Figure 1. The evidence is treated as a paper claim rather than an independently verified fact. "
    )
    replacements = {
        "{{ONE_SENTENCE_VERDICT}}": anchored * 2,
        "{{PROBLEM_AND_MOTIVATION}}": anchored * 2,
        "{{CORE_CONTRIBUTIONS}}": anchored * 2,
        "{{METHOD_AT_A_GLANCE}}": anchored * 2,
        "{{CLAIMS_AND_EVIDENCE}}": anchored * 2,
        "{{LIMITATIONS_AND_CONFIDENCE}}": anchored * 2,
        "{{RECOMMENDED_FOLLOW_UPS}}": anchored * 2,
        "{{AUTHORS}}": "Not reported in PDF metadata",
        "{{VENUE_OR_STATUS}}": "Not verified",
    }
    for token, value in replacements.items():
        report = report.replace(token, value)
    return report


def complete_deep_report(report: str, *, partial: bool = True, include_image: bool = False) -> str:
    paragraph = (
        "Claim C1 is stated in Section 2 and supported by Equation (1), while Table 1 on p. 3 provides "
        "the primary empirical comparison. Figure 1 shows the proposed data flow. The ablation in Table 2 "
        "does not isolate every confounder, so the causal interpretation remains weaker than the predictive result. "
        "A reproduction should preserve preprocessing, random seeds, and evaluation settings reported in Section 3. "
    )
    evidence_marker = pipeline.EXTERNAL_PARTIAL if partial else pipeline.EXTERNAL_COMPLETE
    literature = paragraph * 3
    if not partial:
        literature += (
            " [Primary work one](https://arxiv.org/abs/2101.00001)"
            " [Primary work two](https://proceedings.mlr.press/v1/example.html)"
        )
    replacements = {
        "{{CLAIMS_EVIDENCE_MATRIX}}": paragraph * 3,
        "{{THEORY_AND_FORMULAS}}": paragraph * 3 + " $$ y = Wx + b $$ ",
        "{{EXPERIMENT_AUDIT}}": paragraph * 3,
        "{{EXTERNAL_EVIDENCE_STATUS}}": evidence_marker,
        "{{RELATED_LITERATURE}}": literature,
        "{{REVIEWER_CRITIQUE}}": paragraph * 3,
        "{{REPRODUCIBILITY}}": paragraph * 3,
        "{{FINAL_VERDICT}}": paragraph * 3,
    }
    for token, value in replacements.items():
        report = report.replace(token, value)
    if include_image:
        report = report.replace(
            pipeline.DEEP_SECTION_MARKERS[2],
            pipeline.DEEP_SECTION_MARKERS[2] + "\n\n![Method figure](assets/source-figure.png)",
        )
    return report


class ParsingTests(unittest.TestCase):
    def test_modern_and_legacy_arxiv_ids(self) -> None:
        self.assertEqual(pipeline.parse_arxiv_input("https://arxiv.org/abs/2401.12345v2"), ("2401.12345", "v2"))
        self.assertEqual(pipeline.parse_arxiv_input("arXiv:cs/9901001"), ("cs/9901001", None))
        self.assertIsNone(pipeline.parse_arxiv_input("https://example.com/2401.12345"))

    def test_slugify_is_stable_and_safe(self) -> None:
        self.assertEqual(pipeline.slugify(" A/B: Paper — Test "), "a-b-paper-test")
        self.assertEqual(pipeline.slugify("论文"), "paper")

    def test_latest_arxiv_version_and_metadata(self) -> None:
        html = """
        <meta name="citation_title" content="Versioned Paper">
        <meta name="citation_author" content="A. Author">
        <a href="/abs/2401.12345v1">v1</a><a href="/abs/2401.12345v3">v3</a>
        """
        metadata = pipeline.parse_arxiv_metadata(html, "2401.12345", None)
        self.assertEqual(metadata["paper_id"], "2401.12345v3")
        self.assertEqual(metadata["title"], "Versioned Paper")


class LocalPipelineTests(unittest.TestCase):
    def test_local_quick_is_private_idempotent_and_upgrades_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "paper.pdf"
            make_text_pdf(pdf)
            output = root / "reports"
            with mock.patch.object(pipeline, "http_get", side_effect=AssertionError("local PDF used network")):
                workspace, metadata = pipeline.prepare_paper(pdf.as_posix(), "quick", output, "en")
            self.assertEqual(metadata["paper_key"], pipeline.sha256_file(pdf)[:12])
            self.assertEqual(metadata["status"], "prepared")
            self.assertTrue((workspace / "raw" / "paper.pdf").is_file())

            report_path = workspace / "report.md"
            quick_report = complete_quick_report(report_path.read_text(encoding="utf-8"))
            report_path.write_text(quick_report, encoding="utf-8")
            quick_validation = pipeline.validate_workspace(workspace, "quick")
            self.assertTrue(quick_validation["ok"], quick_validation)
            self.assertEqual(json.loads((workspace / "metadata.json").read_text())["status"], "quick_complete")

            same_workspace, _ = pipeline.prepare_paper(pdf.as_posix(), "quick", output, "en")
            self.assertEqual(workspace, same_workspace)
            self.assertEqual(report_path.read_text(encoding="utf-8"), quick_report)

            deep_workspace, deep_metadata = pipeline.prepare_paper(pdf.as_posix(), "deep", output, "en")
            self.assertEqual(workspace, deep_workspace)
            self.assertEqual(deep_metadata["status"], "deep_prepared")
            upgraded = report_path.read_text(encoding="utf-8")
            self.assertIn(quick_report.rstrip(), upgraded)
            report_path.write_text(complete_deep_report(upgraded), encoding="utf-8")
            deep_validation = pipeline.validate_workspace(workspace, "deep")
            self.assertTrue(deep_validation["ok"], deep_validation)
            final_metadata = json.loads((workspace / "metadata.json").read_text())
            self.assertEqual(final_metadata["status"], "partial")
            self.assertEqual(final_metadata["preparation"]["external_evidence_status"], "partial")

    def test_missing_scanned_and_encrypted_pdf_fail_actionably(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(pipeline.PipelineError, "does not exist"):
                pipeline.prepare_paper((root / "missing.pdf").as_posix(), output_root=root / "out")

            scanned = root / "scanned.pdf"
            document = fitz.open()
            document.new_page()
            document.save(scanned)
            document.close()
            with self.assertRaisesRegex(pipeline.PipelineError, "OCR"):
                pipeline.prepare_paper(scanned.as_posix(), output_root=root / "out")

            encrypted = root / "encrypted.pdf"
            make_encrypted_pdf(encrypted)
            with self.assertRaisesRegex(pipeline.PipelineError, "encrypted"):
                pipeline.prepare_paper(encrypted.as_posix(), output_root=root / "out")


class ArxivPipelineTests(unittest.TestCase):
    def test_mocked_arxiv_deep_preparation_uses_latest_version_and_source_figures(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf_path = root / "download.pdf"
            make_text_pdf(pdf_path, title="PDF Metadata Title")
            pdf_bytes = pdf_path.read_bytes()
            source_bytes = make_source_tar()
            html = """
            <html><head>
            <meta name="citation_title" content="Mock Arxiv Paper">
            <meta name="citation_author" content="First Author">
            </head><body>
            <a href="/abs/2401.12345v1">v1</a>
            <a href="/abs/2401.12345v2">v2</a>
            </body></html>
            """

            def fake_get(url: str, *, binary: bool = False, timeout: int = 45):
                del timeout
                if "/abs/" in url:
                    return html
                if "/pdf/" in url and binary:
                    return pdf_bytes
                if "/src/" in url and binary:
                    return source_bytes
                raise AssertionError(url)

            with mock.patch.object(pipeline, "http_get", side_effect=fake_get):
                workspace, metadata = pipeline.prepare_paper(
                    "2401.12345", "deep", root / "reports", "en"
                )
            self.assertEqual(metadata["arxiv"]["paper_id"], "2401.12345v2")
            self.assertEqual(metadata["paper_key"], "2401.12345")
            manifest = json.loads((workspace / "cache" / "figures.json").read_text())
            source_figures = [item for item in manifest["figures"] if item["origin"] == "arxiv_source"]
            self.assertTrue(source_figures)
            self.assertEqual(source_figures[0]["caption"], "Method overview")
            self.assertTrue((workspace / source_figures[0]["path"]).is_file())

    def test_arxiv_network_failure_is_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(pipeline, "http_get", side_effect=pipeline.PipelineError("network down")):
                with self.assertRaisesRegex(pipeline.PipelineError, "network down"):
                    pipeline.prepare_paper("2401.12345", output_root=Path(directory))


class ValidationTests(unittest.TestCase):
    def test_complete_external_evidence_requires_primary_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "paper.pdf"
            make_text_pdf(pdf)
            workspace, _ = pipeline.prepare_paper(pdf.as_posix(), "deep", root / "reports", "en")
            report_path = workspace / "report.md"
            report = complete_quick_report(report_path.read_text(encoding="utf-8"))
            report = complete_deep_report(report, partial=False)
            report_path.write_text(report, encoding="utf-8")
            result = pipeline.validate_workspace(workspace, "deep")
            self.assertTrue(result["ok"], result)
            self.assertEqual(len(result["external_links"]), 2)
            repeated = pipeline.validate_workspace(workspace, "deep")
            self.assertTrue(repeated["ok"], repeated)
            _, prepared_again = pipeline.prepare_paper(pdf.as_posix(), "deep", root / "reports", "en")
            external_sources = [
                source for source in prepared_again["sources"] if source.get("kind") == "external"
            ]
            self.assertEqual(len(external_sources), 2)

    def test_placeholders_and_remote_images_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pdf = root / "paper.pdf"
            make_text_pdf(pdf)
            workspace, _ = pipeline.prepare_paper(pdf.as_posix(), "quick", root / "reports", "en")
            report_path = workspace / "report.md"
            report = report_path.read_text(encoding="utf-8") + "\n![remote](https://example.com/image.png)\n"
            report_path.write_text(report, encoding="utf-8")
            result = pipeline.validate_workspace(workspace, "quick")
            self.assertFalse(result["ok"])
            self.assertTrue(any("placeholders" in error for error in result["errors"]))
            self.assertTrue(any("remote URLs" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
