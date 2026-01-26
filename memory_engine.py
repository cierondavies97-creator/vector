"""Vector memory engine using sentence-transformers and FAISS."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import faiss
from sentence_transformers import CrossEncoder, SentenceTransformer

from config import AppConfig


@dataclass(frozen=True)
class MemoryChunk:
    text: str
    source_path: str
    score: float | None = None
    rank: int | None = None


@dataclass(frozen=True)
class TokenStats:
    input_tokens: int
    output_tokens: int
    estimated_cost: float


class MemoryEngine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.model = SentenceTransformer(config.embedding_model)
        self.reranker = (
            CrossEncoder(config.rerank_model) if config.rerank_enabled else None
        )
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

        self._persist_index(files)

    def _persist_index(self, files: dict[str, str]) -> None:
        index_dir = self.config.index_path()
        index_dir.mkdir(parents=True, exist_ok=True)
        if self.index is None:
            return
        faiss.write_index(self.index, str(index_dir / "faiss.index"))
        metadata_path = index_dir / "metadata.txt"
        lines = [f"{chunk.source_path}\t{chunk.text}\n" for chunk in self.metadata]
        metadata_path.write_text("".join(lines), encoding="utf-8")
        self._persist_run_metadata(index_dir, files)

    def _persist_run_metadata(self, index_dir: Path, files: dict[str, str]) -> None:
        from datetime import datetime, timezone
        import json

        run_metadata = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "embedding_model": self.config.embedding_model,
            "rerank_enabled": self.config.rerank_enabled,
            "rerank_model": self.config.rerank_model,
            "rerank_pool_size": self.config.rerank_pool_size,
            "chunk_size": self.config.chunk_size,
            "chunk_overlap": self.config.chunk_overlap,
            "file_count": len(files),
            "chunk_count": len(self.metadata),
            "source_files": sorted(files.keys()),
        }
        metadata_path = index_dir / "index_metadata.json"
        metadata_path.write_text(json.dumps(run_metadata, indent=2), encoding="utf-8")

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
        pool_size = max(top_k, self.config.rerank_pool_size)
        embedding = self.model.encode([text])
        distances, indices = self.index.search(embedding, pool_size)
        candidates = []
        for idx in indices[0]:
            if idx < 0 or idx >= len(self.metadata):
                continue
            candidates.append(self.metadata[idx])
        if not candidates:
            return []

        if self.reranker:
            pairs = [(text, chunk.text) for chunk in candidates]
            rerank_scores = self.reranker.predict(pairs)
            scored = list(zip(candidates, rerank_scores))
            scored.sort(key=lambda item: item[1], reverse=True)
            results = [
                MemoryChunk(
                    text=chunk.text,
                    source_path=chunk.source_path,
                    score=float(score),
                    rank=rank,
                )
                for rank, (chunk, score) in enumerate(scored[:top_k], start=1)
            ]
        else:
            results = []
            for rank, idx in enumerate(indices[0][:top_k], start=1):
                if idx < 0 or idx >= len(self.metadata):
                    continue
                chunk = self.metadata[idx]
                score = float(distances[0][rank - 1])
                results.append(
                    MemoryChunk(
                        text=chunk.text,
                        source_path=chunk.source_path,
                        score=score,
                        rank=rank,
                    )
                )

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
