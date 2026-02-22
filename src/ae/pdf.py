"""PDF parsing facade — pymupdf for text, MinerU for complex layouts, OCR fallback."""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Any

import fitz  # pymupdf
import httpx

from ae.config import get_settings

logger = logging.getLogger(__name__)


def compute_file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_pdf_pymupdf(path: Path) -> dict[str, Any]:
    """Parse PDF using pymupdf. Returns page texts and metadata."""
    doc = fitz.open(str(path))
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text("text")
        pages.append({
            "page_number": i + 1,
            "text": text,
            "width": page.rect.width,
            "height": page.rect.height,
        })
    metadata = doc.metadata or {}
    doc.close()
    return {
        "method": "pymupdf",
        "page_count": len(pages),
        "pages": pages,
        "metadata": metadata,
    }


def parse_pdf_mineru(path: Path) -> dict[str, Any]:
    """Parse PDF using MinerU API for complex layouts with tables/figures."""
    settings = get_settings()
    api_key = settings.mineru_api_key
    if not api_key:
        raise ValueError("MINERU_API_KEY not set")

    # Submit job
    with open(path, "rb") as f:
        file_data = f.read()

    import base64
    file_b64 = base64.b64encode(file_data).decode()
    filename = path.name

    submit_url = "https://mineru.net/api/v4/file-urls/batch"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = {
        "files": [{"name": filename, "is_ocr": True, "data_id": filename}],
        "enable_formula": True,
        "enable_table": True,
        "layout_model": "doclayout_yolo",
        "language": "ch",
    }

    with httpx.Client(timeout=120) as client:
        resp = client.post(submit_url, json=payload, headers=headers)
        resp.raise_for_status()
        submit_data = resp.json()

    batch_id = submit_data.get("data", {}).get("batch_id")
    if not batch_id:
        # Try file upload approach
        upload_url = "https://mineru.net/api/v4/extract/task"
        with open(path, "rb") as f:
            resp = httpx.post(
                upload_url,
                files={"file": (filename, f, "application/pdf")},
                data={"is_ocr": "true", "enable_formula": "true", "enable_table": "true"},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=120,
            )
        resp.raise_for_status()
        task_data = resp.json()
        task_id = task_data.get("data", {}).get("task_id", "")

        # Poll for result
        result_url = f"https://mineru.net/api/v4/extract/task/{task_id}"
        for _ in range(60):
            time.sleep(5)
            resp = httpx.get(result_url, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json().get("data", {})
            if data.get("state") == "done":
                return {
                    "method": "mineru",
                    "page_count": data.get("page_count", 0),
                    "pages": data.get("pages", []),
                    "full_result": data,
                }
        raise TimeoutError("MinerU parsing timed out")

    # Poll batch
    status_url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
    for _ in range(60):
        time.sleep(5)
        resp = httpx.get(status_url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        extract_results = data.get("extract_result", [])
        if extract_results and extract_results[0].get("state") == "done":
            result = extract_results[0]
            return {
                "method": "mineru",
                "page_count": result.get("page_count", 0),
                "pages": result.get("pages", []),
                "full_result": result,
            }

    raise TimeoutError("MinerU batch parsing timed out")


def parse_pdf(path: Path, method: str = "auto") -> dict[str, Any]:
    """Parse a PDF file using the specified method.

    Methods:
        auto: Try pymupdf first, fall back to MinerU if text is sparse
        pymupdf: Direct text extraction
        mineru: MinerU API for complex layouts
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    if method == "pymupdf":
        return parse_pdf_pymupdf(path)
    elif method == "mineru":
        return parse_pdf_mineru(path)

    # Auto mode: try pymupdf, fall back if text is sparse
    result = parse_pdf_pymupdf(path)
    total_chars = sum(len(p["text"]) for p in result["pages"])
    avg_chars_per_page = total_chars / max(len(result["pages"]), 1)

    if avg_chars_per_page < 100 and len(result["pages"]) > 0:
        logger.info(
            "Sparse text detected (avg %.0f chars/page), trying MinerU: %s",
            avg_chars_per_page,
            path.name,
        )
        try:
            return parse_pdf_mineru(path)
        except Exception as e:
            logger.warning("MinerU fallback failed: %s, using pymupdf result", e)

    return result


def get_page_text(parse_result: dict[str, Any], page_num: int) -> str:
    """Get text for a specific page (1-indexed)."""
    for page in parse_result.get("pages", []):
        pn = page.get("page_number", page.get("page_num", 0))
        if pn == page_num:
            return page.get("text", "")
    return ""


def get_all_text(parse_result: dict[str, Any]) -> str:
    """Get concatenated text from all pages."""
    texts = []
    for page in parse_result.get("pages", []):
        text = page.get("text", "")
        if text:
            texts.append(text)
    return "\n\n".join(texts)


def render_page_to_image(pdf_path: Path, page_num: int, dpi: int = 150) -> bytes:
    """Render a PDF page to PNG image bytes."""
    doc = fitz.open(str(pdf_path))
    page = doc[page_num - 1]
    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    img_bytes = pix.tobytes("png")
    doc.close()
    return img_bytes


def extract_filename_metadata(filename: str) -> dict[str, str]:
    """Extract metadata from Chinese research report filenames.

    Format: {证券公司}：{报告标题}_{作者}_{类别}_{日期}.pdf
    """
    name = filename.replace(".pdf", "").replace(".PDF", "")

    result: dict[str, str] = {}

    # Split on ： (full-width colon)
    if "：" in name:
        parts = name.split("：", 1)
        result["broker"] = parts[0].strip()
        name = parts[1].strip()
    elif ":" in name:
        parts = name.split(":", 1)
        result["broker"] = parts[0].strip()
        name = parts[1].strip()

    # Split remaining on _
    segments = name.rsplit("_", 3)
    if len(segments) >= 4:
        result["title"] = segments[0].strip()
        result["authors"] = segments[1].strip()
        result["category"] = segments[2].strip()
        result["date"] = segments[3].strip()
    elif len(segments) == 3:
        result["title"] = segments[0].strip()
        result["authors"] = segments[1].strip()
        result["category"] = segments[2].strip()
    elif len(segments) == 2:
        result["title"] = segments[0].strip()
        result["authors"] = segments[1].strip()
    else:
        result["title"] = name

    return result
