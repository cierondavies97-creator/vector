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
        files = self._scan_workspace(Path(workspace_path), persist=True)
        files.update(self._scan_workspace(self.config.knowledge_base_path(), persist=False))
        self.memory_engine.build_index(files)

    def ingest_paths(self, paths: list[str]) -> None:
        collected: Dict[str, str] = {}
        for raw_path in paths:
            path = Path(raw_path)
            if path.is_dir():
                collected.update(self._scan_workspace(path, persist=True))
            elif path.is_file():
                extracted = self._parse_file(path)
                if extracted:
                    self._persist_to_knowledge_base(extracted)
                    collected[extracted.path] = extracted.content
        self.memory_engine.build_index(collected)

    def knowledge_base_path(self) -> str:
        return self.config.knowledge_base_path().as_posix()

    def _scan_workspace(self, path: Path, persist: bool) -> Dict[str, str]:
        parsed: Dict[str, str] = {}
        for file_path in path.rglob("*"):
            if file_path.is_dir():
                continue
            extracted = self._parse_file(file_path)
            if extracted:
                if persist:
                    self._persist_to_knowledge_base(extracted)
                parsed[extracted.path] = extracted.content
        return parsed

    def _parse_file(self, file_path: Path) -> ParsedFile | None:
        suffix = file_path.suffix.lower()
        if suffix in {".txt", ".md"}:
            return ParsedFile(
                path=file_path.as_posix(),
                content=file_path.read_text(encoding="utf-8"),
            )
        if suffix == ".pdf":
            return ParsedFile(path=file_path.as_posix(), content=extract_text(file_path))
        if suffix == ".py":
            return ParsedFile(
                path=file_path.as_posix(),
                content=self._extract_python_comments(file_path),
            )
        return None

    def _extract_python_comments(self, path: Path) -> str:
        lines = path.read_text(encoding="utf-8").splitlines()
        comment_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                comment_lines.append(stripped.lstrip("# "))
        return "\n".join(comment_lines)

    def _persist_to_knowledge_base(self, parsed: ParsedFile) -> None:
        knowledge_base = self.config.knowledge_base_path() / "ingested"
        knowledge_base.mkdir(parents=True, exist_ok=True)
        safe_name = (
            parsed.path.replace(":", "")
            .replace("\\", "__")
            .replace("/", "__")
            .strip("_")
        )
        target_path = knowledge_base / f"{safe_name}.txt"
        target_path.write_text(parsed.content, encoding="utf-8")

    def save_note(self, note: str) -> str:
        knowledge_base = self.config.knowledge_base_path()
        knowledge_base.mkdir(parents=True, exist_ok=True)
        existing = list(knowledge_base.glob("note_*.txt"))
        note_id = len(existing) + 1
        note_path = knowledge_base / f"note_{note_id:03d}.txt"
        note_path.write_text(note, encoding="utf-8")
        return note_path.as_posix()

    def save_chat(self, query: str, response: str) -> str:
        from datetime import datetime

        chat_dir = self.config.knowledge_base_path() / "chats"
        chat_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        chat_path = chat_dir / f"chat_{timestamp}.md"
        chat_path.write_text(
            f"# Chat {timestamp}\n\n## Query\n{query}\n\n## Response\n{response}\n",
            encoding="utf-8",
        )
        return chat_path.as_posix()
