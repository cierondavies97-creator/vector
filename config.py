"""Configuration for the Vector AI Trading Assistant."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    model_name: str = "gpt-4o-mini"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    rerank_enabled: bool = True
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rerank_pool_size: int = 20
    knowledge_base_dir: str = "knowledge_base"
    index_dir: str = "vector_index"
    workspace_path: str | None = None
    top_k: int = 5
    chunk_size: int = 500
    chunk_overlap: int = 50
    test_command: str = "pytest"
    token_cost_input: float = 0.01 / 1000
    token_cost_output: float = 0.03 / 1000

    @staticmethod
    def load() -> "AppConfig":
        return AppConfig()

    def with_workspace(self, workspace_path: str) -> "AppConfig":
        return AppConfig(
            model_name=self.model_name,
            embedding_model=self.embedding_model,
            rerank_enabled=self.rerank_enabled,
            rerank_model=self.rerank_model,
            rerank_pool_size=self.rerank_pool_size,
            knowledge_base_dir=self.knowledge_base_dir,
            index_dir=self.index_dir,
            workspace_path=workspace_path,
            top_k=self.top_k,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            test_command=self.test_command,
            token_cost_input=self.token_cost_input,
            token_cost_output=self.token_cost_output,
        )

    def knowledge_base_path(self) -> Path:
        return Path(self.knowledge_base_dir)

    def index_path(self) -> Path:
        return Path(self.index_dir)
