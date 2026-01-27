from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from memory_engine import RetrievedItem


@dataclass
class CycleState:
    """
    A Cycle represents a guarded workspace-authority session.

    Cycles gate filesystem mutation and execution authority.
    They do NOT gate intelligence, context, or pinning.

    Nothing touches disk unless the cycle is explicitly committed.
    Discarding a cycle leaves zero persistent side effects.
    """

    # -------------------------------------------------
    # Identity & lifecycle
    # -------------------------------------------------

    name: str
    status: str = "active"  # active | committed | discarded
    created_at: datetime = field(default_factory=datetime.utcnow)
    committed_at: datetime | None = None

    # -------------------------------------------------
    # Workspace containment (G2)
    # -------------------------------------------------

    locked_root: Path | None = None

    # -------------------------------------------------
    # Context snapshot (NON-AUTHORITATIVE)
    # -------------------------------------------------
    # These exist only for:
    # - audit
    # - inspection
    # - UI/debug compatibility
    #
    # They are NOT required for cycle operation.

    pins: Dict[str, Dict[str, RetrievedItem]] = field(
        default_factory=lambda: {
            "file": {},
            "memory_core": {},
        }
    )

    pinned_files: List[str] = field(default_factory=list)
    pinned_file_chunks: Dict[str, List[RetrievedItem]] = field(default_factory=dict)

    # -------------------------------------------------
    # Workspace bridge (critical authority layer)
    # -------------------------------------------------

    staged_edits: Dict[str, str] = field(default_factory=dict)
    original_snapshots: Dict[str, str] = field(default_factory=dict)

    # -------------------------------------------------
    # Notes / audit
    # -------------------------------------------------

    notes: List[str] = field(default_factory=list)

    # =================================================
    # Lifecycle
    # =================================================

    def start(self) -> None:
        self.status = "active"
        self.created_at = datetime.utcnow()
        self.committed_at = None
        self.notes.clear()
        self.clear_context_snapshot()
        self.clear_edits()

    def commit(self) -> None:
        """
        Apply staged edits to disk.

        Enforces:
        - active cycle
        - locked workspace root
        - strict root containment
        """
        self._require_active()
        self._require_locked_root()

        for path, content in self.staged_edits.items():
            p = Path(path)
            self._assert_within_root(p)
            p.write_text(content, encoding="utf-8")

        self.status = "committed"
        self.committed_at = datetime.utcnow()
        self.notes.append(f"Committed at {self.committed_at.isoformat()}")

        self.clear_edits()

    def discard(self) -> None:
        """
        Drop the cycle without touching disk.
        """
        if self.status != "active":
            return

        self.status = "discarded"
        self.notes.append(f"Discarded at {datetime.utcnow().isoformat()}")

        self.clear_context_snapshot()
        self.clear_edits()

    # =================================================
    # Guards (authority only)
    # =================================================

    def _require_active(self) -> None:
        if self.status != "active":
            raise RuntimeError("No active cycle")

    def _require_locked_root(self) -> None:
        if self.locked_root is None:
            raise RuntimeError("Workspace root is not locked")

    def _assert_within_root(self, path: Path) -> None:
        root = self.locked_root
        if root is None:
            raise RuntimeError("Workspace root is not locked")

        try:
            path.resolve().relative_to(root.resolve())
        except Exception:
            raise RuntimeError(f"Path outside locked workspace: {path}")

    # =================================================
    # Workspace root API (G2)
    # =================================================

    def lock_workspace_root(self, root: str | Path) -> None:
        """
        Lock the workspace root.

        Must be called before staging or committing edits.
        """
        self._require_active()

        root_path = Path(root).resolve()
        if not root_path.exists() or not root_path.is_dir():
            raise RuntimeError(f"Invalid workspace root: {root}")

        self.locked_root = root_path
        self.notes.append(f"Workspace root locked: {root_path}")

    # =================================================
    # Context snapshot API (NON-GATED)
    # =================================================

    def snapshot_pins(
        self,
        *,
        pins: Dict[str, Dict[str, RetrievedItem]],
        pinned_files: List[str],
        pinned_file_chunks: Dict[str, List[RetrievedItem]],
    ) -> None:
        """
        Capture a read-only snapshot of assistant context.

        This is OPTIONAL and does not affect cycle safety.
        """
        self.pins = {
            ns: dict(items) for ns, items in pins.items()
        }
        self.pinned_files = list(pinned_files)
        self.pinned_file_chunks = {
            k: list(v) for k, v in pinned_file_chunks.items()
        }
        self.notes.append("Context snapshot captured")

    def clear_context_snapshot(self) -> None:
        self.pins = {"file": {}, "memory_core": {}}
        self.pinned_files.clear()
        self.pinned_file_chunks.clear()

    def all_pinned_items(self) -> List[RetrievedItem]:
        """
        Ordered pinned context snapshot (for audit/debug only).
        """
        items: list[RetrievedItem] = []

        for path in self.pinned_files:
            items.extend(self.pinned_file_chunks.get(path, []))

        items.extend(self.pins["file"].values())
        items.extend(self.pins["memory_core"].values())

        return items

    # =================================================
    # Workspace edits (staging)
    # =================================================

    def stage_edit(self, path: str, new_content: str) -> None:
        """
        Stage a file edit.

        - Requires active cycle
        - Requires locked workspace root
        - Enforces root containment
        - Does NOT write to disk
        - Captures original snapshot once
        """
        self._require_active()
        self._require_locked_root()

        p = Path(path).resolve()
        self._assert_within_root(p)

        path_str = str(p)

        if path_str not in self.original_snapshots:
            if p.exists():
                self.original_snapshots[path_str] = p.read_text(encoding="utf-8")
            else:
                self.original_snapshots[path_str] = ""

        self.staged_edits[path_str] = new_content

    def clear_edits(self) -> None:
        self.staged_edits.clear()
        self.original_snapshots.clear()
