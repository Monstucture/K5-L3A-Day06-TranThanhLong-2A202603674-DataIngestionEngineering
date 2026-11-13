"""Local demo: ask the OpenStax RAG index a question and watch each step.

Run from starter/ (venv active, Docker + Ollama running, `python -m src.run` done once):
    python -m demo.server
then open http://127.0.0.1:8000

Retrieval always uses the stored qwen3-embedding vectors. The answer is written by a local
Ollama model or by OpenRouter (key read from starter/.env, never sent to the browser), and
only from the retrieved sentences.
"""
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import ollama
import pymupdf
from dotenv import load_dotenv

from src.chunking import _SENTENCE_SPLIT
from src.embeddings import MyEmbedder
from src.evaluation import flat
from src.run import DEFAULT_MODEL, MANIFEST_PATH, PDF_PATH, QUESTIONS_PATH, STARTER, STRATEGIES, read_json
from src.ingestion import load_pdf
from src.store import PgVectorStore

HOST, PORT = "127.0.0.1", 8000  # localhost only
TOP_K = 3
TOP_SENTENCES = 4  # sentences marked "relevant" by embedding similarity
LOCAL_LLM = "llama3.2:3b"
API_LLM = "openai/gpt-4o-mini"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
NO_ANSWER = "The retrieved text does not contain the answer."
MAX_ANSWER_TOKENS = 400  # about 4 sentences with citations
INDEX_HTML = Path(__file__).with_name("index.html")

SYSTEM_PROMPT = f"""You answer questions about an anatomy and physiology textbook.
Use ONLY the numbered sentences you are given. Do not add facts from your own knowledge.
Cite every sentence you rely on with its tag, e.g. [S3]. Answer in at most 4 sentences.
If the sentences do not contain the answer, reply exactly: {NO_ANSWER}"""

load_dotenv(STARTER / ".env")
STATE: dict = {}
LOCK = threading.Lock()  # one Postgres connection and one Ollama client, shared: serialize requests


def startup() -> None:
    manifest = read_json(MANIFEST_PATH)
    counted = {p["page"] for ch in manifest["chapters"] for p in ch["counted_pages"]}
    pages, _ = load_pdf(PDF_PATH, manifest["source_id"], PDF_PATH.name)
    embedder = MyEmbedder(os.getenv("EMBEDDING_MODEL") or DEFAULT_MODEL)
    store = PgVectorStore(os.environ["DATABASE_URL"], embedder.dimensions)
    if store.count("A") == 0 or store.count("B") == 0:
        raise SystemExit("The index is empty. Run `python -m src.run --split dev` once first.")
    questions = read_json(QUESTIONS_PATH)
    STATE.update(
        embedder=embedder, store=store, pdf=pymupdf.open(PDF_PATH), png_cache={},
        pages={p.page: p for p in pages if p.page in counted},
        # dev questions only, so the demo never becomes a way of looking at the test set
        examples=[q for q in questions if q["split"] == "dev"],
        api_ready=bool(os.getenv("OPENROUTER_API_KEY")),
    )


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(flat(text)) if len(s) >= 20]


def stream_local(messages: list[dict]):
    for part in ollama.Client().chat(model=LOCAL_LLM, messages=messages, stream=True,
                                     options={"num_predict": MAX_ANSWER_TOKENS, "temperature": 0}):
        yield part.message.content


def stream_openrouter(messages: list[dict]):
    request = urllib.request.Request(
        OPENROUTER_URL,
        # max_tokens: without it OpenRouter reserves the model's full output limit against your credits
        data=json.dumps({"model": API_LLM, "messages": messages, "stream": True, "temperature": 0,
                         "max_tokens": MAX_ANSWER_TOKENS}).encode(),
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                 "Content-Type": "application/json"},
    )
    try:
        response = urllib.request.urlopen(request, timeout=60)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"OpenRouter returned HTTP {error.code}: {error.read().decode(errors='replace')[:200]}")
    with response:
        for raw in response:
            line = raw.decode().strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            delta = json.loads(line[6:])["choices"][0]["delta"].get("content")
            if delta:
                yield delta


