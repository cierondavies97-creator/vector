"""Assistant orchestration layer for query answering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from openai import OpenAI

from config import AppConfig
from memory_engine import MemoryChunk, MemoryEngine, TokenStats


@dataclass(frozen=True)
class AssistantResponse:
    text: str
    memory: List[MemoryChunk]
    stats: TokenStats


class Assistant:
    def __init__(self, config: AppConfig, memory_engine: MemoryEngine) -> None:
        self.config = config
        self.memory_engine = memory_engine
        self.client = OpenAI()

    def answer(self, query: str, use_memory: bool) -> tuple[str, List[MemoryChunk], TokenStats]:
        memory_chunks = (
            self.memory_engine.query(query, self.config.top_k) if use_memory else []
        )
        memory_text = "\n\n".join(
            [f"Source: {chunk.source_path}\n{chunk.text}" for chunk in memory_chunks]
        )

        system_prompt = (
            "You are Vector, an AI trading assistant that answers questions about the user's "
            "codebase and documents. Use the provided memory context when available, and be clear "
            "about uncertainty."
        )

        user_prompt = query
        if memory_text:
            user_prompt = (
                "Context:\n" + memory_text + "\n\nQuestion:\n" + query
            )

        response = self.client.chat.completions.create(
            model=self.config.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = response.choices[0].message.content or ""
        stats = self.memory_engine.token_stats(user_prompt, text)
        return text, memory_chunks, stats

    def propose_edit(self, content: str, instruction: str) -> str:
        system_prompt = (
            "You are a careful code editor. Apply the user's instruction to the provided file "
            "content. Return the full updated file content only, with no extra commentary."
        )
        user_prompt = f"Instruction:\n{instruction}\n\nFile content:\n{content}"
        response = self.client.chat.completions.create(
            model=self.config.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or ""
