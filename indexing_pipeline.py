"""
Deterministic indexing pipeline with:
- resume / skip unchanged files
- cooperative cancellation
- semantic chunking
- tier-1 + tier-2 + tier-3 tag enrichment
- detailed progress events
"""

from __future__ import annotations

import json
import hashlib
import threading
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from pdfminer.high_level import extract_text
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation

from semantic_chunker import semantic_chunk


# ============================================================
# Tier-3 Concept Registry (controlled vocabulary)
# ============================================================

CONCEPTS = {
    "buyer_liquidity": {
        "keywords": {"buyer", "demand", "liquidity"},
        "sections": {"liquidity", "market depth"},
    },
    "seller_liquidity": {
        "keywords": {"seller", "supply", "liquidity"},
        "sections": {"liquidity", "market depth"},
    },
    "market_imbalance": {
        "keywords": {"imbalance", "asymmetry"},
        "sections": {"order flow", "market structure"},
    },
    "price_discovery": {
        "keywords": {"price", "discovery"},
        "sections": {"pricing", "market structure"},
    },
}


# ============================================================
# Progress / Events
# ============================================================

class Stage(str, Enum):
    DISCOVER = "Discovering files"
    FILTER = "Filtering files"
    PARSE = "Parsing files"
    CHUNK = "Chunking text"
    STORE = "Storing chunks"
    INDEX = "Building index"


@dataclass
class ProgressEvent:
    stage: Stage
    current: int
    total: int
    message: str
    file: str | None = None
    debug: bool = False


class ProgressSink:
    def __init__(self, emit: Callable[[ProgressEvent], None]):
        self.emit = emit

    def stage(self, stage: Stage, total: int, message: str):
        self.emit(ProgressEvent(stage, 0, total, message))

    def step(self, stage: Stage, current: int, total: int, file: str):
        self.emit(ProgressEvent(stage, current, total, "Processing", file))

    def log(self, stage: Stage, message: str):
        self.emit(ProgressEvent(stage, 0, 0, message, debug=True))


# ============================================================
# Data Models
# ============================================================

@dataclass(frozen=True)
class ParsedDocument:
    path: str
    text: str


@dataclass(frozen=True)
class Chunk:
    id: str
    source: str
    text: str


# ============================================================
# Indexing Pipeline
# ============================================================