def ask(params: dict, send) -> None:
    question = params.get("q", "").strip()
    strategy = params.get("strategy", "B")
    model = params.get("model", "local")
    if not question or strategy not in STRATEGIES or model not in ("local", "api"):
        raise ValueError("Need a question, strategy A/B/C and model local/api.")
    if model == "api" and not STATE["api_ready"]:
        raise ValueError("OPENROUTER_API_KEY is not set in starter/.env.")
    config = STRATEGIES[strategy]
    chapter = params.get("chapter")
    filters = {"chapter": int(chapter)} if config["use_filter"] and chapter else None
    embedder, store = STATE["embedder"], STATE["store"]

    def step(name: str, status: str, detail: str = "", started: float | None = None) -> None:
        ms = round((time.perf_counter() - started) * 1000) if started else None
        send("step", {"name": name, "status": status, "detail": detail, "ms": ms})

    t = time.perf_counter(); step("embed", "running", "qwen3-embedding turns the question into 2560 numbers")
    query_vector = embedder.embed_query(question)
    step("embed", "done", f"{len(query_vector)}-dimension vector", t)

    t = time.perf_counter()
    where = f"index {config['index']}" + (f", filter chapter = {filters['chapter']}" if filters else ", no filter")
    step("search", "running", f"cosine search in pgvector ({where})")
    hits = store.search(config["index"], query_vector, TOP_K, filters)
    send("hits", [{k: (round(v, 4) if k == "score" else v) for k, v in h.items()
                   if k in ("chunk_id", "page", "page_end", "chapter", "section", "section_title", "score", "text")}
                  for h in hits])
    step("search", "done", f"top {len(hits)} of strategy {strategy}", t)

    t = time.perf_counter(); step("extract", "running", "scoring every retrieved sentence against the question")
    sentences = [{"id": f"S{n}", "hit": i, "text": s}
                 for n, (i, s) in enumerate(((i, s) for i, h in enumerate(hits) for s in split_sentences(h["text"])), 1)]
    for s, vector in zip(sentences, embedder.embed_documents([s["text"] for s in sentences]) if sentences else []):
        s["score"] = round(cosine(query_vector, vector), 4)
    relevant = {s["id"] for s in sorted(sentences, key=lambda s: -s["score"])[:TOP_SENTENCES]}
    for s in sentences:
        s["relevant"] = s["id"] in relevant
    send("sentences", sentences)
    step("extract", "done", f"{len(relevant)} most relevant of {len(sentences)} sentences", t)

    gold = next((q for q in STATE["examples"] if q["id"] == params.get("qid")), None)
    if gold:
        send("gold", {"page": gold["gold_page"], "quote": gold["evidence_quote"]})

    t = time.perf_counter()
    llm = LOCAL_LLM if model == "local" else API_LLM
    step("answer", "running", f"{llm} writes an answer from the retrieved sentences only")
    listing = "\n".join(f"[{s['id']}]{' (most relevant)' if s['relevant'] else ''} {s['text']}" for s in sentences)
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Sentences:\n{listing}\n\nQuestion: {question}"}]
    answer = ""
    for token in (stream_local if model == "local" else stream_openrouter)(messages):
        answer += token
        send("token", token)
    known = {s["id"] for s in sentences}
    cited = sorted({c for c in re.findall(r"S\d+", answer) if c in known}, key=lambda c: int(c[1:]))
    send("answer", {"text": answer, "cited": cited, "model": llm})
    step("answer", "done", f"cites {', '.join(cited) or 'nothing'}", t)


