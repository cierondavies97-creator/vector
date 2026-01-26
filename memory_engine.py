"""Vector memory engine using sentence-transformers and FAISS."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import faiss
from sentence_transformers import SentenceTransformer

from config import AppConfig


@dataclass(frozen=True)
class MemoryChunk:
    text: str
    source_path: str


@dataclass(frozen=True)
class TokenStats:
    input_tokens: int
    output_tokens: int
    estimated_cost: float


class MemoryEngine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.model = SentenceTransformer(config.embedding_model)
        self.index = None
        self.metadata: list[MemoryChunk] = []
        self._rotation_offset = 0

    def _chunk_text(self, text: str) -> list[str]:
        tokens = text.split()
        chunks = []
        start = 0
        while start < len(tokens):
            end = min(start + self.config.chunk_size, len(tokens))
            chunk = " ".join(tokens[start:end])
            chunks.append(chunk)
            start = end - self.config.chunk_overlap
            if start < 0:
                start = 0
        return chunks

    def build_index(self, files: dict[str, str]) -> None:
        chunks: list[MemoryChunk] = []
        for path, content in files.items():
            for chunk in self._chunk_text(content):
                if chunk.strip():
                    chunks.append(MemoryChunk(text=chunk, source_path=path))

        if not chunks:
            self.index = None
            self.metadata = []
            return

        embeddings = self.model.encode([chunk.text for chunk in chunks])
        dimension = embeddings.shape[1]
        index = faiss.IndexFlatL2(dimension)
        index.add(embeddings)
        self.index = index
        self.metadata = chunks
        self._rotation_offset = 0

        self._persist_index()

    def _persist_index(self) -> None:
        index_dir = self.config.index_path()
        index_dir.mkdir(parents=True, exist_ok=True)
        if self.index is None:
            return
        faiss.write_index(self.index, str(index_dir / "faiss.index"))
        metadata_path = index_dir / "metadata.txt"
        lines = [f"{chunk.source_path}\t{chunk.text}\n" for chunk in self.metadata]
        metadata_path.write_text("".join(lines), encoding="utf-8")

    def load_index(self) -> None:
        index_dir = self.config.index_path()
        index_path = index_dir / "faiss.index"
        metadata_path = index_dir / "metadata.txt"
        if not index_path.exists() or not metadata_path.exists():
            return
        self.index = faiss.read_index(str(index_path))
        metadata_lines = metadata_path.read_text(encoding="utf-8").splitlines()
        self.metadata = []
        for line in metadata_lines:
            if not line.strip():
                continue
            source_path, text = line.split("\t", 1)
            self.metadata.append(MemoryChunk(text=text, source_path=source_path))

    def query(self, text: str, top_k: int) -> list[MemoryChunk]:
        if self.index is None:
            return []
        embedding = self.model.encode([text])
        distances, indices = self.index.search(embedding, top_k)
        results = []
        for idx in indices[0]:
            if idx < 0 or idx >= len(self.metadata):
                continue
            results.append(self.metadata[idx])
        if not results:
            return []
        rotation = self._rotation_offset % len(results)
        return results[rotation:] + results[:rotation]

    def rotate_memory(self) -> None:
        self._rotation_offset += 1

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text.split()))

    def token_stats(self, input_text: str, output_text: str) -> TokenStats:
        input_tokens = self.estimate_tokens(input_text)
        output_tokens = self.estimate_tokens(output_text)
        cost = (
            input_tokens * self.config.token_cost_input
            + output_tokens * self.config.token_cost_output
        )
        return TokenStats(
            input_tokens=input_tokens, output_tokens=output_tokens, estimated_cost=cost
        )

    def iter_chunks(self) -> Iterable[MemoryChunk]:
        return list(self.metadata)
