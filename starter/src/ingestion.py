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
END_OF_CHAPTER = "Key Terms"  # from here to the next chapter: glossary, summary, review questions
BACK_MATTER = {"REFERENCES", "INDEX"}  # first line of the book's closing sections


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
                chapter_title = chapter_title_after(lines, i)
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


def chapter_title_after(lines: list[str], heading: int) -> str | None:
    """The title under a "CHAPTER n" line; long titles wrap onto a second line before "Chapter Objectives"."""
    after = lines[heading + 1:heading + 4]  # titles never wrap past 3 lines
    end = next((k for k, line in enumerate(after) if line.startswith("Chapter Objectives")), None)
    title = after[:end] if end else after[:1]  # no marker: trust only the first line
    return " ".join(title) or None


def content_pages(pages: list[DocumentPage]) -> list[DocumentPage]:
    """The manifest's counting rule, applied automatically: chapter body pages only.

    Skips front matter (cover, contents, preface: no chapter yet), each chapter's
    "Key Terms" page up to the next chapter (glossary, summary, review questions),
    everything from REFERENCES/INDEX on, and near-empty pages.
    """
    kept, chapter, in_review, in_back_matter = [], None, False, False
    for page in pages:
        first_line = page.text.split("\n", 1)[0].strip()
        if page.metadata.get("chapter") != chapter:
            chapter, in_review = page.metadata.get("chapter"), False
        in_review = in_review or first_line.startswith(END_OF_CHAPTER)
        in_back_matter = in_back_matter or first_line.upper() in BACK_MATTER
        if chapter is None or in_review or in_back_matter or len(page.text) < EMPTY_PAGE_CHARS:
            continue
        kept.append(page)
    return kept


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
