#!/usr/bin/env python3
"""Prepare and validate source-grounded Paper Lens workspaces."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import posixpath
import re
import shutil
import sys
import tarfile
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
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


PLUGIN_VERSION = "0.3.0"
SCHEMA_VERSION = 1
USER_AGENT = f"paper-lens/{PLUGIN_VERSION}"
HTTP_TIMEOUT = (10, 60)
MAX_HTML_BYTES = 5 * 1024 * 1024
MAX_PDF_BYTES = 100 * 1024 * 1024
MAX_SOURCE_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_ARCHIVE_MEMBER_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 2_000
MAX_SOURCE_EXPANDED_BYTES = 250 * 1024 * 1024
MAX_SOURCE_IMAGE_PIXELS = 40_000_000
DOWNLOAD_CHUNK_BYTES = 64 * 1024
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
FORMULA_DISCUSSION_RE = re.compile(
    r"\b(?:formula(?:e|s)?|equation(?:s)?|loss function|objective function|mathematical)\b|"
    r"公式|方程(?:式)?|损失函数|目标函数|数学表达式",
    re.I,
)
TABLE_DISCUSSION_RE = re.compile(
    r"\b(?:table|tab\.)\s*\d*\b|主结果表|结果表|消融表|数据规模表|表格|表\s*\d+",
    re.I,
)
NOT_REPORTED_RE = re.compile(
    r"\b(?:not\s+(?:reported|provided|shown|specified|available)|not\s+presented|"
    r"no\s+(?:formula|equation|table)|unreported)\b|"
    r"未(?:报告|提供|展示|给出)|没有(?:报告|提供|公式|方程|表格)|不存在",
    re.I,
)
TEX_INCLUDE_RE = re.compile(r"\\(?:input|include)\s*\{([^{}]+)\}")
TEX_FILE_MARKER_RE = re.compile(r"% PAPER_LENS_FILE: (?P<path>[^\n]+)")
TEX_FIGURE_BLOCK_RE = re.compile(
    r"\\begin\{figure\*?\}(.*?)\\end\{figure\*?\}", re.S | re.I
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


def http_get(
    url: str,
    *,
    binary: bool = False,
    timeout: int | tuple[int, int] = HTTP_TIMEOUT,
    max_bytes: int | None = None,
) -> bytes | str:
    require_network_support()
    limit = max_bytes if max_bytes is not None else (MAX_PDF_BYTES if binary else MAX_HTML_BYTES)
    response = None
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            stream=True,
        )
        response.raise_for_status()
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                announced_size = int(content_length)
            except ValueError:
                announced_size = 0
            if announced_size > limit:
                raise PipelineError(
                    f"Refused {url}: response declares {announced_size} bytes; limit is {limit}."
                )
        payload = bytearray()
        for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
            if not chunk:
                continue
            payload.extend(chunk)
            if len(payload) > limit:
                raise PipelineError(f"Refused {url}: response exceeded the {limit}-byte limit.")
        encoding = response.encoding or "utf-8"
    except PipelineError:
        raise
    except Exception as exc:
        raise PipelineError(f"Could not fetch {url}: {exc}") from exc
    finally:
        if response is not None:
            response.close()
    result = bytes(payload)
    return result if binary else result.decode(encoding, errors="replace")


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
                "Paper Lens does not provide OCR; run OCR locally and retry."
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


def safe_download(url: str, destination: Path, *, max_bytes: int) -> None:
    require_network_support()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    response = None
    try:
        response = requests.get(
            url,
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            stream=True,
        )
        response.raise_for_status()
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                announced_size = int(content_length)
            except ValueError:
                announced_size = 0
            if announced_size > max_bytes:
                raise PipelineError(
                    f"Refused {url}: response declares {announced_size} bytes; limit is {max_bytes}."
                )
        downloaded = 0
        with tempfile.NamedTemporaryFile("wb", dir=destination.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > max_bytes:
                    raise PipelineError(f"Refused {url}: response exceeded the {max_bytes}-byte limit.")
                handle.write(chunk)
        if downloaded == 0:
            raise PipelineError(f"Downloaded an empty response from {url}")
        temp_path.replace(destination)
        temp_path = None
    except PipelineError:
        raise
    except Exception as exc:
        raise PipelineError(f"Could not fetch {url}: {exc}") from exc
    finally:
        if response is not None:
            response.close()
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


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
                    if pixmap.width * pixmap.height > MAX_SOURCE_IMAGE_PIXELS:
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
    normalized = name.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", normalized):
        return None
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
        return None
    return path.as_posix()


def convert_source_asset(data: bytes, archive_name: str, assets_dir: Path) -> str | None:
    suffix = Path(archive_name).suffix.lower()
    digest = hashlib.sha256(archive_name.encode("utf-8")).hexdigest()[:8]
    stem = slugify(Path(archive_name).stem, fallback="figure", max_length=55)
    assets_dir.mkdir(parents=True, exist_ok=True)
    require_pdf_support()
    document = None
    try:
        document = fitz.open(stream=data, filetype=suffix.removeprefix("."))
        if document.page_count == 0:
            return None
        page = document[0]
        rect = page.rect
        if rect.width <= 0 or rect.height <= 0:
            return None
        scale = min(2.0, math.sqrt(MAX_SOURCE_IMAGE_PIXELS / (rect.width * rect.height)))
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        if pixmap.width * pixmap.height > MAX_SOURCE_IMAGE_PIXELS:
            return None
        output = assets_dir / f"source-{stem}-{digest}.png"
        pixmap.save(output)
        return f"assets/{output.name}"
    except Exception:
        return None
    finally:
        if document is not None:
            document.close()


def normalize_source_reference(reference: str, source_file: str = "") -> str | None:
    normalized = reference.strip().replace("\\", "/")
    if not normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
        return None
    candidate = posixpath.normpath(posixpath.join(posixpath.dirname(source_file), normalized))
    if candidate in {"", "."} or candidate == ".." or candidate.startswith("../"):
        return None
    return candidate


def resolve_tex_sources(tex_files: dict[str, str]) -> tuple[str, list[str]]:
    """Expand safe relative TeX includes without executing TeX or archive files."""

    warnings: list[str] = []
    warning_set: set[str] = set()
    expanded: set[str] = set()
    stack: list[str] = []

    def warn(message: str) -> None:
        if message not in warning_set:
            warning_set.add(message)
            warnings.append(message)

    def resolve_include(source_file: str, reference: str) -> str | None:
        normalized = normalize_source_reference(reference, source_file)
        if normalized is None:
            warn(
                f"Unsafe TeX include {reference!r} in {source_file}; the reference was not expanded."
            )
            return None
        candidates = [normalized]
        if not PurePosixPath(normalized).suffix:
            candidates.append(f"{normalized}.tex")
        for candidate in candidates:
            if candidate in tex_files:
                return candidate
        warn(
            f"Missing TeX include {reference!r} referenced from {source_file}; "
            "the reference was not expanded."
        )
        return None

    def render(path: str) -> str:
        if path in stack:
            cycle = " -> ".join([*stack, path])
            warn(f"TeX include cycle detected: {cycle}.")
            return ""
        if path in expanded:
            return ""
        expanded.add(path)
        stack.append(path)
        body = tex_files[path]
        chunks = [f"% PAPER_LENS_FILE: {path}\n"]
        cursor = 0
        for match in TEX_INCLUDE_RE.finditer(body):
            line_start = body.rfind("\n", 0, match.start()) + 1
            if body[line_start:match.start()].lstrip().startswith("%"):
                continue
            chunks.append(body[cursor:match.start()])
            reference = match.group(1).strip()
            resolved = resolve_include(path, reference)
            if resolved is None or resolved in stack:
                if resolved in stack:
                    cycle = " -> ".join([*stack, resolved])
                    warn(f"TeX include cycle detected: {cycle}.")
                chunks.append(match.group(0))
            else:
                chunks.append(render(resolved))
            cursor = match.end()
        chunks.append(body[cursor:])
        chunks.append(f"\n% END PAPER_LENS_FILE: {path}\n")
        stack.pop()
        return "".join(chunks)

    roots: list[str] = []
    if "main.tex" in tex_files:
        roots.append("main.tex")
    document_roots = sorted(
        path
        for path, body in tex_files.items()
        if re.search(r"\\documentclass(?:\[[^\]]*\])?\s*\{", body, re.I)
    )
    roots.extend(path for path in document_roots if path not in roots)
    roots.extend(path for path in sorted(tex_files) if path not in roots)
    source_text = "".join(render(path) for path in roots if path not in expanded)
    if not source_text:
        warnings.append("The arXiv source archive contained no readable TeX files.")
    return source_text, warnings


def find_source_asset(
    include_value: str, source_file: str, source_assets: list[dict[str, Any]]
) -> tuple[str, str]:
    assets_by_path = {
        str(item.get("archive_path")): item
        for item in source_assets
        if item.get("archive_path") and item.get("path")
    }
    normalized_paths: list[str] = []
    for base in (source_file, ""):
        normalized = normalize_source_reference(include_value, base)
        if normalized and normalized not in normalized_paths:
            normalized_paths.append(normalized)
    if not normalized_paths:
        return "", ""
    candidates: list[str] = []
    for normalized in normalized_paths:
        candidates.append(normalized)
        if not PurePosixPath(normalized).suffix:
            candidates.extend(
                f"{normalized}{suffix}" for suffix in sorted(SOURCE_IMAGE_SUFFIXES)
            )
    for candidate in candidates:
        item = assets_by_path.get(candidate)
        if item:
            return str(item["path"]), candidate

    requested_name = PurePosixPath(normalized_paths[0]).name
    requested_stem = PurePosixPath(requested_name).stem
    basename_matches = [
        item
        for archive_path, item in assets_by_path.items()
        if PurePosixPath(archive_path).name == requested_name
        or (
            not PurePosixPath(requested_name).suffix
            and PurePosixPath(archive_path).stem == requested_stem
        )
    ]
    if len(basename_matches) == 1:
        item = basename_matches[0]
        return str(item["path"]), str(item["archive_path"])
    return "", ""


def parse_figure_context(source_text: str, source_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    figures: list[dict[str, Any]] = []
    for match in TEX_FIGURE_BLOCK_RE.finditer(source_text):
        block = match.group(1)
        include = re.search(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", block)
        caption = re.search(r"\\caption\{(.*?)\}", block, re.S)
        label = re.search(r"\\label\{([^}]+)\}", block)
        section_matches = list(
            re.finditer(r"\\(?:section|subsection|subsubsection)\*?\{([^}]+)\}", source_text[: match.start()])
        )
        include_value = include.group(1).strip() if include else ""
        marker_matches = list(TEX_FILE_MARKER_RE.finditer(source_text[: match.start()]))
        source_file = marker_matches[-1].group("path").strip() if marker_matches else ""
        asset_path, archive_path = find_source_asset(
            include_value, source_file, source_assets
        )
        figures.append(
            {
                "origin": "arxiv_source",
                "includegraphics": include_value,
                "path": asset_path or "",
                "archive_path": archive_path,
                "source_file": source_file,
                "caption": re.sub(r"\s+", " ", caption.group(1)).strip() if caption else "",
                "label": label.group(1).strip() if label else "",
                "section": section_matches[-1].group(1).strip() if section_matches else "",
            }
        )
    return figures


def extract_source_bundle(source_tar: Path, workspace: Path) -> tuple[list[dict[str, Any]], str, list[str]]:
    source_assets: list[dict[str, Any]] = []
    tex_files: dict[str, str] = {}
    warnings: list[str] = []
    try:
        archive = tarfile.open(source_tar, "r:*")
    except tarfile.TarError as exc:
        return [], "", [f"Could not open the arXiv source archive: {exc}"]
    with archive:
        member_count = 0
        selected_bytes = 0
        for member in archive:
            member_count += 1
            if member_count > MAX_ARCHIVE_MEMBERS:
                raise PipelineError(
                    f"The arXiv source archive exceeds the {MAX_ARCHIVE_MEMBERS}-member limit."
                )
            safe_name = safe_archive_name(member.name)
            if not safe_name or not member.isfile():
                continue
            suffix = Path(safe_name).suffix.lower()
            if suffix not in SOURCE_IMAGE_SUFFIXES and suffix != ".tex":
                continue
            if member.size < 0 or member.size > MAX_ARCHIVE_MEMBER_BYTES:
                raise PipelineError(
                    f"Archive member {safe_name!r} exceeds the {MAX_ARCHIVE_MEMBER_BYTES}-byte limit."
                )
            selected_bytes += member.size
            if selected_bytes > MAX_SOURCE_EXPANDED_BYTES:
                raise PipelineError(
                    "Selected arXiv source files exceed the "
                    f"{MAX_SOURCE_EXPANDED_BYTES}-byte expansion limit."
                )
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            data = extracted.read(member.size + 1)
            if len(data) > member.size or len(data) > MAX_ARCHIVE_MEMBER_BYTES:
                raise PipelineError(f"Archive member {safe_name!r} expanded beyond its declared size.")
            if suffix == ".tex":
                tex_files[safe_name] = data.decode("utf-8", errors="replace")
                continue
            path = convert_source_asset(data, safe_name, workspace / "assets")
            if path:
                source_assets.append({"origin": "arxiv_source", "archive_path": safe_name, "path": path})
    source_text, source_warnings = resolve_tex_sources(tex_files)
    warnings.extend(source_warnings)
    write_text(workspace / "cache" / "source.tex", source_text)
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
    if source_path.stat().st_size > MAX_PDF_BYTES:
        raise PipelineError(f"Local PDF exceeds the {MAX_PDF_BYTES}-byte limit: {source_path}")
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
    html = http_get(initial_url, max_bytes=MAX_HTML_BYTES)
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
        safe_download(arxiv["pdf_url"], pdf_path, max_bytes=MAX_PDF_BYTES)
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
        source_ready = source_tar.exists() and not (refresh or source_changed)
        if refresh or source_changed or not source_tar.exists():
            try:
                safe_download(
                    arxiv["source_url"],
                    source_tar,
                    max_bytes=MAX_SOURCE_ARCHIVE_BYTES,
                )
                source_ready = True
            except PipelineError as exc:
                warnings.append(str(exc))
        source_assets: list[dict[str, Any]] = []
        source_text = ""
        if source_ready:
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
    parsed_input = urlparse(input_value.strip())
    if parsed_input.scheme and parsed_input.netloc and "arxiv.org" not in parsed_input.netloc.lower():
        raise PipelineError("Paper Lens accepts only an arXiv URL/ID or an existing local .pdf path.")
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


def _line_number(report: str, offset: int) -> int:
    return report.count("\n", 0, offset) + 1


def _paragraph_context(lines: list[str], line_index: int) -> tuple[int, int, str]:
    start = line_index
    while start > 0 and lines[start - 1].strip():
        start -= 1
    end = line_index + 1
    while end < len(lines) and lines[end].strip():
        end += 1
    return start + 1, end, " ".join(line.strip() for line in lines[start:end]).strip()


def _grounding_diagnostic(
    kind: str, start_line: int, end_line: int, context: str
) -> str:
    anchor_examples = (
        "Equation (1), Section 2, p. 3"
        if kind == "formula"
        else "Table 1, Section 3, p. 3"
    )
    snippet = re.sub(r"\s+", " ", context).strip()[:140]
    suffix = f" Context: {snippet!r}." if snippet else "."
    return (
        f"{kind.title()} discussion at lines {start_line}-{end_line} needs a "
        f"source-location anchor such as {anchor_examples}{suffix}"
    )


def validate_formula_table_grounding(
    report: str, errors: list[str]
) -> dict[str, list[dict[str, Any]]]:
    """Check formula/table evidence locally without judging scientific correctness."""

    lines = report.splitlines()
    checks: dict[str, list[dict[str, Any]]] = {"formulas": [], "tables": []}
    seen: set[tuple[str, int, int]] = set()

    def add_check(
        kind: str,
        line_index: int,
        start_line: int,
        end_line: int,
        context_start: int | None = None,
        context_end: int | None = None,
    ) -> None:
        key = (kind, start_line, end_line)
        if key in seen:
            return
        seen.add(key)
        context_start = context_start or start_line
        context_end = context_end or end_line
        context = " ".join(line.strip() for line in lines[context_start - 1 : context_end]).strip()
        not_reported = bool(NOT_REPORTED_RE.search(context))
        anchored = bool(ANCHOR_RE.search(context))
        entry = {
            "line": line_index + 1,
            "block_start": start_line,
            "block_end": end_line,
            "anchor_found": anchored,
            "not_reported": not_reported,
        }
        checks["formulas" if kind == "formula" else "tables"].append(entry)
        if not not_reported and not anchored:
            errors.append(_grounding_diagnostic(kind, start_line, end_line, context))

    display_math_re = re.compile(r"\$\$(.+?)\$\$", re.S)
    display_math_lines: list[int] = []
    for match in display_math_re.finditer(report):
        line_index = _line_number(report, match.start()) - 1
        start_line, end_line, _ = _paragraph_context(lines, line_index)
        display_math_lines.append(line_index)
        add_check(
            "formula",
            line_index,
            start_line,
            end_line,
            max(1, start_line - 2),
            min(len(lines), end_line + 1),
        )

    for line_index, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        kind = None
        if FORMULA_DISCUSSION_RE.search(line):
            kind = "formula"
        elif TABLE_DISCUSSION_RE.search(line):
            kind = "table"
        if kind is None:
            continue
        if kind == "formula" and any(abs(line_index - display_line) <= 2 for display_line in display_math_lines):
            continue
        start_line, end_line, _ = _paragraph_context(lines, line_index)
        add_check(kind, line_index, start_line, end_line)

    table_row_indexes = [
        index
        for index, line in enumerate(lines)
        if line.count("|") >= 2 and line.strip().startswith("|")
    ]
    for line_index in table_row_indexes:
        start_line, end_line, _ = _paragraph_context(lines, line_index)
        add_check("table", line_index, start_line, end_line)
    return checks


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
    grounding_checks = validate_formula_table_grounding(report, errors)
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
        "grounding_checks": grounding_checks,
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
    parser.add_argument("--version", action="version", version=f"%(prog)s {PLUGIN_VERSION}")
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
