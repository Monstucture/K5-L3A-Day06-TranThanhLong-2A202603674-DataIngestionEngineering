"""Store and search chunk vectors in PostgreSQL + pgvector."""
from typing import Any

import psycopg

from .models import Chunk

TABLE = "chunks"
# Only these metadata columns may be used as filters; values are always passed as SQL parameters.
FILTER_COLUMNS = {"chapter", "section"}


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


class PgVectorStore:
    """One table for every strategy; (strategy, chunk_id) is the primary key.

    Search is exact (no ANN index): pgvector indexes stop at 2000 dimensions and the
    corpus is small, so a full cosine scan is fast enough and has no recall loss.
    """

    def __init__(self, database_url: str, dimensions: int) -> None:
        if dimensions <= 0:
            raise ValueError(f"dimensions must be positive, got {dimensions}")
        self.dimensions = dimensions
        try:
            # autocommit: reads don't open a hidden transaction, and each `transaction()` block commits for real.
            self._conn = psycopg.connect(database_url, connect_timeout=5, autocommit=True)
        except psycopg.OperationalError as error:
            # The URL holds the password, so it is not repeated in the message.
            raise RuntimeError(
                "Cannot connect to PostgreSQL. Start Docker Desktop, run "
                "`docker compose -p day6_student_starter up -d --wait` in starter/, "
                f"and check DATABASE_URL in starter/.env. ({type(error).__name__})") from error

    def create_schema(self) -> None:
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    strategy      TEXT NOT NULL,
                    chunk_id      TEXT NOT NULL,
                    document_id   TEXT NOT NULL,
                    source        TEXT NOT NULL,
                    page          INT  NOT NULL,
                    page_end      INT  NOT NULL,
                    chapter       INT,
                    chapter_title TEXT,
                    section       TEXT,
                    section_title TEXT,
                    char_start    INT,
                    char_end      INT,
                    text          TEXT NOT NULL,
                    content_type  TEXT NOT NULL DEFAULT 'text',
                    embedding     vector({self.dimensions}) NOT NULL,
                    PRIMARY KEY (strategy, chunk_id)
                )""")
            # Tables created before section chunking / OCR existed get the new columns added in place.
            cur.execute(f"""ALTER TABLE {TABLE}
                            ADD COLUMN IF NOT EXISTS page_end INT,
                            ADD COLUMN IF NOT EXISTS section TEXT,
                            ADD COLUMN IF NOT EXISTS section_title TEXT,
                            ADD COLUMN IF NOT EXISTS content_type TEXT NOT NULL DEFAULT 'text'""")
            cur.execute(f"UPDATE {TABLE} SET page_end = page WHERE page_end IS NULL")
            cur.execute("""SELECT atttypmod FROM pg_attribute
                           WHERE attrelid = %s::regclass AND attname = 'embedding'""", (TABLE,))
            stored = cur.fetchone()[0]
        if stored != self.dimensions:
            raise RuntimeError(f"Table {TABLE} stores vector({stored}) but the model gives {self.dimensions} "
                               f"dimensions. Drop the table (DROP TABLE {TABLE}) and run again.")

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        wrong = [c.chunk_id for c, v in zip(chunks, vectors) if len(v) != self.dimensions]
        if wrong:
            raise ValueError(f"vectors without {self.dimensions} dimensions: {wrong[:5]}")
        if len({c.chunk_id for c in chunks}) != len(chunks):
            raise ValueError("duplicate chunk_id values in one upsert")

        rows = [(strategy, c.chunk_id, c.document_id, c.source, c.page, c.metadata.get("page_end", c.page),
                 c.metadata.get("chapter"), c.metadata.get("chapter_title"), c.metadata.get("section"),
                 c.metadata.get("section_title"), c.metadata.get("char_start"), c.metadata.get("char_end"),
                 c.text, c.metadata.get("content_type", "text"), _vector_literal(v)) for c, v in zip(chunks, vectors)]
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.executemany(f"""
                INSERT INTO {TABLE} (strategy, chunk_id, document_id, source, page, page_end, chapter, chapter_title,
                                     section, section_title, char_start, char_end, text, content_type, embedding)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector)
                ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                    document_id = EXCLUDED.document_id, source = EXCLUDED.source, page = EXCLUDED.page,
                    page_end = EXCLUDED.page_end, chapter = EXCLUDED.chapter,
                    chapter_title = EXCLUDED.chapter_title, section = EXCLUDED.section,
                    section_title = EXCLUDED.section_title,
                    char_start = EXCLUDED.char_start, char_end = EXCLUDED.char_end,
                    text = EXCLUDED.text, content_type = EXCLUDED.content_type,
                    embedding = EXCLUDED.embedding""", rows)
            # A strategy's index holds exactly this chunk set: drop rows from changed or replaced documents.
            cur.execute(f"DELETE FROM {TABLE} WHERE strategy = %s AND NOT (chunk_id = ANY(%s))",
                        (strategy, [c.chunk_id for c in chunks]))

    def count(self, strategy: str) -> int:
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {TABLE} WHERE strategy = %s", (strategy,))
            return cur.fetchone()[0]

    def page_chunks(self, strategy: str, page: int) -> list[dict[str, Any]]:
        """Stored chunks that cover `page`, in reading order (used by the demo's chunking view)."""
        with self._conn.cursor() as cur:
            cur.execute(f"""
                SELECT chunk_id, page, page_end, chapter, section, section_title, char_start, text, content_type
                FROM {TABLE} WHERE strategy = %s AND page <= %s AND page_end >= %s
                ORDER BY page, char_start, chunk_id""", (strategy, page, page))
            columns = [d.name for d in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if len(query_vector) != self.dimensions:
            raise ValueError(f"query vector has {len(query_vector)} dimensions, expected {self.dimensions}")
        filters = filters or {}
        unknown = set(filters) - FILTER_COLUMNS
        if unknown:
            raise ValueError(f"unsupported filter keys: {sorted(unknown)}")

        where = ["strategy = %s"]
        params: list[Any] = [strategy]
        for column in sorted(filters):  # column names come from the allow-list above
            where.append(f"{column} = %s")
            params.append(filters[column])
        vector = _vector_literal(query_vector)
        with self._conn.cursor() as cur:
            cur.execute(f"""
                SELECT chunk_id, document_id, source, page, page_end, chapter, chapter_title, section,
                       section_title, char_start, char_end, text, content_type,
                       1 - (embedding <=> %s::vector) AS score
                FROM {TABLE}
                WHERE {' AND '.join(where)}
                ORDER BY embedding <=> %s::vector
                LIMIT %s""", [vector, *params, vector, top_k])
            columns = [d.name for d in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
