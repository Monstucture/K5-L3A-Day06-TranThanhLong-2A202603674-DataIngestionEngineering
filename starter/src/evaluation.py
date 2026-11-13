"""Score retrieved evidence (Hit@1, Evidence Hit@3) and aggregate per strategy and split."""
import unicodedata
from collections import defaultdict
from typing import Any


def flat(text: str) -> str:
    """Same normalization on both sides: NFKC + collapse all whitespace."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _gold_evidence(question: dict[str, Any]) -> list[tuple[int, str]]:
    """The main (page, quote) plus any documented alternatives: [{"page": 12, "quote": "..."}]."""
    golds = [(question["gold_page"], question["evidence_quote"])]
    golds += [(alt["page"], alt["quote"]) for alt in question.get("alternative_evidence", [])]
    return golds


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    """A hit is a chunk from a gold page that contains the whole gold evidence quote.

    This is the automatic retrieval metric only; coherence and grounding are labelled by hand.
    """
    golds = [(page, flat(quote)) for page, quote in _gold_evidence(question)]
    checks = []
    for rank, hit in enumerate(hits, start=1):
        text = flat(hit["text"])
        page_match = any(hit["page"] == page for page, _ in golds)
        evidence_match = any(hit["page"] == page and quote in text for page, quote in golds)
        checks.append({"rank": rank, "chunk_id": hit["chunk_id"], "page": hit["page"],
                       "page_match": page_match, "evidence_match": evidence_match})

    hit_ranks = [c["rank"] for c in checks if c["evidence_match"]]
    return {
        "gold_page": question["gold_page"],
        "evidence_quote": question["evidence_quote"],
        "checks": checks,
        "hit@1": bool(hit_ranks) and hit_ranks[0] == 1,
        "hit@3": any(r <= 3 for r in hit_ranks),
        "first_hit_rank": hit_ranks[0] if hit_ranks else None,
        # Diagnostic only: right page in top-3 but evidence split across chunks or incomplete.
        "page_hit@3": any(c["page_match"] for c in checks if c["rank"] <= 3),
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts as n/N plus rates, per strategy and split."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for trace in traces:
        groups[(trace["strategy"], trace["split"])].append(trace)

    summary: dict[str, Any] = defaultdict(dict)
    for (strategy, split), group in sorted(groups.items()):
        n = len(group)
        row: dict[str, Any] = {"questions": n}
        for metric in ("hit@1", "hit@3", "page_hit@3"):
            k = sum(1 for t in group if t[metric])
            row[metric] = f"{k}/{n}"
            row[f"{metric}_rate"] = round(k / n, 3)
        row["misses@3"] = [t["question_id"] for t in group if not t["hit@3"]]
        summary[strategy][split] = row
    return dict(summary)
