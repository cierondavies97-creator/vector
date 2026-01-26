"""File ingestion and indexing utilities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from pdfminer.high_level import extract_text

from config import AppConfig
from memory_engine import MemoryEngine


@dataclass(frozen=True)
class ParsedFile:
    path: str
    content: str


class FileHandler:
    def __init__(self, config: AppConfig, memory_engine: MemoryEngine) -> None:
        self.config = config
        self.memory_engine = memory_engine
        self.config.knowledge_base_path().mkdir(parents=True, exist_ok=True)

    def reindex_workspace(self, workspace_path: str) -> None:
        files = self._scan_workspace(Path(workspace_path))
        self.memory_engine.build_index(files)

    def _scan_workspace(self, path: Path) -> Dict[str, str]:
        parsed: Dict[str, str] = {}
        for file_path in path.rglob("*"):
            if file_path.is_dir():
                continue
            if file_path.suffix.lower() in {".txt", ".md"}:
                parsed[file_path.as_posix()] = file_path.read_text(encoding="utf-8")
            elif file_path.suffix.lower() == ".pdf":
                parsed[file_path.as_posix()] = extract_text(file_path)
            elif file_path.suffix.lower() == ".py":
                parsed[file_path.as_posix()] = self._extract_python_comments(file_path)
        return parsed

    def _extract_python_comments(self, path: Path) -> str:
        lines = path.read_text(encoding="utf-8").splitlines()
        comment_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                comment_lines.append(stripped.lstrip("# "))
        return "\n".join(comment_lines)

    def save_note(self, note: str) -> str:
        knowledge_base = self.config.knowledge_base_path()
        knowledge_base.mkdir(parents=True, exist_ok=True)
        existing = list(knowledge_base.glob("note_*.txt"))
        note_id = len(existing) + 1
        note_path = knowledge_base / f"note_{note_id:03d}.txt"
        note_path.write_text(note, encoding="utf-8")
        return note_path.as_posix()
