from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    # -------------------------
    # Paths
    # -------------------------
    workspace_path: str | None = None
    knowledge_base_dir: str = "knowledge_base"

    # -------------------------
    # OpenAI / Chat
    # -------------------------
    chat_model: str = "gpt-5.2"
    openai_api_key: str | None = None

    # -------------------------
    # Embeddings (LOCAL MiniLM)
    # -------------------------
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_device: str = "cpu"          # "cpu" or "cuda"
    embedding_batch_size: int = 32
    embedding_enrichment_enabled: bool = False
    embedding_enrichment_kind: str = "knowledge"

    # -------------------------
    # Memory / FAISS
    # -------------------------
    memory_top_k: int = 10                 # ← FIXES YOUR ERROR
    memory_core_top_k: int = 15
    memory_min_score: float = 0.0          # optional, future-safe

    # -------------------------
    # Chunking
    # -------------------------
    chunk_size: int = 3000
    chunk_overlap: int = 100

    # -------------------------
    # Limits
    # -------------------------
    max_file_mb: int = 10

    # -------------------------
    # Factory / helpers
    # -------------------------
    @classmethod
    def load(cls) -> "AppConfig":
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY"),
        )

    def with_workspace(self, path: str) -> "AppConfig":
        return replace(self, workspace_path=path)

    def knowledge_base_path(self) -> Path:
        return Path(self.knowledge_base_dir)
