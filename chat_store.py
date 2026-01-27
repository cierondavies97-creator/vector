from __future__ import annotations

import json
from pathlib import Path
from typing import List, Dict


class ChatStore:
    """
    Persistent chat history store.

    Stores a list of messages in OpenAI-compatible format:
    { "role": "user" | "assistant" | "system", "content": str }
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # -------------------------
    # Core persistence
    # -------------------------

    def load(self) -> List[Dict[str, str]]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def save(self, messages: List[Dict[str, str]]) -> None:
        self.path.write_text(
            json.dumps(messages, indent=2),
            encoding="utf-8",
        )

    # -------------------------
    # Append helpers
    # -------------------------

    def append(self, role: str, content: str) -> None:
        messages = self.load()
        messages.append({"role": role, "content": content})
        self.save(messages)

    def append_user(self, content: str) -> None:
        self.append("user", content)

    def append_assistant(self, content: str) -> None:
        self.append("assistant", content)

    def append_system(self, content: str) -> None:
        self.append("system", content)

    # -------------------------
    # Utilities
    # -------------------------

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def exists(self) -> bool:
        return self.path.exists()
