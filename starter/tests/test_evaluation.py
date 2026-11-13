"""Checks for the hit rule behind every reported Hit@1 / Hit@3.

Run from starter/:  python -m tests.test_evaluation   (also works with pytest)
"""
from src.evaluation import evaluate_query, summarize

QUESTION = {"id": "q01", "gold_page": 2,
            "evidence_quote": "Human anatomy is the scientific study of the body’s structures."}
QUOTE_TEXT = "Intro line.\nHuman anatomy is the scientific study\nof the body’s  structures. More text."


def hit(page: int, text: str, chunk_id: str = "B:x") -> dict:
    return {"chunk_id": chunk_id, "page": page, "text": text}


def test_quote_on_gold_page_is_a_hit_despite_line_breaks():
    result = evaluate_query(QUESTION, [hit(2, QUOTE_TEXT)])
    assert result["hit@1"] and result["hit@3"] and result["first_hit_rank"] == 1


def test_same_quote_on_wrong_page_is_a_miss():
    result = evaluate_query(QUESTION, [hit(5, QUOTE_TEXT)])
    assert not result["hit@3"] and not result["page_hit@3"]


def test_gold_page_without_full_quote_is_only_a_page_hit():
    result = evaluate_query(QUESTION, [hit(2, "Human anatomy is the scientific study")])
    assert not result["hit@3"] and result["page_hit@3"]


def test_hit_at_rank_three_counts_for_hit3_not_hit1():
    hits = [hit(9, "other", "a"), hit(9, "other", "b"), hit(2, QUOTE_TEXT, "c")]
    result = evaluate_query(QUESTION, hits)
    assert not result["hit@1"] and result["hit@3"] and result["first_hit_rank"] == 3


def test_section_chunk_spanning_pages_covers_the_gold_page():
    spanning = {**hit(1, QUOTE_TEXT), "page_end": 2}
    assert evaluate_query(QUESTION, [spanning])["hit@1"]
    ends_before = {**hit(0, QUOTE_TEXT), "page_end": 1}
    assert not evaluate_query(QUESTION, [ends_before])["hit@3"]


def test_summary_counts_as_n_over_n():
    traces = [{"strategy": "B", "split": "dev", "question_id": "q01", **evaluate_query(QUESTION, [hit(2, QUOTE_TEXT)])},
              {"strategy": "B", "split": "dev", "question_id": "q02", **evaluate_query(QUESTION, [hit(5, QUOTE_TEXT)])}]
    row = summarize(traces)["B"]["dev"]
    assert row["hit@1"] == "1/2" and row["hit@3"] == "1/2" and row["misses@3"] == ["q02"]


if __name__ == "__main__":
    tests = [f for name, f in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"{len(tests)} evaluation tests passed")
