"""Deterministic, bounded PDF ingestion with page-preserving provenance."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re


MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PAGES = 500


class IngestionError(ValueError):
    """The source cannot be safely or reproducibly ingested."""


def normalize_text(text):
    """Normalize extraction noise without changing page boundaries."""
    text = text.replace("\ufffd", '"').replace("\u201c", '"').replace("\u201d", '"')
    text = text.replace("\u00d7", "x").replace("\u00b2", "2")
    text = re.sub(r"[\t\r ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


@dataclass(frozen=True)
class PageText:
    pdf_page: int
    text: str
    sha256: str


@dataclass(frozen=True)
class PdfDocument:
    path: str
    sha256: str
    byte_length: int
    page_count: int
    metadata: dict
    pages: tuple

    def page(self, number):
        if not 1 <= number <= self.page_count:
            raise IngestionError(f"Page {number} is outside the document")
        return self.pages[number - 1]


def ingest_pdf(path, *, expected_sha256=None):
    """Read original PDF bytes and extract normalized text one page at a time."""
    path = Path(path)
    data = path.read_bytes()
    if not data.startswith(b"%PDF-"):
        raise IngestionError("Source does not have a PDF signature")
    if len(data) > MAX_PDF_BYTES:
        raise IngestionError(f"PDF exceeds {MAX_PDF_BYTES} byte limit")
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 and digest != expected_sha256.lower():
        raise IngestionError("PDF SHA-256 does not match the extraction request")
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise IngestionError("pypdf is required for PDF ingestion") from exc
    try:
        reader = PdfReader(path)
    except Exception as exc:
        raise IngestionError(f"Unable to parse PDF: {exc}") from exc
    # PdfReader already verifies the document password during construction. The
    # Bosch source is permissions-encrypted but opens with the empty public
    # password, so it remains a valid deterministic input.
    if not 1 <= len(reader.pages) <= MAX_PAGES:
        raise IngestionError(f"PDF page count must be between 1 and {MAX_PAGES}")
    pages = []
    for index, page in enumerate(reader.pages, 1):
        try:
            text = normalize_text(page.extract_text() or "")
        except Exception as exc:
            raise IngestionError(f"Text extraction failed on PDF page {index}: {exc}") from exc
        pages.append(PageText(index, text, hashlib.sha256(text.encode()).hexdigest()))
    metadata = {str(k).lstrip("/"): str(v) for k, v in (reader.metadata or {}).items()}
    return PdfDocument(str(path), digest, len(data), len(pages), metadata, tuple(pages))


def document_from_page_map(page_count, pages, *, sha256, metadata=None, path="golden-page-map"):
    """Build a document from reviewed page text for offline golden tests."""
    page_objects = []
    for number in range(1, page_count + 1):
        text = normalize_text(pages.get(str(number), pages.get(number, "")))
        page_objects.append(PageText(number, text, hashlib.sha256(text.encode()).hexdigest()))
    return PdfDocument(path, sha256, 0, page_count, metadata or {}, tuple(page_objects))
