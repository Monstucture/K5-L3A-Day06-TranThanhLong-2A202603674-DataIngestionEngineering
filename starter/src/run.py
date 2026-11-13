"""Day 06 pipeline: ingest -> chunk (A/B) -> embed -> store -> retrieve (A/B/C) -> evaluate.

Run from starter/ with the venv active, Docker (pgvector) and Ollama running:
    python -m src.run --split dev     # choose a strategy on dev only
    python -m src.run --split test    # after the choice is frozen
"""
import argparse
import csv
import json
import os
import platform
import statistics
import time
from dataclasses import replace
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from pypdf.errors import PdfReadError

from .chunking import by_section, fixed_size
from .embeddings import MyEmbedder
from .evaluation import evaluate_query, flat, summarize
from .ingestion import load_pdf
from .models import Chunk, DocumentPage
from .store import FILTER_COLUMNS, PgVectorStore

STARTER = Path(__file__).resolve().parents[1]
ROOT = STARTER.parent
PDF_PATH = ROOT / "data" / "anatomy-and-physiology-2e_70pages.pdf"
MANIFEST_PATH = ROOT / "data" / "manifest.json"
QUESTIONS_PATH = ROOT / "benchmark" / "questions.json"
RESULTS = STARTER / "results"
DEFAULT_MODEL = "qwen3-embedding:4b"
TOP_K = 3
COHERENCE_POSITIONS = 10

# A vs B changes only the chunking (fixed windows vs section-aware, same 500-char budget);
# B vs C changes only the filter: C searches B's stored section chunks with a question's filter.
STRATEGIES = {
    "A": {"chunking": "fixed_size", "size": 500, "overlap": 50, "index": "A", "use_filter": False},
    "B": {"chunking": "by_section", "max_size": 500, "index": "B", "use_filter": False},
    "C": {"chunking": "by_section", "max_size": 500, "index": "B", "use_filter": True},
}


def build_chunks(name: str, pages: list[DocumentPage]) -> list[Chunk]:
    """Chunk the pages with the strategy's settings; prefix IDs with the strategy name."""
    config = STRATEGIES[name]
    if config["chunking"] == "fixed_size":
        chunks = [c for page in pages for c in fixed_size(page, config["size"], config["overlap"])]
    else:
        chunks = by_section(pages, config["max_size"])
    return [replace(c, chunk_id=f"{name}:{c.chunk_id}") for c in chunks]


def package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not installed"


REQUIRED_QUESTION_FIELDS = ("id", "split", "question", "expected_answer", "gold_source_id",
                            "gold_page", "evidence_quote")


