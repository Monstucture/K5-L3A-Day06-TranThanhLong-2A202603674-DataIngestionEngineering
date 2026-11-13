"""Fixed-size chunking (strategy A) and section-aware chunking (strategies B and C)."""
import re

from .models import Chunk, DocumentPage

# A line ending like this closes a sentence, so the next line may start a new paragraph.
_SENTENCE_END = re.compile(r"[.!?:][\"”’)]*$")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|(?<=[.!?][\"”’)])\s+")
HEADING_MAX_CHARS = 80  # short lines without final punctuation are treated as headings
# OpenStax section headings, e.g. "1.3 Functions of Human Life" (footers contain "•" and never match).
_SECTION_HEADING = re.compile(r"^(\d+\.\d+) ([A-Z][^.]*)$")


def _make_chunk(page: DocumentPage, index: int, text: str, start: int) -> Chunk:
    """Build a chunk that keeps the page's source, page number and metadata."""
    return Chunk(
        chunk_id=f"{page.document_id}:p{page.page:03d}:c{index:03d}",
        document_id=page.document_id,
        source=page.source,
        page=page.page,
        text=text,
        metadata={**page.metadata, "char_start": start, "char_end": start + len(text)},
    )


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Cut the page text into windows of `size` characters, each overlapping the last by `overlap`."""
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError(f"need size > 0 and 0 <= overlap < size, got {size=} {overlap=}")
    text = page.text
    step = size - overlap
    chunks = []
    start = 0
    while start < len(text):
        piece = text[start:start + size]
        if piece.strip():
            chunks.append(_make_chunk(page, len(chunks), piece, start))
        if start + size >= len(text):
            break
        start += step
    return chunks


def _paragraphs(text: str) -> list[str]:
    """Rebuild paragraphs from PDF lines; headings and bullets become their own paragraphs."""
    paragraphs: list[str] = []
    current: list[str] = []
    for line in text.split("\n"):
        is_bullet = line.startswith("•")
        is_heading = len(line) <= HEADING_MAX_CHARS and not _SENTENCE_END.search(line)
        if (is_bullet or is_heading) and current:
            paragraphs.append(" ".join(current))
            current = []
        current.append(line)
        if is_heading or _SENTENCE_END.search(line):
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def _split_long(paragraph: str, max_size: int) -> list[str]:
    """Split an oversized paragraph at sentence ends; hard-cut a single huge sentence."""
    pieces: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(paragraph):
        while len(sentence) > max_size:
            pieces.append(sentence[:max_size])
            sentence = sentence[max_size:]
        if sentence:
            pieces.append(sentence)
    return pieces


def by_section(pages: list[DocumentPage], max_size: int) -> list[Chunk]:
    """Pack paragraphs into chunks of at most `max_size` chars that never cross a section heading.

    A chunk may continue across a page break inside one section, so it carries a page range (`page` .. `page_end`) and the section number/title as metadata.
    Text before a chapter's first section is section "<chapter>.0", titled "Introduction".
    """
    if max_size <= 0:
        raise ValueError(f"need max_size > 0, got {max_size=}")
    chunks: list[Chunk] = []
    section = section_title = None
    current, first, last = "", None, None  # text being packed, its first and last page

    def close() -> None:
        nonlocal current
        if not current:
            return
        index = sum(1 for c in chunks if c.metadata["section"] == section)
        chunks.append(Chunk(
            chunk_id=f"{first.document_id}:s{section}:c{index:03d}",
            document_id=first.document_id,
            source=first.source,
            page=first.page,
            text=current,
            metadata={**first.metadata, "page_end": last.page,
                      "section": section, "section_title": section_title,
                      "char_start": first.text.replace("\n", " ").find(current[:60])},
        ))
        current = ""

    for page in pages:
        if section is None or not section.startswith(f"{page.metadata.get('chapter')}."):
            close()  # new chapter: start at its introduction
            section, section_title = f"{page.metadata.get('chapter')}.0", "Introduction"
        for paragraph in _paragraphs(page.text):
            heading = _SECTION_HEADING.match(paragraph)
            if heading and len(paragraph) <= HEADING_MAX_CHARS:
                close()
                section, section_title = heading.group(1), heading.group(2)
            pieces = [paragraph] if len(paragraph) <= max_size else _split_long(paragraph, max_size)
            for piece in pieces:
                joined = f"{current} {piece}" if current else piece
                if len(joined) > max_size:
                    close()
                    joined = piece
                if not current:
                    first = page
                current, last = joined, page
    close()
    return chunks
