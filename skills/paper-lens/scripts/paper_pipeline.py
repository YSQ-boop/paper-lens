#!/usr/bin/env python3
"""Prepare and validate source-grounded Paper Lens workspaces."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tarfile
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

try:
    import pymupdf as fitz  # type: ignore
except ImportError:  # pragma: no cover - compatibility with older PyMuPDF packages
    try:
        import fitz  # type: ignore
    except ImportError:  # pragma: no cover - exercised through dependency error paths
        fitz = None

try:
    import requests  # type: ignore
except ImportError:  # pragma: no cover
    requests = None

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:  # pragma: no cover
    BeautifulSoup = None


SCHEMA_VERSION = 1
USER_AGENT = "paper-lens/0.1.0"
MODERN_ARXIV_RE = re.compile(r"(?<!\d)(?P<base>\d{4}\.\d{4,5})(?P<version>v\d+)?", re.I)
LEGACY_ARXIV_RE = re.compile(
    r"(?P<base>[a-z][a-z0-9.-]+(?:/[0-9]{7}))(?P<version>v\d+)?",
    re.I,
)
INVALID_PATH_RE = re.compile(r"[^A-Za-z0-9._-]+")
PLACEHOLDER_RE = re.compile(r"\{\{[^{}]+\}\}|\[TODO(?::[^\]]*)?\]", re.I)
ANCHOR_RE = re.compile(
    r"(?:\bp\.\s*\d+|\bpages?\s+\d+|第\s*\d+\s*页|"
    r"\bsections?\s+\d+(?:\.\d+)*|章节?\s*\d+(?:\.\d+)*|§\s*\d+|"
    r"\b(?:equation|eq\.)\s*\(?\d+\)?|式\s*\(?\d+\)?|"
    r"\bfig(?:ure|\.)?\s*\d+|图\s*\d+|"
    r"\btable\s*\d+|表\s*\d+)",
    re.I,
)
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\((https?://[^)\s]+)\)")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
QUICK_START = "<!-- paper-lens:quick:start -->"
QUICK_END = "<!-- paper-lens:quick:end -->"
DEEP_START = "<!-- paper-lens:deep:start -->"
DEEP_END = "<!-- paper-lens:deep:end -->"
DEEP_SECTION_MARKERS = (
    "<!-- paper-lens:deep:claims -->",
    "<!-- paper-lens:deep:formulas -->",
    "<!-- paper-lens:deep:experiments -->",
    "<!-- paper-lens:deep:literature -->",
    "<!-- paper-lens:deep:critique -->",
    "<!-- paper-lens:deep:reproducibility -->",
    "<!-- paper-lens:deep:verdict -->",
)
EXTERNAL_COMPLETE = "<!-- paper-lens:external-evidence:complete -->"
EXTERNAL_PARTIAL = "<!-- paper-lens:external-evidence:partial -->"
SOURCE_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".pdf"}


class PipelineError(RuntimeError):
    """An actionable preparation or validation failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"Cannot read valid JSON from {path}: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slugify(value: str, fallback: str = "paper", max_length: int = 100) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = INVALID_PATH_RE.sub("-", ascii_value.lower()).strip("-._")
    slug = re.sub(r"-{2,}", "-", slug)[:max_length].rstrip("-._")
    return slug or fallback


def parse_arxiv_input(value: str) -> tuple[str, str | None] | None:
    candidate = value.strip().removeprefix("arXiv:").removeprefix("arxiv:")
    parsed = urlparse(candidate)
    if parsed.scheme and parsed.netloc and "arxiv.org" not in parsed.netloc.lower():
        return None
    for pattern in (MODERN_ARXIV_RE, LEGACY_ARXIV_RE):
        match = pattern.search(candidate)
        if match:
            base = match.group("base")
            version = match.group("version")
            return base, version.lower() if version else None
    return None


def require_pdf_support() -> None:
    if fitz is None:
        raise PipelineError(
            "PyMuPDF is required. Run scripts/bootstrap.sh and retry with the printed Python executable."
        )


def require_network_support() -> None:
    if requests is None:
        raise PipelineError(
            "Requests is required for arXiv input. Run scripts/bootstrap.sh and retry with the printed Python executable."
        )


def http_get(url: str, *, binary: bool = False, timeout: int = 45) -> bytes | str:
    require_network_support()
    try:
        response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
    except Exception as exc:
        raise PipelineError(f"Could not fetch {url}: {exc}") from exc
    return response.content if binary else response.text


