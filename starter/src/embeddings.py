"""Real embedding provider: a local model served by Ollama."""
from typing import Protocol

import ollama


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


# Qwen3-Embedding is trained with an instruction on the query side only; documents are embedded as-is.
QUERY_INSTRUCTION = "Instruct: Given a question, retrieve passages from a textbook that answer it\nQuery: "
BATCH_SIZE = 16


class MyEmbedder:
    """Embeds with an Ollama model. Errors are raised, never replaced by mock vectors."""

    def __init__(self, model_name: str, host: str | None = None) -> None:
        self.model_name = model_name
        self.query_instruction = QUERY_INSTRUCTION
        self._client = ollama.Client(host=host)
        # One probe call: fails fast if Ollama is down or the model is missing, and reads the dimension.
        self.dimensions = len(self._embed(["dimension probe"])[0])

    def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = self._client.embed(model=self.model_name, input=texts)
        except ConnectionError as error:
            raise RuntimeError("Cannot reach Ollama. Start the Ollama app or run `ollama serve`.") from error
        except ollama.ResponseError as error:
            raise RuntimeError(f"Ollama could not embed with {self.model_name!r}: {error.error}. "
                               f"Try `ollama pull {self.model_name}`.") from error
        vectors = [list(v) for v in response.embeddings]
        if len(vectors) != len(texts):
            raise RuntimeError(f"Ollama returned {len(vectors)} vectors for {len(texts)} texts.")
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), BATCH_SIZE):
            vectors.extend(self._embed(texts[i:i + BATCH_SIZE]))
        bad = [i for i, v in enumerate(vectors) if len(v) != self.dimensions]
        if bad:
            raise RuntimeError(f"Vectors {bad[:5]} do not have {self.dimensions} dimensions.")
        return vectors

    def embed_query(self, question: str) -> list[float]:
        return self._embed([self.query_instruction + question])[0]
