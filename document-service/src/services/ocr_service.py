import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_IMAGE_TYPES = {
    "image/jpeg", "image/jpg", "image/png",
    "image/tiff", "image/bmp", "image/gif", "image/webp",
}


@dataclass
class ExtractionResult:
    text: str
    page_count: int | None = None


def _extract_pdf(file_bytes: bytes) -> ExtractionResult:
    import pdfplumber
    parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                parts.append(text.strip())
    return ExtractionResult(text="\n\n".join(parts), page_count=page_count)


def _extract_image(file_bytes: bytes) -> ExtractionResult:
    import pytesseract
    from PIL import Image
    img = Image.open(io.BytesIO(file_bytes))
    return ExtractionResult(text=pytesseract.image_to_string(img).strip())


def _extract_docx(file_bytes: bytes) -> ExtractionResult:
    from docx import Document
    doc = Document(io.BytesIO(file_bytes))
    return ExtractionResult(text="\n".join(p.text for p in doc.paragraphs if p.text.strip()))


def extract_text(file_bytes: bytes, mime_type: str, filename: str = "") -> ExtractionResult:
    suffix = Path(filename).suffix.lower()
    try:
        if mime_type == "application/pdf" or suffix == ".pdf":
            return _extract_pdf(file_bytes)
        if mime_type in _IMAGE_TYPES or suffix in {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif", ".webp"}:
            return _extract_image(file_bytes)
        if (
            mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            or suffix == ".docx"
        ):
            return _extract_docx(file_bytes)
        return ExtractionResult(text=file_bytes.decode("utf-8", errors="replace"))
    except Exception as exc:
        logger.error("Text extraction failed for %s (%s): %s", filename, mime_type, exc)
        return ExtractionResult(text="")
