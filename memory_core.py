from __future__ import annotations

import json
from pathlib import Path
from typing import List


class MemoryCore:
    """
    Long-term semantic memory extracted from chat.
    Stores distilled facts, preferences, goals.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> List[str]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def save(self, memories: List[str]) -> None:
        self.path.write_text(
            json.dumps(memories, indent=2),
            encoding="utf-8",
        )

    def add(self, entries: List[str]) -> None:
        existing = self.load()
        merged = list(dict.fromkeys(existing + entries))
        self.save(merged)

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
