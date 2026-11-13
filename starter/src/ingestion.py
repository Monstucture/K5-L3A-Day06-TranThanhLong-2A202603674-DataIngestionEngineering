"""Read and normalize source data."""
import re
import unicodedata
from pathlib import Path

from pypdf import PdfReader

from .models import DocumentPage

# Repeated page furniture that pypdf returns as its own lines:
#   even pages: "8 1 • An Introduction to the Human Body" + "Access for free at openstax.org"
#   odd pages:  "1.2 • Structural Organization of the Human Body 9"
_FOOTER_PATTERNS = [
    re.compile(r"^Access for free at openstax\.org$"),
    re.compile(r"^\d+ \d+ • .+$"),
    re.compile(r"^\d+\.\d+ • .+ \d+$"),
]
# OpenStax chapter opening pages carry a line "CHAPTER 2" followed by the chapter title.
_CHAPTER_HEADING = re.compile(r"^CHAPTER (\d+)$")
EMPTY_PAGE_CHARS = 50  # pages with less text than this are logged as empty


def load_pdf(path: Path, document_id: str, source: str) -> tuple[list[DocumentPage], list[dict]]:
    """Return one DocumentPage per physical page, plus a log of empty/failed pages.

    The chapter is detected from each chapter's opening page and carried forward
    to the following pages, so metadata["chapter"] comes from the source itself.
    """
    reader = PdfReader(path)
    pages: list[DocumentPage] = []
    problems: list[dict] = []
    chapter: int | None = None
    chapter_title: str | None = None

    for page_no, pdf_page in enumerate(reader.pages, start=1):
        try:
            raw = pdf_page.extract_text() or ""
        except Exception as error:  # keep going, but record the failure
            problems.append({"page": page_no, "problem": f"extract failed: {error}"})
            continue

        text = normalize_text(raw)
        lines = text.split("\n")
        for i, line in enumerate(lines):
            match = _CHAPTER_HEADING.match(line)
            if match:
                chapter = int(match.group(1))
                chapter_title = lines[i + 1] if i + 1 < len(lines) else None
                break

        if len(text) < EMPTY_PAGE_CHARS:
            problems.append({"page": page_no, "problem": f"only {len(text)} chars"})
        if chapter is None:
            problems.append({"page": page_no, "problem": "before first chapter heading"})

        pages.append(DocumentPage(
            document_id=document_id,
            source=source,
            page=page_no,
            text=text,
            metadata={"chapter": chapter, "chapter_title": chapter_title},
        ))
    return pages, problems


def normalize_text(text: str) -> str:
    """NFKC, drop header/footer lines, tidy spaces; keep one line per PDF line."""
    text = unicodedata.normalize("NFKC", text)
    kept = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if not line or any(p.match(line) for p in _FOOTER_PATTERNS):
            continue
        kept.append(line)
    return "\n".join(kept)