def parse_arxiv_metadata(html: str, base_id: str, requested_version: str | None) -> dict[str, Any]:
    versions = [int(value) for value in re.findall(rf"{re.escape(base_id)}v(\d+)", html, re.I)]
    version = requested_version or (f"v{max(versions)}" if versions else None)
    title = ""
    authors: list[str] = []
    published = ""
    venue = ""
    abstract = ""

    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        title_meta = soup.find("meta", attrs={"name": "citation_title"})
        if title_meta:
            title = str(title_meta.get("content", "")).strip()
        authors = [
            str(node.get("content", "")).strip()
            for node in soup.find_all("meta", attrs={"name": "citation_author"})
            if str(node.get("content", "")).strip()
        ]
        date_meta = soup.find("meta", attrs={"name": "citation_date"})
        if date_meta:
            published = str(date_meta.get("content", "")).strip()
        for name in ("citation_conference_title", "citation_journal_title"):
            venue_meta = soup.find("meta", attrs={"name": name})
            if venue_meta and venue_meta.get("content"):
                venue = str(venue_meta.get("content")).strip()
                break
        abstract_block = soup.find("blockquote", class_=re.compile(r"abstract", re.I))
        if abstract_block:
            abstract = abstract_block.get_text(" ", strip=True)
            abstract = re.sub(r"^Abstract:\s*", "", abstract, flags=re.I)

    if not title:
        match = re.search(
            r'<meta[^>]+name=["\']citation_title["\'][^>]+content=["\'](.*?)["\']',
            html,
            re.I | re.S,
        )
        if match:
            title = re.sub(r"\s+", " ", match.group(1)).strip()

    paper_id = f"{base_id}{version or ''}"
    return {
        "base_id": base_id,
        "version": version or "",
        "paper_id": paper_id,
        "title": title or base_id,
        "authors": authors,
        "published": published,
        "venue": venue,
        "abstract": abstract,
        "abs_url": f"https://arxiv.org/abs/{paper_id}",
        "pdf_url": f"https://arxiv.org/pdf/{paper_id}.pdf",
        "source_url": f"https://arxiv.org/src/{paper_id}",
    }


def inspect_pdf(path: Path) -> dict[str, Any]:
    require_pdf_support()
    try:
        document = fitz.open(path)
    except Exception as exc:
        raise PipelineError(f"The PDF is damaged or unreadable: {path} ({exc})") from exc
    try:
        if document.needs_pass:
            raise PipelineError(f"The PDF is encrypted. Remove the password before using Paper Lens: {path}")
        if document.page_count <= 0:
            raise PipelineError(f"The PDF has no pages: {path}")
        pages = []
        text_characters = 0
        for index, page in enumerate(document):
            text = page.get_text("text").strip()
            text_characters += len(re.sub(r"\s+", "", text))
            pages.append({"page": index + 1, "text": text})
        threshold = max(200, document.page_count * 40)
        if text_characters < threshold:
            raise PipelineError(
                "The PDF appears scanned or image-only and has too little extractable text. "
                "Paper Lens v0.1 does not provide OCR; run OCR locally and retry."
            )
        metadata = document.metadata or {}
        return {
            "page_count": document.page_count,
            "text_characters": text_characters,
            "pages": pages,
            "title": str(metadata.get("title") or "").strip(),
            "authors": [
                part.strip()
                for part in re.split(r"[;,]", str(metadata.get("author") or ""))
                if part.strip()
            ],
        }
    finally:
        document.close()


def find_workspace(output_root: Path, paper_key: str, title: str) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    for candidate in sorted(path for path in output_root.iterdir() if path.is_dir()):
        try:
            metadata = load_json(candidate / "metadata.json", {})
        except PipelineError:
            continue
        if isinstance(metadata, dict) and metadata.get("paper_key") == paper_key:
            return candidate
    return output_root / f"{paper_key}_{slugify(title)}"