def chunk_view(params: dict) -> dict:
    strategy = params.get("strategy", "A")
    page = int(params.get("page", 0))
    if strategy not in STRATEGIES or page not in STATE["pages"]:
        raise ValueError("Unknown strategy or page.")
    config = STRATEGIES[strategy]
    chunks = STATE["store"].page_chunks(config["index"], page)
    doc_page = STATE["pages"][page]
    return {"strategy": strategy, "config": config, "page": page, "chapter": doc_page.metadata.get("chapter"),
            "page_text": flat(doc_page.text), "chunks": chunks}


PAGE_ZOOM = 2  # render at 144 dpi so text stays sharp when scaled to the panel


def pdf_page(number: int):
    if number not in STATE["pages"]:
        raise ValueError(f"Page {number} is not a content page.")
    return STATE["pdf"][number - 1]


def page_png(number: int) -> bytes:
    if number not in STATE["png_cache"]:
        STATE["png_cache"][number] = pdf_page(number).get_pixmap(matrix=pymupdf.Matrix(PAGE_ZOOM, PAGE_ZOOM)).tobytes("png")
    return STATE["png_cache"][number]


def find_boxes(page, text: str) -> list:
    """Rectangles of `text` on the page; long or oddly broken text is searched in 6-word pieces."""
    rects = page.search_for(text)
    if rects:
        return rects
    words = text.split()
    return [r for i in range(0, len(words), 6) for r in page.search_for(" ".join(words[i:i + 6]))]


def page_marks(body: dict) -> dict:
    """Boxes for each requested mark ({"text", "kind", "id"}) on one page, in page units."""
    page = pdf_page(int(body.get("page", 0)))
    rects = []
    for mark in body.get("marks", [])[:60]:
        for r in find_boxes(page, flat(str(mark.get("text", ""))))[:40]:
            rects.append({"kind": mark.get("kind"), "id": mark.get("id"),
                          "x0": r.x0, "y0": r.y0, "x1": r.x1, "y1": r.y1})
    return {"width": page.rect.width, "height": page.rect.height, "rects": rects}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # keep the terminal quiet
        pass

    def send_json(self, body: object, status: int = 200) -> None:
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path == "/":
                data = INDEX_HTML.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif url.path == "/api/config":
                self.send_json({
                    "strategies": STRATEGIES,
                    "pages": [{"page": p.page, "chapter": p.metadata.get("chapter")} for p in STATE["pages"].values()],
                    "examples": [{"id": q["id"], "question": q["question"], "type": q.get("type"),
                                  "filter": q.get("filter")} for q in STATE["examples"]],
                    "models": {"local": LOCAL_LLM, "api": API_LLM if STATE["api_ready"] else None},
                })
            elif url.path == "/api/chunks":
                with LOCK:
                    self.send_json(chunk_view(params))
            elif url.path == "/api/ask":
                self.stream(params)
            elif url.path == "/api/page.png":
                with LOCK:
                    data = page_png(int(params.get("page", 0)))
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=3600")
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_json({"error": "not found"}, 404)
        except ValueError as error:
            self.send_json({"error": str(error)}, 400)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/marks":
            self.send_json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 200_000:
                raise ValueError("Request too large.")
            body = json.loads(self.rfile.read(length) or b"{}")
            with LOCK:
                self.send_json(page_marks(body))
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json({"error": str(error)}, 400)

    def stream(self, params: dict) -> None:
        """Server-sent events: the page receives each step as it happens."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def send(event: str, data: object) -> None:
            self.wfile.write(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode())
            self.wfile.flush()

        try:
            with LOCK:
                ask(params, send)
        except (BrokenPipeError, ConnectionResetError):
            return  # the browser closed the page
        except Exception as error:  # report any failure to the page instead of a silent hang
            send("fail", {"message": f"{type(error).__name__}: {error}"})
        send("end", {})


def main() -> None:
    print("Loading pages, embedding model and database ...")
    try:
        startup()
    except RuntimeError as error:
        raise SystemExit(f"Error: {error}")
    print(f"Demo ready: http://{HOST}:{PORT}  (Ctrl+C to stop)")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
