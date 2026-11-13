"""Fixed-size (strategy A) and structure-aware (strategy B) chunking."""
import re

from .models import Chunk, DocumentPage

# A line ending like this closes a sentence, so the next line may start a new paragraph.
_SENTENCE_END = re.compile(r"[.!?:][\"”’)]*$")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|(?<=[.!?][\"”’)])\s+")
HEADING_MAX_CHARS = 80  # short lines without final punctuation are treated as headings


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


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Pack whole paragraphs (or whole sentences of long ones) into chunks of at most `max_size` chars."""
    if max_size <= 0:
        raise ValueError(f"need max_size > 0, got {max_size=}")
    units: list[str] = []
    for paragraph in _paragraphs(page.text):
        units.extend([paragraph] if len(paragraph) <= max_size else _split_long(paragraph, max_size))

    # Units are joined with single spaces, so each chunk is an exact substring of the
    # page text with line breaks turned into spaces (same length, same offsets).
    flat = page.text.replace("\n", " ")
    chunks: list[Chunk] = []
    cursor = 0

    def close(text: str) -> None:
        nonlocal cursor
        start = flat.find(text, cursor)
        chunks.append(_make_chunk(page, len(chunks), text, start))
        cursor = max(cursor, start)

    current = ""
    for unit in units:
        joined = f"{current} {unit}" if current else unit
        if len(joined) <= max_size:
            current = joined
            continue
        close(current)
        current = unit
    if current:
        close(current)
    return chunks