def ensure_workspace(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    for name in ("raw", "assets", "cache", "logs"):
        (workspace / name).mkdir(exist_ok=True)


def write_pdf_cache(workspace: Path, inspection: dict[str, Any]) -> None:
    pages = inspection["pages"]
    write_json(
        workspace / "cache" / "pages.json",
        {
            "page_numbering": "PDF pages, 1-based",
            "page_count": inspection["page_count"],
            "pages": pages,
        },
    )
    text = "\n\n".join(f"===== PDF page {page['page']} =====\n{page['text']}" for page in pages)
    write_text(workspace / "cache" / "paper.txt", text + "\n")


def safe_download(url: str, destination: Path) -> None:
    payload = http_get(url, binary=True)
    if not isinstance(payload, bytes) or not payload:
        raise PipelineError(f"Downloaded an empty response from {url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=destination.parent, delete=False) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)
    temp_path.replace(destination)


def extract_pdf_images(pdf_path: Path, assets_dir: Path) -> list[dict[str, Any]]:
    require_pdf_support()
    document = fitz.open(pdf_path)
    results: list[dict[str, Any]] = []
    seen: set[int] = set()
    try:
        for page_index, page in enumerate(document):
            for image_index, image in enumerate(page.get_images(full=True), start=1):
                xref = int(image[0])
                if xref in seen:
                    continue
                seen.add(xref)
                try:
                    pixmap = fitz.Pixmap(document, xref)
                    if pixmap.width < 200 or pixmap.height < 150 or pixmap.width * pixmap.height < 60000:
                        continue
                    if pixmap.colorspace is None:
                        continue
                    if pixmap.n - pixmap.alpha > 3:
                        pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
                    name = f"pdf-p{page_index + 1:03d}-img{image_index:02d}.png"
                    output = assets_dir / name
                    pixmap.save(output)
                    results.append(
                        {
                            "origin": "pdf",
                            "page": page_index + 1,
                            "xref": xref,
                            "path": f"assets/{name}",
                            "width": pixmap.width,
                            "height": pixmap.height,
                        }
                    )
                except Exception:
                    continue
    finally:
        document.close()
    return results


def safe_archive_name(name: str) -> str | None:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        return None
    return path.as_posix()


def convert_source_asset(data: bytes, archive_name: str, assets_dir: Path) -> str | None:
    suffix = Path(archive_name).suffix.lower()
    digest = hashlib.sha256(archive_name.encode("utf-8")).hexdigest()[:8]
    stem = slugify(Path(archive_name).stem, fallback="figure", max_length=55)
    if suffix == ".pdf":
        require_pdf_support()
        try:
            document = fitz.open(stream=data, filetype="pdf")
            if document.page_count == 0:
                return None
            pixmap = document[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            output = assets_dir / f"source-{stem}-{digest}.png"
            pixmap.save(output)
            document.close()
            return f"assets/{output.name}"
        except Exception:
            return None
    output = assets_dir / f"source-{stem}-{digest}{suffix}"
    output.write_bytes(data)
    return f"assets/{output.name}"


def parse_figure_context(source_text: str, source_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    figures: list[dict[str, Any]] = []
    asset_by_name = {Path(item["archive_path"]).name: item["path"] for item in source_assets}
    pattern = re.compile(r"\\begin\{figure\*?\}(.*?)\\end\{figure\*?\}", re.S | re.I)
    for match in pattern.finditer(source_text):
        block = match.group(1)
        include = re.search(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", block)
        caption = re.search(r"\\caption\{(.*?)\}", block, re.S)
        label = re.search(r"\\label\{([^}]+)\}", block)
        section_matches = list(
            re.finditer(r"\\(?:section|subsection|subsubsection)\*?\{([^}]+)\}", source_text[: match.start()])
        )
        include_value = include.group(1).strip() if include else ""
        include_name = Path(include_value).name
        asset_path = asset_by_name.get(include_name)
        if asset_path is None and not Path(include_name).suffix:
            for name, path in asset_by_name.items():
                if Path(name).stem == include_name:
                    asset_path = path
                    break
        figures.append(
            {
                "origin": "arxiv_source",
                "includegraphics": include_value,
                "path": asset_path or "",
                "caption": re.sub(r"\s+", " ", caption.group(1)).strip() if caption else "",
                "label": label.group(1).strip() if label else "",
                "section": section_matches[-1].group(1).strip() if section_matches else "",
            }
        )
    return figures


def extract_source_bundle(source_tar: Path, workspace: Path) -> tuple[list[dict[str, Any]], str, list[str]]:
    source_assets: list[dict[str, Any]] = []
    tex_parts: list[str] = []
    warnings: list[str] = []
    try:
        archive = tarfile.open(source_tar, "r:*")
    except tarfile.TarError as exc:
        return [], "", [f"Could not open the arXiv source archive: {exc}"]
    with archive:
        for member in archive.getmembers():
            safe_name = safe_archive_name(member.name)
            if not safe_name or not member.isfile() or member.size > 50 * 1024 * 1024:
                continue
            suffix = Path(safe_name).suffix.lower()
            if suffix not in SOURCE_IMAGE_SUFFIXES and suffix != ".tex":
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            data = extracted.read()
            if suffix == ".tex":
                tex_parts.append(f"\n% BEGIN {safe_name}\n{data.decode('utf-8', errors='replace')}\n% END {safe_name}\n")
                continue
            path = convert_source_asset(data, safe_name, workspace / "assets")
            if path:
                source_assets.append({"origin": "arxiv_source", "archive_path": safe_name, "path": path})
    source_text = "".join(tex_parts)
    write_text(workspace / "cache" / "source.tex", source_text)
    if not tex_parts:
        warnings.append("The arXiv source archive contained no readable TeX files.")
    return source_assets, source_text, warnings


def quick_report_template(metadata: dict[str, Any]) -> str:
    language = metadata.get("language")
    source = metadata["sources"][0]
    if source["kind"] == "arxiv":
        source_text = f"[arXiv {source['paper_id']}]({source['url']})"
    else:
        source_text = "[Local PDF](raw/paper.pdf)"
    authors = ", ".join(metadata.get("authors") or []) or "{{AUTHORS}}"
    venue = metadata.get("venue") or "{{VENUE_OR_STATUS}}"
    if language == "zh":
        return f"""# Paper Lens 论文报告

{QUICK_START}
## 论文信息
- 标题：{metadata['title']}
- 作者：{authors}
- 来源 / 状态：{venue}
- 原文：{source_text}
- 定位规则：PDF 页码，从 1 开始

## 快读
### 一句话判断
{{{{ONE_SENTENCE_VERDICT}}}}

### 问题与动机
{{{{PROBLEM_AND_MOTIVATION}}}}

### 核心贡献
{{{{CORE_CONTRIBUTIONS}}}}

### 方法概览
{{{{METHOD_AT_A_GLANCE}}}}

### 主张与证据
{{{{CLAIMS_AND_EVIDENCE}}}}

### 局限与置信度
{{{{LIMITATIONS_AND_CONFIDENCE}}}}

### 建议继续追问
{{{{RECOMMENDED_FOLLOW_UPS}}}}
{QUICK_END}
"""
    return f"""# Paper Lens Report

{QUICK_START}
## Paper information
- Title: {metadata['title']}
- Authors: {authors}
- Venue / status: {venue}
- Source: {source_text}
- Location convention: PDF pages, 1-based

## Quick read
### One-sentence verdict
{{{{ONE_SENTENCE_VERDICT}}}}

### Problem and motivation
{{{{PROBLEM_AND_MOTIVATION}}}}

### Core contributions
{{{{CORE_CONTRIBUTIONS}}}}

### Method at a glance
{{{{METHOD_AT_A_GLANCE}}}}

### Claims and evidence
{{{{CLAIMS_AND_EVIDENCE}}}}

### Limitations and confidence
{{{{LIMITATIONS_AND_CONFIDENCE}}}}

### Recommended follow-ups
{{{{RECOMMENDED_FOLLOW_UPS}}}}
{QUICK_END}
"""


def deep_report_template(language: str) -> str:
    if language == "zh":
        return f"""

{DEEP_START}
## 深读
{DEEP_SECTION_MARKERS[0]}
### 核心主张—证据矩阵
{{{{CLAIMS_EVIDENCE_MATRIX}}}}

{DEEP_SECTION_MARKERS[1]}
### 理论、假设与关键公式
{{{{THEORY_AND_FORMULAS}}}}

{DEEP_SECTION_MARKERS[2]}
### 实验充分性审查
{{{{EXPERIMENT_AUDIT}}}}

{DEEP_SECTION_MARKERS[3]}
### 相关工作与外部证据
{{{{EXTERNAL_EVIDENCE_STATUS}}}}
{{{{RELATED_LITERATURE}}}}

{DEEP_SECTION_MARKERS[4]}
### 审稿式质疑
{{{{REVIEWER_CRITIQUE}}}}

{DEEP_SECTION_MARKERS[5]}
### 可复现性
{{{{REPRODUCIBILITY}}}}

{DEEP_SECTION_MARKERS[6]}
### 最终评分与结论
{{{{FINAL_VERDICT}}}}
{DEEP_END}
"""
    return f"""

{DEEP_START}
## Deep review
{DEEP_SECTION_MARKERS[0]}
### Claims–Evidence matrix
{{{{CLAIMS_EVIDENCE_MATRIX}}}}

{DEEP_SECTION_MARKERS[1]}
### Theory, assumptions, and key formulas
{{{{THEORY_AND_FORMULAS}}}}

{DEEP_SECTION_MARKERS[2]}
### Experiment audit
{{{{EXPERIMENT_AUDIT}}}}

{DEEP_SECTION_MARKERS[3]}
### Related literature and external evidence
{{{{EXTERNAL_EVIDENCE_STATUS}}}}
{{{{RELATED_LITERATURE}}}}

{DEEP_SECTION_MARKERS[4]}
### Reviewer critique
{{{{REVIEWER_CRITIQUE}}}}

{DEEP_SECTION_MARKERS[5]}
### Reproducibility
{{{{REPRODUCIBILITY}}}}

{DEEP_SECTION_MARKERS[6]}
### Final scores and verdict
{{{{FINAL_VERDICT}}}}
{DEEP_END}
"""


def ensure_report(workspace: Path, metadata: dict[str, Any], mode: str) -> None:
    report_path = workspace / "report.md"
    if not report_path.exists():
        write_text(report_path, quick_report_template(metadata))
    report = report_path.read_text(encoding="utf-8")
    if report.count(QUICK_START) != 1 or report.count(QUICK_END) != 1:
        raise PipelineError(
            f"Existing report does not contain one intact Paper Lens quick section: {report_path}"
        )
    if mode == "deep" and DEEP_START not in report:
        write_text(report_path, report.rstrip() + deep_report_template(metadata["language"]) + "\n")
    elif mode == "deep" and (report.count(DEEP_START) != 1 or report.count(DEEP_END) != 1):
        raise PipelineError(
            f"Existing report does not contain one intact Paper Lens deep section: {report_path}"
        )


def relative_artifacts() -> dict[str, str]:
    return {
        "report": "report.md",
        "metadata": "metadata.json",
        "pdf": "raw/paper.pdf",
        "paper_text": "cache/paper.txt",
        "pages": "cache/pages.json",
        "figures": "cache/figures.json",
        "source_text": "cache/source.tex",
    }


def status_after_prepare(existing: dict[str, Any], mode: str, source_changed: bool) -> str:
    old = str(existing.get("status") or "")
    if source_changed:
        return "deep_prepared" if mode == "deep" else "prepared"
    if mode == "deep":
        return old if old in {"deep_complete", "partial"} else "deep_prepared"
    return old if old in {"quick_complete", "deep_complete", "partial"} else "prepared"


def preserved_external_sources(existing: dict[str, Any], source_changed: bool) -> list[dict[str, Any]]:
    if source_changed:
        return []
    return [
        source
        for source in existing.get("sources", [])
        if isinstance(source, dict) and source.get("kind") == "external" and source.get("url")
    ]


def prepare_local_pdf(
    input_value: str, mode: str, output_root: Path, language: str, refresh: bool
) -> tuple[Path, dict[str, Any]]:
    source_path = Path(input_value).expanduser().resolve()
    if not source_path.is_file():
        raise PipelineError(f"Local PDF does not exist: {source_path}")
    if source_path.suffix.lower() != ".pdf":
        raise PipelineError(f"Only local .pdf files are supported: {source_path}")
    source_hash = sha256_file(source_path)
    inspection = inspect_pdf(source_path)
    title = inspection["title"] or source_path.stem
    paper_key = source_hash[:12]
    workspace = find_workspace(output_root, paper_key, title)
    ensure_workspace(workspace)
    existing = load_json(workspace / "metadata.json", {})
    destination = workspace / "raw" / "paper.pdf"
    destination_hash = sha256_file(destination) if destination.exists() else ""
    source_changed = destination_hash != source_hash
    if source_changed or refresh:
        shutil.copy2(source_path, destination)
    write_pdf_cache(workspace, inspection)
    warnings: list[str] = []
    figures: list[dict[str, Any]] = []
    if mode == "deep":
        figures = extract_pdf_images(destination, workspace / "assets")
        if not figures:
            warnings.append("No clean embedded raster figures were extracted from the PDF.")
    write_json(workspace / "cache" / "figures.json", {"figures": figures})
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "paper_key": paper_key,
        "input": {"kind": "local_pdf", "original": str(source_path), "sha256": source_hash},
        "arxiv": None,
        "title": title,
        "authors": inspection["authors"],
        "venue": "",
        "published": "",
        "language": language,
        "requested_mode": mode,
        "current_mode": "deep" if mode == "deep" or existing.get("current_mode") == "deep" else "quick",
        "status": status_after_prepare(existing, mode, source_changed or refresh),
        "workspace": str(workspace.resolve()),
        "artifacts": relative_artifacts(),
        "sources": [
            {
                "kind": "local_pdf",
                "path": str(source_path),
                "copied_to": "raw/paper.pdf",
                "sha256": source_hash,
            },
            *preserved_external_sources(existing, source_changed or refresh),
        ],
        "preparation": {
            "page_count": inspection["page_count"],
            "text_characters": inspection["text_characters"],
            "figure_count": len(figures),
            "external_evidence_status": "pending" if mode == "deep" else "not_requested",
        },
        "warnings": warnings,
        "created_at": existing.get("created_at") or utc_now(),
        "updated_at": utc_now(),
    }
    write_json(workspace / "metadata.json", metadata)
    ensure_report(workspace, metadata, mode)
    write_json(workspace / "logs" / "prepare.json", {"ok": True, "at": utc_now(), "mode": mode})
    return workspace, metadata


def prepare_arxiv(
    input_value: str, mode: str, output_root: Path, language: str, refresh: bool
) -> tuple[Path, dict[str, Any]]:
    parsed = parse_arxiv_input(input_value)
    if parsed is None:
        raise PipelineError(f"Could not parse an arXiv ID from: {input_value}")
    base_id, requested_version = parsed
    initial_url = f"https://arxiv.org/abs/{base_id}{requested_version or ''}"
    html = http_get(initial_url)
    if not isinstance(html, str):
        raise PipelineError(f"Expected HTML metadata from {initial_url}")
    arxiv = parse_arxiv_metadata(html, base_id, requested_version)
    paper_key = base_id.replace("/", "_")
    workspace = find_workspace(output_root, paper_key, arxiv["title"])
    ensure_workspace(workspace)
    existing = load_json(workspace / "metadata.json", {})
    old_paper_id = ((existing.get("arxiv") or {}).get("paper_id") if isinstance(existing, dict) else None)
    source_changed = bool(old_paper_id and old_paper_id != arxiv["paper_id"])
    write_text(workspace / "raw" / "abs.html", html)
    pdf_path = workspace / "raw" / "paper.pdf"
    if refresh or source_changed or not pdf_path.exists():
        safe_download(arxiv["pdf_url"], pdf_path)
    inspection = inspect_pdf(pdf_path)
    source_hash = sha256_file(pdf_path)
    write_pdf_cache(workspace, inspection)
    warnings: list[str] = []
    if source_changed:
        warnings.append(
            f"The arXiv version changed from {old_paper_id} to {arxiv['paper_id']}; re-check all report claims."
        )
    figures: list[dict[str, Any]] = []
    if mode == "deep":
        source_tar = workspace / "raw" / "source.tar"
        if refresh or source_changed or not source_tar.exists():
            try:
                safe_download(arxiv["source_url"], source_tar)
            except PipelineError as exc:
                warnings.append(str(exc))
        source_assets: list[dict[str, Any]] = []
        source_text = ""
        if source_tar.exists():
            source_assets, source_text, source_warnings = extract_source_bundle(source_tar, workspace)
            warnings.extend(source_warnings)
        figures.extend(parse_figure_context(source_text, source_assets))
        figures.extend(extract_pdf_images(pdf_path, workspace / "assets"))
        if not any(item.get("path") for item in figures):
            warnings.append("No clean report-ready figures were extracted from the source or PDF.")
    write_json(workspace / "cache" / "figures.json", {"figures": figures})
    authors = arxiv["authors"] or inspection["authors"]
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "paper_key": paper_key,
        "input": {"kind": "arxiv", "original": input_value, "sha256": source_hash},
        "arxiv": arxiv,
        "title": arxiv["title"],
        "authors": authors,
        "venue": arxiv["venue"],
        "published": arxiv["published"],
        "language": language,
        "requested_mode": mode,
        "current_mode": "deep" if mode == "deep" or existing.get("current_mode") == "deep" else "quick",
        "status": status_after_prepare(existing, mode, source_changed or refresh),
        "workspace": str(workspace.resolve()),
        "artifacts": relative_artifacts(),
        "sources": [
            {
                "kind": "arxiv",
                "paper_id": arxiv["paper_id"],
                "url": arxiv["abs_url"],
                "sha256": source_hash,
            },
            *preserved_external_sources(existing, source_changed or refresh),
        ],
        "preparation": {
            "page_count": inspection["page_count"],
            "text_characters": inspection["text_characters"],
            "figure_count": sum(1 for item in figures if item.get("path")),
            "external_evidence_status": "pending" if mode == "deep" else "not_requested",
        },
        "warnings": warnings,
        "created_at": existing.get("created_at") or utc_now(),
        "updated_at": utc_now(),
    }
    write_json(workspace / "metadata.json", metadata)
    ensure_report(workspace, metadata, mode)
    write_json(workspace / "logs" / "prepare.json", {"ok": True, "at": utc_now(), "mode": mode})
    return workspace, metadata


def normalize_language(value: str) -> str:
    lowered = value.lower()
    if lowered in {"zh", "zh-cn", "chinese", "中文"}:
        return "zh"
    if lowered in {"en", "english", "英文"}:
        return "en"
    if lowered == "auto":
        return "auto"
    raise PipelineError(f"Unsupported language '{value}'. Use zh, en, or auto.")


def prepare_paper(
    input_value: str,
    mode: str = "quick",
    output_root: Path | str = "paper-reports",
    language: str = "auto",
    refresh: bool = False,
) -> tuple[Path, dict[str, Any]]:
    normalized_mode = mode.lower()
    if normalized_mode not in {"quick", "deep"}:
        raise PipelineError("Mode must be quick or deep.")
    normalized_language = normalize_language(language)
    root = Path(output_root).expanduser().resolve()
    local_candidate = Path(input_value).expanduser()
    if local_candidate.exists() or local_candidate.suffix.lower() == ".pdf":
        return prepare_local_pdf(input_value, normalized_mode, root, normalized_language, refresh)
    if parse_arxiv_input(input_value):
        return prepare_arxiv(input_value, normalized_mode, root, normalized_language, refresh)
    raise PipelineError("Paper Lens accepts only an arXiv URL/ID or an existing local .pdf path.")


def count_marker(report: str, marker: str, errors: list[str]) -> None:
    count = report.count(marker)
    if count != 1:
        errors.append(f"Expected exactly one marker {marker!r}; found {count}.")


def validate_images(workspace: Path, report: str, errors: list[str]) -> list[str]:
    paths: list[str] = []
    for raw in MARKDOWN_IMAGE_RE.findall(report):
        path_text = raw.strip().split()[0].strip("<>")
        if urlparse(path_text).scheme:
            errors.append(f"Report images must be local extracted assets, not remote URLs: {path_text}")
            continue
        candidate = (workspace / path_text).resolve()
        try:
            candidate.relative_to(workspace.resolve())
        except ValueError:
            errors.append(f"Report image escapes the workspace: {path_text}")
            continue
        if not candidate.is_file():
            errors.append(f"Report image does not exist: {path_text}")
        paths.append(path_text)
    return paths


def external_links(report: str, metadata: dict[str, Any]) -> list[str]:
    original_urls = {
        source.get("url")
        for source in metadata.get("sources", [])
        if isinstance(source, dict) and source.get("kind") != "external" and source.get("url")
    }
    return sorted({url for url in MARKDOWN_LINK_RE.findall(report) if url not in original_urls})


def validate_workspace(workspace: Path | str, mode: str) -> dict[str, Any]:
    workspace_path = Path(workspace).expanduser().resolve()
    metadata_path = workspace_path / "metadata.json"
    report_path = workspace_path / "report.md"
    metadata = load_json(metadata_path, {})
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(metadata, dict) or metadata.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"metadata.json must use schema_version {SCHEMA_VERSION}.")
    if not report_path.is_file():
        errors.append("Missing report.md.")
        report = ""
    else:
        report = report_path.read_text(encoding="utf-8")

    count_marker(report, QUICK_START, errors)
    count_marker(report, QUICK_END, errors)
    if PLACEHOLDER_RE.search(report):
        errors.append("Report still contains template placeholders or TODO markers.")
    if len(re.sub(r"\s+", "", report)) < 900:
        errors.append("Quick report is too short to satisfy the report contract.")
    anchor_count = len(ANCHOR_RE.findall(report))
    if anchor_count < 3:
        errors.append(f"Quick report needs at least 3 source-location anchors; found {anchor_count}.")
    if report.count("$$") % 2:
        errors.append("Display-math delimiters '$$' are unbalanced.")
    if "\\tag{" in report:
        errors.append("Put equation numbers in prose; do not use \\tag{} in report formulas.")
    if "\\[" in report or "\\]" in report:
        errors.append("Use $$ ... $$ rather than \\[ ... \\] for display mathematics.")
    image_paths = validate_images(workspace_path, report, errors)

    normalized_mode = mode.lower()
    if normalized_mode not in {"quick", "deep"}:
        errors.append("Validation mode must be quick or deep.")
    external_status = "not_requested"
    links = external_links(report, metadata if isinstance(metadata, dict) else {})
    if normalized_mode == "deep":
        count_marker(report, DEEP_START, errors)
        count_marker(report, DEEP_END, errors)
        for marker in DEEP_SECTION_MARKERS:
            count_marker(report, marker, errors)
        if len(re.sub(r"\s+", "", report)) < 2800:
            errors.append("Deep report is too short to satisfy the deep-review contract.")
        if anchor_count < 8:
            errors.append(f"Deep report needs at least 8 source-location anchors; found {anchor_count}.")
        complete_count = report.count(EXTERNAL_COMPLETE)
        partial_count = report.count(EXTERNAL_PARTIAL)
        if complete_count + partial_count != 1:
            errors.append("Deep report must contain exactly one complete or partial external-evidence marker.")
        elif complete_count:
            external_status = "complete"
            if len(links) < 2:
                errors.append("Complete external evidence requires at least 2 linked primary sources.")
        else:
            external_status = "partial"
            warnings.append("External literature verification is incomplete; the report will be marked partial.")
        figure_count = int((metadata.get("preparation") or {}).get("figure_count") or 0)
        if figure_count > 0 and not image_paths:
            errors.append("Extracted figures are available, but the deep report embeds none of them.")

    result = {
        "ok": not errors,
        "mode": normalized_mode,
        "workspace": str(workspace_path),
        "errors": errors,
        "warnings": warnings,
        "anchor_count": anchor_count,
        "image_count": len(image_paths),
        "external_links": links,
        "validated_at": utc_now(),
    }
    write_json(workspace_path / "logs" / "validation.json", result)
    if errors:
        return result

    sources = [
        source
        for source in metadata.get("sources", [])
        if isinstance(source, dict) and source.get("kind") != "external"
    ]
    sources.extend({"kind": "external", "url": url} for url in links)
    metadata["sources"] = sources
    metadata["requested_mode"] = normalized_mode
    metadata["current_mode"] = "deep" if normalized_mode == "deep" else metadata.get("current_mode", "quick")
    metadata["status"] = (
        "partial" if normalized_mode == "deep" and external_status == "partial" else f"{normalized_mode}_complete"
    )
    preparation = metadata.setdefault("preparation", {})
    preparation["external_evidence_status"] = external_status
    metadata["validated_at"] = result["validated_at"]
    metadata["updated_at"] = result["validated_at"]
    write_json(metadata_path, metadata)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare and validate Paper Lens workspaces.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="Prepare a paper workspace and report skeleton.")
    prepare.add_argument("--input", required=True, help="arXiv URL/ID or an existing local PDF path")
    prepare.add_argument("--mode", choices=("quick", "deep"), default="quick")
    prepare.add_argument("--output-root", default="paper-reports")
    prepare.add_argument("--language", default="auto")
    prepare.add_argument("--refresh", action="store_true")
    validate = subparsers.add_parser("validate", help="Validate and finalize a report.")
    validate.add_argument("--workspace", required=True)
    validate.add_argument("--mode", choices=("quick", "deep"), required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "prepare":
            workspace, metadata = prepare_paper(
                args.input,
                mode=args.mode,
                output_root=args.output_root,
                language=args.language,
                refresh=args.refresh,
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "workspace": str(workspace.resolve()),
                        "report": str((workspace / "report.md").resolve()),
                        "metadata": str((workspace / "metadata.json").resolve()),
                        "status": metadata["status"],
                        "warnings": metadata["warnings"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        result = validate_workspace(args.workspace, args.mode)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    except PipelineError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