def read_json(path: Path):
    """Load an input JSON file, or stop with a message naming the file and the problem."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Missing input file: {path}")
    except json.JSONDecodeError as error:
        raise SystemExit(f"{path.name} is not valid JSON: line {error.lineno}, column {error.colno}: {error.msg}")


def check_corpus(pages: list[DocumentPage], counted: set[int]) -> list[DocumentPage]:
    """Keep only the pages the manifest counts as content; require at least 30."""
    kept = [p for p in pages if p.page in counted]
    missing = counted - {p.page for p in kept}
    if missing:
        raise SystemExit(f"Manifest counts pages that could not be loaded: {sorted(missing)}")
    if len(kept) < 30:
        raise SystemExit(f"Only {len(kept)} content pages; the lab needs at least 30.")
    return kept


def check_benchmark(questions: list[dict], pages: list[DocumentPage]) -> None:
    """Fail loudly if the benchmark breaks the lab rules or an evidence quote is not on its page."""
    if not isinstance(questions, list):
        raise SystemExit("questions.json must contain a list of questions.")
    malformed = []
    for i, q in enumerate(questions):
        missing = [f for f in REQUIRED_QUESTION_FIELDS if not isinstance(q, dict) or f not in q]
        if missing:
            malformed.append(f"question #{i + 1} ({q.get('id', '?') if isinstance(q, dict) else '?'}): missing {missing}")
        elif not isinstance(q["gold_page"], int):
            malformed.append(f"{q['id']}: gold_page must be a whole number")
        elif q.get("filter") and (not isinstance(q["filter"], dict) or set(q["filter"]) - FILTER_COLUMNS):
            malformed.append(f"{q['id']}: filter may only use {sorted(FILTER_COLUMNS)}")
    ids = [q["id"] for q in questions if isinstance(q, dict) and "id" in q]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        malformed.append(f"duplicate ids: {duplicates}")
    if malformed:
        raise SystemExit("Malformed benchmark:\n  " + "\n  ".join(malformed))

    splits = [q["split"] for q in questions]
    filtered = [q for q in questions if q.get("filter")]
    errors = []
    if len(questions) < 20:
        errors.append(f"{len(questions)} questions (need >= 20)")
    if splits.count("dev") < 15 or splits.count("test") < 5:
        errors.append(f"{splits.count('dev')} dev / {splits.count('test')} test (need >= 15 / >= 5)")
    if len(filtered) < 3 or not any(q["split"] == "test" for q in filtered):
        errors.append("need >= 3 filter questions with >= 1 in test")
    text_by_page = {p.page: flat(p.text) for p in pages}
    for q in questions:
        if q["split"] not in ("dev", "test"):
            errors.append(f"{q['id']}: split must be dev or test")
        page_text = text_by_page.get(q["gold_page"])
        if page_text is None:
            errors.append(f"{q['id']}: gold_page {q['gold_page']} is not a counted page")
        elif flat(q["evidence_quote"]) not in page_text:
            errors.append(f"{q['id']}: evidence_quote not found on page {q['gold_page']}")
    if errors:
        raise SystemExit("Benchmark problems:\n  " + "\n  ".join(errors))


def length_stats(chunks: list[Chunk]) -> dict:
    lengths = [len(c.text) for c in chunks]
    return {
        "chunks": len(chunks),
        "total_chars": sum(lengths),
        "min_chars": min(lengths),
        "median_chars": statistics.median(lengths),
        "mean_chars": round(statistics.mean(lengths), 1),
        "max_chars": max(lengths),
    }


def ingest(store: PgVectorStore, embedder: MyEmbedder, pages: list[DocumentPage]) -> dict:
    """Chunk, embed and upsert each stored index once; record sizes, timings and row counts."""
    stats = {}
    for name in sorted({config["index"] for config in STRATEGIES.values()}):
        t0 = time.perf_counter()
        chunks = build_chunks(name, pages)
        t1 = time.perf_counter()
        vectors = embedder.embed_documents([c.text for c in chunks])
        t2 = time.perf_counter()
        rows_before = store.count(name)
        store.upsert(name, chunks, vectors)
        rows_after = store.count(name)
        t3 = time.perf_counter()
        if rows_after != len(chunks):
            raise SystemExit(f"Index {name}: {rows_after} rows stored for {len(chunks)} chunks (duplicates or stale rows).")
        stats[name] = {
            **length_stats(chunks),
            "chunk_seconds": round(t1 - t0, 3),
            "embed_seconds": round(t2 - t1, 3),
            "upsert_seconds": round(t3 - t2, 3),
            "rows_before_upsert": rows_before,
            "rows_after_upsert": rows_after,
        }
        print(f"Index {name}: {len(chunks)} chunks, embedded in {t2 - t1:.1f}s, rows {rows_before} -> {rows_after}")
    return stats


def retrieve(store: PgVectorStore, embedder: MyEmbedder, questions: list[dict]) -> list[dict]:
    """Run every question against every strategy and keep a full top-k trace."""
    query_vectors = {}
    for q in questions:
        t0 = time.perf_counter()
        query_vectors[q["id"]] = (embedder.embed_query(q["question"]), time.perf_counter() - t0)

    traces = []
    for name, config in STRATEGIES.items():
        for q in questions:
            vector, embed_seconds = query_vectors[q["id"]]
            filters = q.get("filter") if config["use_filter"] else None
            t0 = time.perf_counter()
            hits = store.search(config["index"], vector, top_k=TOP_K, filters=filters or None)
            search_seconds = time.perf_counter() - t0
            traces.append({
                "strategy": name,
                "split": q["split"],
                "question_id": q["id"],
                "question": q["question"],
                "filter_applied": filters or None,
                "hits": hits,
                "query_embed_seconds": round(embed_seconds, 4),
                "search_seconds": round(search_seconds, 4),
                **evaluate_query(q, hits),
            })
    return traces


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def coherence_template(pages: list[DocumentPage]) -> list[dict]:
    """Fixed positions chosen before any scoring: the middle of 10 evenly spaced counted pages."""
    step = len(pages) / COHERENCE_POSITIONS
    chosen = [pages[int(i * step)] for i in range(COHERENCE_POSITIONS)]
    indexes = {config["index"]: build_chunks(config["index"], pages) for config in STRATEGIES.values()}
    rows = []
    for n, page in enumerate(chosen, start=1):
        page_text = flat(page.text)
        position = len(page_text) // 2
        snippet = page_text[position:position + 40]
        for name, config in STRATEGIES.items():  # C searches B's stored chunks
            covering = [c for c in indexes[config["index"]]
                        if c.page <= page.page <= c.metadata.get("page_end", c.page)]
            # the chunk holding the text at the position; a snippet cut by a chunk edge falls back to its start
            chunk = (next((c for c in covering if snippet in flat(c.text)), None)
                     or next((c for c in covering if snippet[:15] in flat(c.text)), covering[0]))
            rows.append({
                "position_id": f"pos{n:02d}", "page": page.page, "char_offset": position,
                "strategy": name, "chunk_id": chunk.chunk_id, "chunk_text": chunk.text,
                "score_0_2": "", "reason": "",
            })
    return rows


def audit_templates(traces: list[dict]) -> tuple[list[dict], list[dict]]:
    """Blank rows for the manual metadata and grounding checks on the test split."""
    metadata_rows, grounding_rows = [], []
    for t in traces:
        if t["split"] != "test":
            continue
        hits = t["hits"]
        for rank, hit in enumerate(hits, start=1):
            metadata_rows.append({
                "question_id": t["question_id"], "strategy": t["strategy"], "rank": rank,
                "chunk_id": hit["chunk_id"], "source": hit["source"],
                "page": hit["page"], "page_end": hit["page_end"], "chapter": hit["chapter"],
                "section": hit["section"],
                "filter_applied": json.dumps(t["filter_applied"]),
                "source_ok": "", "page_ok": "", "chapter_ok": "", "filter_ok": "", "note": "",
            })
        grounding_rows.append({
            "question_id": t["question_id"], "strategy": t["strategy"],
            "top3_pages": ", ".join(f"{h['page']}-{h['page_end']}" if h["page_end"] != h["page"] else str(h["page"])
                                    for h in hits),
            "top3_text": "\n---\n".join(h["text"] for h in hits),
            "score_0_2": "", "reason": "",
        })
    return metadata_rows, grounding_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Day 06 ingestion and retrieval benchmark")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev",
                        help="which questions to run (choose the strategy on dev before running test)")
    args = parser.parse_args()
    try:
        run_pipeline(args.split)
    except RuntimeError as error:  # Ollama / database problems raised with a readable message
        raise SystemExit(f"Error: {error}")
    except psycopg.Error as error:
        raise SystemExit(f"Database error ({type(error).__name__}): {error}")


def run_pipeline(split: str) -> None:
    load_dotenv(STARTER / ".env")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL missing: copy starter/.env.example to starter/.env.")
    model_name = os.getenv("EMBEDDING_MODEL") or DEFAULT_MODEL
    RESULTS.mkdir(exist_ok=True)
    started = datetime.now(timezone.utc)

    # 1. Corpus and benchmark
    manifest = read_json(MANIFEST_PATH)
    questions = read_json(QUESTIONS_PATH)
    if not PDF_PATH.is_file():
        raise SystemExit(f"Missing corpus PDF: {PDF_PATH}")
    try:
        source_id = manifest["source_id"]
        counted = {p["page"] for ch in manifest["chapters"] for p in ch["counted_pages"]}
    except (KeyError, TypeError) as error:
        raise SystemExit(f"manifest.json is missing or has a wrong field: {error}")
    try:
        all_pages, problems = load_pdf(PDF_PATH, source_id, PDF_PATH.name)
    except PdfReadError as error:
        raise SystemExit(f"Cannot read {PDF_PATH.name}: {error}")
    pages = check_corpus(all_pages, counted)
    check_benchmark(questions, pages)
    run_questions = [q for q in questions if split == "all" or q["split"] == split]
    print(f"Loaded {len(pages)} content pages of {len(all_pages)}; running {len(run_questions)} {split} questions")

    # 2-3. Chunk, embed, store (idempotent upsert: re-running must not add rows)
    embedder = MyEmbedder(model_name)
    store = PgVectorStore(database_url, embedder.dimensions)
    store.create_schema()
    index_stats = ingest(store, embedder, pages)

    # 4. Retrieve top-k for every strategy and question, keep full traces
    traces = retrieve(store, embedder, run_questions)
    with (RESULTS / f"traces_{split}.jsonl").open("w", encoding="utf-8") as f:
        for trace in traces:
            f.write(json.dumps(trace, ensure_ascii=False) + "\n")

    # 5. Metrics, run record and blank templates for the manual checks
    summary = {
        "run_started_utc": started.isoformat(timespec="seconds"),
        "split": split,
        "questions": len(run_questions),
        "embedding": {"provider": "ollama (local)", "model": embedder.model_name,
                      "dimensions": embedder.dimensions, "cost_usd": 0},
        "vector_store": "PostgreSQL + pgvector, cosine distance (<=>), exact search",
        "strategies": STRATEGIES,
        "index_stats": index_stats,
        "metrics": summarize(traces),
        "environment": {"python": platform.python_version(),
                        **{pkg: package_version(pkg) for pkg in ("pypdf", "psycopg", "ollama")}},
    }
    # All output files are written together at the end, so a failed run leaves no mix of old and new.
    (RESULTS / "ingestion_log.json").write_text(json.dumps({
        "pdf": PDF_PATH.name,
        "physical_pages": len(all_pages),
        "content_pages": len(pages),
        "content_chars": sum(len(p.text) for p in pages),
        "excluded_pages": sorted({p.page for p in all_pages} - {p.page for p in pages}),
        "problems": problems,
        "pages": [{"page": p.page, "chapter": p.metadata.get("chapter"), "chars": len(p.text)} for p in pages],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    (RESULTS / f"summary_{split}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(RESULTS / "coherence_template.csv", coherence_template(pages))
    metadata_rows, grounding_rows = audit_templates(traces)
    write_csv(RESULTS / "metadata_audit_template.csv", metadata_rows)
    write_csv(RESULTS / "grounding_template.csv", grounding_rows)

    print(json.dumps(summary["metrics"], indent=2, ensure_ascii=False))
    print(f"Results written to {RESULTS}")


if __name__ == "__main__":
    main()