class IndexingPipeline:
    SUPPORTED_SUFFIXES = {
        ".txt", ".md", ".pdf", ".py", ".json", ".docx", ".xlsx", ".pptx"
    }

    TYPE_BY_EXT = {
        ".py": "code",
        ".md": "doc",
        ".txt": "doc",
        ".pdf": "doc",
        ".docx": "doc",
        ".pptx": "presentation",
        ".xlsx": "data",
        ".json": "data",
    }

    # ---------- Tier-2 keyword extraction ----------
    _WORD_RE = re.compile(r"[a-zA-Z]{4,}")
    _STOPWORDS = {
        "this", "that", "with", "from", "there", "where", "which",
        "about", "would", "could", "should", "their", "these",
        "those", "using", "used", "into", "than", "then",
        "have", "has", "had", "also", "such", "more", "most",
    }

    def __init__(
        self,
        memory_engine,
        kb_path: Path,
        chunk_size: int = 1200,
        overlap: int = 200,
    ):
        self.memory_engine = memory_engine
        self.kb_path = kb_path
        self.chunk_size = chunk_size
        self.overlap = overlap

        self.ingest_path = kb_path / "ingested"
        self.chunk_path = self.ingest_path / "chunks"
        self.meta_path = self.ingest_path / "meta.json"

        self.chunk_path.mkdir(parents=True, exist_ok=True)

        self._cancel_event = threading.Event()
        self.meta = self._load_meta()

    # ========================================================
    # Control
    # ========================================================

    def cancel(self):
        self._cancel_event.set()

    def _cancelled(self) -> bool:
        return self._cancel_event.is_set()

    # ========================================================
    # Public Entry
    # ========================================================

    def run(self, root: Path, sink: ProgressSink):
        files = self._discover(root, sink)
        if self._cancelled(): return

        files = self._filter(files, sink)
        if self._cancelled(): return

        docs = self._parse(files, sink)
        if self._cancelled(): return

        chunks = self._chunk(docs, sink)
        if self._cancelled(): return

        self._store(chunks, sink)
        if self._cancelled(): return

        self._index(chunks, sink)
        self._save_meta()

    # ========================================================
    # Metadata
    # ========================================================

    def _load_meta(self) -> dict:
        if self.meta_path.exists():
            try:
                return json.loads(self.meta_path.read_text())
            except Exception:
                pass
        return {"files": {}}

    def _save_meta(self):
        self.meta_path.write_text(json.dumps(self.meta, indent=2))

    def _file_hash(self, path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    # ========================================================
    # Discover / Filter / Parse (unchanged)
    # ========================================================

    def _discover(self, root: Path, sink: ProgressSink) -> list[Path]:
        sink.stage(Stage.DISCOVER, 0, f"Scanning {root}")
        files = [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
        sink.log(Stage.DISCOVER, f"Found {len(files)} files")
        return files

    def _filter(self, files: list[Path], sink: ProgressSink) -> list[Path]:
        accepted = []
        for p in files:
            if p.name.startswith("~$"):
                continue
            if p.suffix.lower() not in self.SUPPORTED_SUFFIXES:
                continue
            accepted.append(p)
        sink.log(Stage.FILTER, f"Accepted {len(accepted)} files")
        return accepted

    def _parse(self, files: list[Path], sink: ProgressSink) -> list[ParsedDocument]:
        docs = []
        sink.stage(Stage.PARSE, len(files), "Parsing files")

        for idx, path in enumerate(files, start=1):
            if self._cancelled():
                return docs

            sink.step(Stage.PARSE, idx, len(files), path.name)

            digest = self._file_hash(path)
            mtime = int(path.stat().st_mtime)

            prev = self.meta["files"].get(path.as_posix())
            if prev and prev["hash"] == digest and prev["mtime"] == mtime:
                continue

            text = self._extract_text(path)
            if text.strip():
                docs.append(ParsedDocument(path=path.as_posix(), text=text))
                self.meta["files"][path.as_posix()] = {
                    "hash": digest,
                    "mtime": mtime,
                }

        return docs

    # ========================================================
    # Tier-1 / Tier-2 / Tier-3 Tag Helpers
    # ========================================================

    def _file_level_tags(self, path: Path) -> set[str]:
        tags = {f"ext:{path.suffix.lower()}", f"type:{self.TYPE_BY_EXT.get(path.suffix.lower(), 'doc')}", "namespace:file"}
        for part in path.parts:
            tags.add(f"path:{part.lower()}")
        return tags

    def _extract_keywords(self, text: str, max_keywords: int = 5) -> set[str]:
        counts = {}
        for m in self._WORD_RE.finditer(text.lower()):
            w = m.group(0)
            if w in self._STOPWORDS:
                continue
            counts[w] = counts.get(w, 0) + 1
        ranked = sorted(counts.items(), key=lambda x: (-x[1], -len(x[0])))
        return {f"keyword:{w}" for w, _ in ranked[:max_keywords]}

    def _extract_concepts(self, *, text: str, section_path: list[str]) -> set[str]:
        concepts = set()
        text_l = text.lower()
        section_l = {s.lower() for s in section_path}

        for name, rule in CONCEPTS.items():
            if rule.get("sections") and section_l & rule["sections"]:
                concepts.add(f"concept:{name}")
                continue
            if rule.get("keywords") and any(k in text_l for k in rule["keywords"]):
                concepts.add(f"concept:{name}")

        return concepts

    # ========================================================
    # Chunk
    # ========================================================

    def _chunk(self, docs: list[ParsedDocument], sink: ProgressSink) -> list[Chunk]:
        chunks = []
        sink.stage(Stage.CHUNK, len(docs), "Chunking documents")

        for doc in docs:
            file_tags = self._file_level_tags(Path(doc.path))
            structured = semantic_chunk(doc.text, max_chars=self.chunk_size)

            # ---------- overview ----------
            oid = f"{doc.path}::overview"
            tags = (
                file_tags
                | {"overview"}
                | self._extract_keywords(doc.text)
                | self._extract_concepts(text=doc.text, section_path=[])
            )

            chunks.append(Chunk(oid, doc.path, doc.text[:1000]))
            self._write_meta(oid, {"is_overview": True, "tags": sorted(tags)})

            # ---------- normal chunks ----------
            for i, sc in enumerate(structured):
                cid = f"{doc.path}:{i}"
                meta = sc["metadata"]

                tags = (
                    file_tags
                    | self._extract_keywords(sc["text"])
                    | self._extract_concepts(
                        text=sc["text"],
                        section_path=meta.get("section_path", []),
                    )
                )

                chunks.append(Chunk(cid, doc.path, sc["text"]))
                self._write_meta(cid, {**meta, "is_overview": False, "tags": sorted(tags)})

        return chunks

    # ========================================================
    # Store / Index / Helpers (unchanged)
    # ========================================================

    def _store(self, chunks: list[Chunk], sink: ProgressSink):
        for c in chunks:
            safe = c.id.replace(":", "__").replace("/", "__").replace("\\", "__")
            (self.chunk_path / f"{safe}.txt").write_text(c.text, encoding="utf-8")

    def _index(self, chunks: list[Chunk], sink: ProgressSink):
        sink.stage(Stage.INDEX, len(chunks), "Embedding + indexing chunks")

        mapping = {c.id: c.text for c in chunks}

        def progress(cur: int, total: int, message: str):
            sink.emit(
                ProgressEvent(
                    stage=Stage.INDEX,
                    current=cur,
                    total=total,
                    message=message,
                )
            )

        stats = self.memory_engine.build_index(
            mapping,
            progress_cb=progress,
        )

        sink.log(
            Stage.INDEX,
            f"Embedding done | chunks={stats.chunk_count} "
            f"embed={stats.embedding_seconds:.2f}s "
            f"faiss={stats.faiss_seconds:.2f}s",
        )


    def _write_meta(self, cid: str, meta: dict):
        safe = cid.replace(":", "__").replace("/", "__").replace("\\", "__")
        (self.chunk_path / f"{safe}.meta.json").write_text(json.dumps(meta, indent=2))

    def _extract_text(self, path: Path) -> str:
        suf = path.suffix.lower()
        if suf in {".txt", ".md"}:
            return path.read_text("utf-8", errors="ignore")
        if suf == ".pdf":
            return extract_text(path)
        if suf == ".docx":
            return "\n".join(p.text for p in Document(path).paragraphs)
        if suf == ".pptx":
            return "\n".join(shape.text for slide in Presentation(path).slides for shape in slide.shapes if hasattr(shape, "text"))
        if suf == ".xlsx":
            wb = load_workbook(path, read_only=True, data_only=True)
            return "\n".join("\t".join(str(c) for c in row if c) for sh in wb.worksheets for row in sh.iter_rows(values_only=True))
        if suf == ".json":
            return json.dumps(json.loads(path.read_text()), indent=2)
        return ""
