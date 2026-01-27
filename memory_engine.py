from __future__ import annotations

from datetime import datetime
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any

import faiss
from sentence_transformers import SentenceTransformer

from config import AppConfig


# =========================================================
# Data structures
# =========================================================

@dataclass
class MemoryChunk:
    id: str
    text: str
    score: float
    source_path: str
    rank: int | None = None


@dataclass
class RetrievedItem:
    namespace: str               # "file" | "memory_core"
    chunk_id: str
    text: str                    # <-- REQUIRED
    score: float
    source_path: str
    metadata: Dict[str, Any]
    rank: int


@dataclass
class TokenStats:
    input_tokens: int
    output_tokens: int
    estimated_cost: float


@dataclass
class IndexStats:
    embedding_seconds: float
    faiss_seconds: float
    chunk_count: int


# =========================================================
# Memory Engine
# =========================================================

class MemoryEngine:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

        self.model = SentenceTransformer(
            config.embedding_model,
            device=config.embedding_device,
        )

        kb = self.config.knowledge_base_path()

        # ---------- FILE MEMORY ----------
        self.file_index: faiss.Index | None = None
        self.file_ids: list[str] = []

        self.file_dir = kb / "faiss"
        self.file_dir.mkdir(parents=True, exist_ok=True)

        self.file_index_path = self.file_dir / "index.faiss"
        self.file_meta_path = self.file_dir / "meta.json"

        # ---------- MEMORY CORE ----------
        self.core_index: faiss.Index | None = None
        self.core_ids: list[str] = []

        self.core_dir = kb / "memory_core"
        self.core_dir.mkdir(parents=True, exist_ok=True)

        self.core_index_path = self.core_dir / "index.faiss"
        self.core_meta_path = self.core_dir / "meta.json"
        self.core_notes_path = self.core_dir / "notes.json"

        # ---------- INGESTED CHUNKS ----------
        self.chunk_dir = kb / "ingested" / "chunks"

        self._load_file_index()
        self._load_core_index()

    # =====================================================
    # FILE INDEXING
    # =====================================================

    def build_index(
        self,
        documents: dict[str, str],
        *,
        progress_cb=None,
    ) -> IndexStats:
        if not documents:
            return IndexStats(0.0, 0.0, 0)

        texts = list(documents.values())
        ids = list(documents.keys())

        import time
        t0 = time.perf_counter()

        embeddings = self.model.encode(
            texts,
            batch_size=self.config.embedding_batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        embedding_seconds = time.perf_counter() - t0

        dim = embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(embeddings)

        self.file_index = index
        self.file_ids = ids
        self._persist_file_index()

        return IndexStats(
            embedding_seconds=embedding_seconds,
            faiss_seconds=0.0,
            chunk_count=len(ids),
        )

    # =====================================================
    # FILE SEARCH
    # =====================================================

    def search_files(self, query: str, top_k: int) -> List[MemoryChunk]:
        if self.file_index is None:
            return []

        q = self.model.encode(query, normalize_embeddings=True).reshape(1, -1)
        scores, indices = self.file_index.search(q, top_k)

        results: list[MemoryChunk] = []

        for rank, (score, idx) in enumerate(zip(scores[0], indices[0]), start=1):
            if idx < 0:
                continue

            cid = self.file_ids[idx]
            safe = cid.replace(":", "__").replace("/", "__").replace("\\", "__")
            chunk_file = self.chunk_dir / f"{safe}.txt"

            text = (
                chunk_file.read_text(encoding="utf-8", errors="ignore")
                if chunk_file.exists()
                else ""
            )

            source_path = cid.split(":", 1)[0]

            results.append(
                MemoryChunk(
                    id=cid,
                    text=text,
                    score=float(score),
                    source_path=source_path,
                    rank=rank,
                )
            )

        return results

    def debug_search_files(self, query: str, top_k: int) -> List[RetrievedItem]:
        raw = self.search_files(query, top_k)

        out: list[RetrievedItem] = []
        for c in raw:
            safe = c.id.replace(":", "__").replace("/", "__").replace("\\", "__")
            meta_path = self.chunk_dir / f"{safe}.meta.json"

            metadata: Dict[str, Any] = {}
            if meta_path.exists():
                try:
                    metadata = json.loads(meta_path.read_text())
                except Exception:
                    metadata = {}

            # -------- ensure tags --------
            tags = list(metadata.get("tags", []))
            if "namespace:file" not in tags:
                tags.append("namespace:file")
            metadata["tags"] = tags


            out.append(
                RetrievedItem(
                    namespace="file",
                    chunk_id=c.id,
                    text=c.text,
                    score=c.score,
                    source_path=c.source_path,
                    metadata=metadata,
                    rank=c.rank or 0,
                )
            )

        return out


    # =====================================================
    # MEMORY CORE
    # =====================================================

    def load_memory_core_notes(self) -> list[dict]:
        if not self.core_notes_path.exists():
            return []
        return json.loads(self.core_notes_path.read_text())

    def add_memory_core_notes(
        self,
        notes: List[str],
        *,
        source: str = "chat",
    ) -> None:
        if not notes:
            return

        existing = self.load_memory_core_notes()

        for text in notes:
            existing.append(
                {
                    "id": datetime.utcnow().isoformat(),
                    "source": source,
                    "text": text,
                }
            )

        self.core_notes_path.write_text(
            json.dumps(existing, indent=2),
            encoding="utf-8",
        )

        self._reindex_memory_core()

    def _reindex_memory_core(self) -> None:
        notes = self.load_memory_core_notes()
        if not notes:
            return

        texts = [n["text"] for n in notes]
        ids = [n["id"] for n in notes]

        embeddings = self.model.encode(
            texts,
            batch_size=self.config.embedding_batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        dim = embeddings.shape[1]
        index = faiss.IndexFlatIP(dim)
        index.add(embeddings)

        self.core_index = index
        self.core_ids = ids
        self._persist_core_index()

    def debug_search_memory_core(
        self,
        query: str,
        top_k: int = 10,
    ) -> List[RetrievedItem]:
        if self.core_index is None:
            return []

        q = self.model.encode(query, normalize_embeddings=True).reshape(1, -1)
        scores, indices = self.core_index.search(q, top_k)
        notes = self.load_memory_core_notes()

        out: list[RetrievedItem] = []
        for rank, (score, idx) in enumerate(zip(scores[0], indices[0]), start=1):
            if idx < 0:
                continue
            note = notes[idx]

            metadata = {
                "source": note.get("source"),
                "created_at": note["id"],
                "importance": 1.0,
                "tags": [
                    "namespace:memory_core",
                    f"source:{note.get('source', 'unknown')}",
                ],
            }


            out.append(
                RetrievedItem(
                    namespace="memory_core",
                    chunk_id=note["id"],
                    text=note["text"],
                    score=float(score),
                    source_path="memory_core",
                    metadata=metadata,
                    rank=rank,
                )
            )

        return out


    def retrieve_all(
        self,
        *,
        query: str,
        top_k_files: int = 30,
        top_k_core: int = 15,
    ) -> List[RetrievedItem]:
        items: list[RetrievedItem] = []
        items.extend(self.debug_search_files(query, top_k_files))
        items.extend(self.debug_search_memory_core(query, top_k_core))
        return items

    # =====================================================
    # Persistence
    # =====================================================

    def _persist_file_index(self) -> None:
        if self.file_index is None:
            return
        faiss.write_index(self.file_index, str(self.file_index_path))
        self.file_meta_path.write_text(json.dumps(self.file_ids, indent=2))

    def _load_file_index(self):
        if self.file_index_path.exists() and self.file_meta_path.exists():
            self.file_index = faiss.read_index(str(self.file_index_path))
            self.file_ids = json.loads(self.file_meta_path.read_text())

    def _persist_core_index(self) -> None:
        if self.core_index is None:
            return
        faiss.write_index(self.core_index, str(self.core_index_path))
        self.core_meta_path.write_text(json.dumps(self.core_ids, indent=2))

    def _load_core_index(self):
        if self.core_index_path.exists() and self.core_meta_path.exists():
            self.core_index = faiss.read_index(str(self.core_index_path))
            self.core_ids = json.loads(self.core_meta_path.read_text())
