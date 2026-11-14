"""Checks for OCR figure chunks. Run from starter/: python -m tests.test_chunking (also works with pytest)."""
from src.chunking import figure_chunks
from src.models import DocumentPage

PAGE = DocumentPage("doc", "doc.pdf", 7, "page text", {"chapter": 1, "chapter_title": "Intro"})


def test_one_chunk_per_figure_with_page_metadata():
    chunks = figure_chunks(PAGE, [{"xref": 53, "text": "Frontal\nplane  Sagittal plane"}], 500)
    assert [c.chunk_id for c in chunks] == ["doc:p007:fig53:c00"]
    assert chunks[0].text == "Frontal plane Sagittal plane"
    assert chunks[0].metadata["chapter"] == 1 and chunks[0].metadata["page_end"] == 7
    assert chunks[0].metadata["content_type"] == "figure_ocr"


def test_empty_ocr_text_makes_no_chunk_and_long_text_is_split():
    assert figure_chunks(PAGE, [{"xref": 1, "text": "  "}], 500) == []
    long = ". ".join(["Label number one is here"] * 40) + "."
    chunks = figure_chunks(PAGE, [{"xref": 2, "text": long}], 200)
    assert len(chunks) > 1 and all(len(c.text) <= 200 for c in chunks)
    assert len({c.chunk_id for c in chunks}) == len(chunks)


if __name__ == "__main__":
    tests = [f for name, f in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"{len(tests)} chunking tests passed")
