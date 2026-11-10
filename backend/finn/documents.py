"""Download and read source PDFs, once.

Every document is cached on disk under the hash of its URL: the raw PDF and the
extracted per-page text. Nothing is downloaded or parsed twice, which is what keeps
both the exchange and the model bill quiet.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pymupdf
import requests

from .config import CACHE_DIR, USER_AGENT

PDF_DIR = CACHE_DIR / "pdf"
TEXT_DIR = CACHE_DIR / "text"
MAX_BYTES = 60 * 1024 * 1024


class DocumentError(RuntimeError):
    """The document could not be fetched or is not a readable PDF."""


def url_key(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]


def download(url: str, referer: str | None = None, timeout: int = 90) -> Path:
    """Return the cached PDF path, downloading it on first use."""
    path = PDF_DIR / f"{url_key(url)}.pdf"
    if path.exists() and path.stat().st_size > 0:
        return path
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"}
    if referer:
        headers["Referer"] = referer
    try:
        with requests.get(url, headers=headers, timeout=timeout, stream=True) as resp:
            resp.raise_for_status()
            data = bytearray()
            for chunk in resp.iter_content(chunk_size=1 << 16):
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    raise DocumentError(f"Document larger than {MAX_BYTES >> 20} MB: {url}")
    except requests.RequestException as exc:
        raise DocumentError(f"Download failed: {exc}") from exc
    if not bytes(data[:1024]).lstrip().startswith(b"%PDF"):
        # Exchanges sometimes attach a zip or an XBRL/HTML page instead of a PDF.
        raise DocumentError(f"Not a PDF (starts with {bytes(data[:8])!r}): {url}")
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(path)  # atomic: a half-written file never looks like a cached one
    return path


def pages(url: str, referer: str | None = None) -> list[str]:
    """Per-page text for a document (index 0 = page 1). Cached as JSON."""
    cache = TEXT_DIR / f"{url_key(url)}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    pdf = download(url, referer)
    try:
        with pymupdf.open(pdf) as doc:
            text = [page.get_text() for page in doc]
    except Exception as exc:  # noqa: BLE001 - corrupt or encrypted file
        raise DocumentError(f"Could not read PDF: {exc}") from exc
    if not text:
        raise DocumentError("PDF has no pages")
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(text, ensure_ascii=False), encoding="utf-8")
    return text


def has_text_layer(page_texts: list[str], min_chars_per_page: int = 200) -> bool:
    """False for image-only scans, which would need OCR (the last resort)."""
    if not page_texts:
        return False
    return sum(len(t) for t in page_texts) / len(page_texts) >= min_chars_per_page
