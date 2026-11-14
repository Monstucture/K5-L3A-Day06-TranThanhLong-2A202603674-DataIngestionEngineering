"""Checks for OCR figure chunks. Run from starter/: python -m tests.test_chunking (also works with pytest)."""
from src.chunking import figure_chunks, with_heading
from src.ingestion import chapter_title_after
from src.models import DocumentPage
from src.store import filter_from_question

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


def test_heading_is_embedded_but_text_is_unchanged():
    chunk = figure_chunks(PAGE, [{"xref": 53, "text": "Frontal plane"}], 500)[0]
    chunk.metadata.update(section="1.6", section_title="Anatomical Terminology")
    assert with_heading(chunk) == "Chapter 1: Intro\n1.6 Anatomical Terminology\nFigure labels\nFrontal plane"
    assert chunk.text == "Frontal plane"


def test_filter_from_question():
    assert filter_from_question("What is chapter 20 about?") == {"chapter": 20}
    assert filter_from_question("Summarize Section 20.1 of chapter 20") == {"section": "20.1"}
    assert filter_from_question("What is a capillary?") is None


def test_wrapped_chapter_title_is_joined():
    lines = ["INTRODUCTION", "CHAPTER 20", "The Cardiovascular System: Blood Vessels and", "Circulation",
             "Chapter Objectives After studying this chapter, you will be able to:"]
    assert chapter_title_after(lines, 1) == "The Cardiovascular System: Blood Vessels and Circulation"
    assert chapter_title_after(["CHAPTER 9", "Joints", "Chapter Objectives"], 0) == "Joints"
    assert chapter_title_after(["CHAPTER 9", "Joints", "some body text", "more"], 0) == "Joints"


if __name__ == "__main__":
    tests = [f for name, f in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"{len(tests)} chunking tests passed")
