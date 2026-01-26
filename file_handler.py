"""File ingestion and indexing utilities."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable

from pdfminer.high_level import extract_text
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation

from config import AppConfig
from memory_engine import MemoryEngine


@dataclass(frozen=True)
class ParsedFile:
    path: str
    content: str


@dataclass(frozen=True)
class IngestStats:
    processed: int
    skipped: int
    candidate_files: int
    parse_seconds: float
    embedding_seconds: float
    faiss_seconds: float
    chunk_count: int


class FileHandler:
    def __init__(self, config: AppConfig, memory_engine: MemoryEngine) -> None:
        self.config = config
        self.memory_engine = memory_engine
        self.config.knowledge_base_path().mkdir(parents=True, exist_ok=True)

    def reindex_workspace(
        self,
        workspace_path: str,
        progress_cb: Callable[[int, int, str], None] | None = None,
    ) -> IngestStats:
        knowledge_base = self.config.knowledge_base_path()
        _, stats = self._scan_workspace(
            Path(workspace_path),
            persist=True,
            collect=False,
            exclude_dirs={knowledge_base},
            progress_cb=progress_cb,
        )
        kb_files, kb_stats = self._scan_workspace(
            knowledge_base, persist=False, progress_cb=progress_cb
        )
        index_stats = self.memory_engine.build_index(kb_files)
        return IngestStats(
            processed=stats.processed + kb_stats.processed,
            skipped=stats.skipped + kb_stats.skipped,
            candidate_files=stats.candidate_files + kb_stats.candidate_files,
            parse_seconds=stats.parse_seconds + kb_stats.parse_seconds,
            embedding_seconds=index_stats.embedding_seconds,
            faiss_seconds=index_stats.faiss_seconds,
            chunk_count=index_stats.chunk_count,
        )

    def ingest_paths(
        self,
        paths: list[str],
        progress_cb: Callable[[int, int, str], None] | None = None,
    ) -> IngestStats:
        collected: Dict[str, str] = {}
        processed = 0
        skipped = 0
        candidate_files = 0
        parse_seconds = 0.0
        for raw_path in paths:
            path = Path(raw_path)
            if path.is_dir():
                files, stats = self._scan_workspace(
                    path, persist=True, progress_cb=progress_cb
                )
                collected.update(files)
                processed += stats.processed
                skipped += stats.skipped
                candidate_files += stats.candidate_files
                parse_seconds += stats.parse_seconds
            elif path.is_file():
                candidate_files += 1
                if self._should_skip(path):
                    skipped += 1
                    continue
                start_parse = time.perf_counter()
                extracted = self._parse_file(path)
                parse_seconds += time.perf_counter() - start_parse
                if extracted:
                    self._persist_to_knowledge_base(extracted)
                    collected[extracted.path] = extracted.content
                    processed += 1
        index_stats = self.memory_engine.build_index(collected)
        return IngestStats(
            processed=processed,
            skipped=skipped,
            candidate_files=candidate_files,
            parse_seconds=parse_seconds,
            embedding_seconds=index_stats.embedding_seconds,
            faiss_seconds=index_stats.faiss_seconds,
            chunk_count=index_stats.chunk_count,
        )

    def knowledge_base_path(self) -> str:
        return self.config.knowledge_base_path().as_posix()

    def _scan_workspace(
        self,
        path: Path,
        persist: bool,
        collect: bool = True,
        exclude_dirs: set[Path] | None = None,
        progress_cb: Callable[[int, int, str], None] | None = None,
    ) -> tuple[Dict[str, str], IngestStats]:
        parsed: Dict[str, str] = {}
        total = self._count_candidate_files(path, exclude_dirs=exclude_dirs)
        processed = 0
        skipped = 0
        parse_seconds = 0.0
        for idx, file_path in enumerate(
            self._iter_candidate_files(path, exclude_dirs=exclude_dirs), start=1
        ):
            if self._should_skip(file_path):
                skipped += 1
                if progress_cb:
                    progress_cb(idx, total, f"Skipped {file_path.name}")
                continue
            start_parse = time.perf_counter()
            extracted = self._parse_file(file_path)
            parse_seconds += time.perf_counter() - start_parse
            if extracted:
                if persist:
                    self._persist_to_knowledge_base(extracted)
                if collect:
                    parsed[extracted.path] = extracted.content
                processed += 1
            if progress_cb:
                progress_cb(idx, total, f"Indexed {file_path.name}")
        return parsed, IngestStats(
            processed=processed,
            skipped=skipped,
            candidate_files=total,
            parse_seconds=parse_seconds,
            embedding_seconds=0.0,
            faiss_seconds=0.0,
            chunk_count=0,
        )

    def _count_candidate_files(
        self, path: Path, exclude_dirs: set[Path] | None = None
    ) -> int:
        return sum(
            1 for _ in self._iter_candidate_files(path, exclude_dirs=exclude_dirs)
        )

    def _iter_candidate_files(
        self, path: Path, exclude_dirs: set[Path] | None = None
    ) -> Iterable[Path]:
        exclude_dirs = {excluded.resolve() for excluded in (exclude_dirs or set())}
        root = path.resolve()
        root_depth = len(root.parts)
        allowed_suffixes = {
            ".txt",
            ".md",
            ".pdf",
            ".py",
            ".json",
            ".docx",
            ".xlsx",
            ".pptx",
        }
        max_depth = self.config.max_scan_depth
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            current_dir = Path(dirpath)
            current_depth = len(current_dir.parts) - root_depth
            if max_depth is not None and current_depth >= max_depth:
                dirnames[:] = []
            else:
                dirnames[:] = [
                    name
                    for name in dirnames
                    if self._should_descend(current_dir / name, exclude_dirs)
                ]
            for filename in filenames:
                file_path = current_dir / filename
                if self.config.skip_symlinks and file_path.is_symlink():
                    continue
                if self._is_excluded_path(file_path, exclude_dirs):
                    continue
                if file_path.suffix.lower() in allowed_suffixes:
                    yield file_path

    def _should_descend(self, path: Path, exclude_dirs: set[Path]) -> bool:
        if self.config.skip_symlinks and path.is_symlink():
            return False
        if self._is_excluded_path(path, exclude_dirs):
            return False
        return True

    def _is_excluded_path(self, path: Path, exclude_dirs: set[Path]) -> bool:
        if not exclude_dirs:
            return False
        try:
            resolved = path.resolve()
        except OSError:
            return True
        return resolved in exclude_dirs or any(
            excluded in resolved.parents for excluded in exclude_dirs
        )

    def _should_skip(self, path: Path) -> bool:
        max_bytes = self.config.max_file_mb * 1024 * 1024
        try:
            return path.stat().st_size > max_bytes
        except OSError:
            return True

    def _parse_file(self, file_path: Path) -> ParsedFile | None:
        suffix = file_path.suffix.lower()
        if suffix in {".txt", ".md"}:
            return ParsedFile(
                path=file_path.as_posix(),
                content=file_path.read_text(encoding="utf-8"),
            )
        if suffix == ".json":
            raw = file_path.read_text(encoding="utf-8")
            try:
                formatted = json.dumps(json.loads(raw), indent=2)
            except json.JSONDecodeError:
                formatted = raw
            return ParsedFile(path=file_path.as_posix(), content=formatted)
        if suffix == ".pdf":
            return ParsedFile(path=file_path.as_posix(), content=extract_text(file_path))
        if suffix == ".docx":
            return ParsedFile(
                path=file_path.as_posix(),
                content=self._extract_docx_text(file_path),
            )
        if suffix == ".xlsx":
            return ParsedFile(
                path=file_path.as_posix(),
                content=self._extract_xlsx_text(file_path),
            )
        if suffix == ".pptx":
            return ParsedFile(
                path=file_path.as_posix(),
                content=self._extract_pptx_text(file_path),
            )
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

    def _extract_docx_text(self, path: Path) -> str:
        document = Document(path.as_posix())
        return "\n".join(paragraph.text for paragraph in document.paragraphs)

    def _extract_xlsx_text(self, path: Path) -> str:
        workbook = load_workbook(path.as_posix(), read_only=True, data_only=True)
        lines = []
        for sheet in workbook.worksheets:
            lines.append(f"# Sheet: {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                row_values = ["" if cell is None else str(cell) for cell in row]
                if any(value.strip() for value in row_values):
                    lines.append("\t".join(row_values))
        return "\n".join(lines)

    def _extract_pptx_text(self, path: Path) -> str:
        presentation = Presentation(path.as_posix())
        lines = []
        for slide_idx, slide in enumerate(presentation.slides, start=1):
            lines.append(f"# Slide {slide_idx}")
            for shape in slide.shapes:
                if hasattr(shape, "text"):
                    text = shape.text.strip()
                    if text:
                        lines.append(text)
        return "\n".join(lines)

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
