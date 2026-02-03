import sys
import threading
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets

from assistant import Assistant
from config import AppConfig
from indexing_pipeline import IndexingPipeline, ProgressSink, ProgressEvent
from memory_engine import MemoryEngine


class IndexStatusDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Indexing Progress")
        self.setMinimumSize(520, 300)

        layout = QtWidgets.QVBoxLayout(self)

        self.stage_label = QtWidgets.QLabel("Idle")
        self.file_label = QtWidgets.QLabel("")
        self.file_label.setStyleSheet("color: #6b7280;")

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 0)

        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)

        layout.addWidget(self.stage_label)
        layout.addWidget(self.progress)
        layout.addWidget(self.file_label)
        layout.addWidget(self.log)

    def update_event(self, event: ProgressEvent) -> None:
        self.stage_label.setText(event.stage.value)
        if event.total:
            self.progress.setMaximum(event.total)
            self.progress.setValue(event.current)
        if event.file:
            self.file_label.setText(event.file)
        if event.debug:
            self.log.append(event.message)


class ProgressEmitter(QtCore.QObject):
    progress = QtCore.pyqtSignal(object)
    finished = QtCore.pyqtSignal()


class VectorQtApp(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Vector Assistant")
        self.resize(1450, 900)

        self.config = AppConfig.load()
        self.memory_engine = MemoryEngine(self.config)
        self.assistant = Assistant(self.config, self.memory_engine)

        self.pipeline: IndexingPipeline | None = None
        self.progress_emitter = ProgressEmitter()
        self.progress_emitter.progress.connect(self._on_progress)
        self.progress_emitter.finished.connect(self._on_index_finished)
        self.status_dialog: IndexStatusDialog | None = None

        self.use_memory = True
        self.use_memory_core = True
        self.last_debug: dict = {}

        self._build_ui()
        self._load_chat_history()
        self._update_cycle_status()

    def _build_ui(self) -> None:
        font = QtGui.QFont("Segoe UI", 10)
        self.setFont(font)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root_layout = QtWidgets.QVBoxLayout(central)
        root_layout.setContentsMargins(12, 10, 12, 12)
        root_layout.setSpacing(8)

        top_bar = QtWidgets.QHBoxLayout()
        root_layout.addLayout(top_bar)

        choose_btn = QtWidgets.QPushButton("Choose Directory")
        choose_btn.clicked.connect(self._choose_dir)
        top_bar.addWidget(choose_btn)

        reindex_btn = QtWidgets.QPushButton("Reindex")
        reindex_btn.clicked.connect(self._reindex)
        top_bar.addWidget(reindex_btn)

        cancel_btn = QtWidgets.QPushButton("Cancel Indexing")
        cancel_btn.clicked.connect(self._cancel)
        top_bar.addWidget(cancel_btn)

        pin_btn = QtWidgets.QPushButton("📌 Pin File…")
        pin_btn.clicked.connect(self._pin_file_browser)
        top_bar.addWidget(pin_btn)

        top_bar.addSpacing(12)

        self.use_memory_checkbox = QtWidgets.QCheckBox("Use Knowledge Base")
        self.use_memory_checkbox.setChecked(True)
        self.use_memory_checkbox.toggled.connect(self._toggle_memory)
        top_bar.addWidget(self.use_memory_checkbox)

        self.use_memory_core_checkbox = QtWidgets.QCheckBox("Use Memory Core")
        self.use_memory_core_checkbox.setChecked(True)
        self.use_memory_core_checkbox.toggled.connect(self._toggle_memory_core)
        top_bar.addWidget(self.use_memory_core_checkbox)

        top_bar.addStretch()

        self.cycle_status = QtWidgets.QLabel("🟡 No active cycle")
        self.cycle_status.setStyleSheet("color: #6b7280;")
        root_layout.addWidget(self.cycle_status)

        content_layout = QtWidgets.QGridLayout()
        content_layout.setHorizontalSpacing(12)
        content_layout.setVerticalSpacing(8)
        root_layout.addLayout(content_layout)

        content_layout.addWidget(QtWidgets.QLabel("Query"), 0, 0)
        self.query = QtWidgets.QTextEdit()
        self.query.setFixedHeight(120)
        content_layout.addWidget(self.query, 1, 0)

        ask_btn = QtWidgets.QPushButton("Ask")
        ask_btn.clicked.connect(self._ask)
        ask_btn.setFixedWidth(80)
        ask_btn.setStyleSheet(
            "QPushButton { background: #2d6cdf; color: white; padding: 8px; }"
            "QPushButton:hover { background: #1f5ab8; }"
        )
        content_layout.addWidget(ask_btn, 1, 1, alignment=QtCore.Qt.AlignmentFlag.AlignTop)

        content_layout.addWidget(QtWidgets.QLabel("Response"), 2, 0)
        self.response = QtWidgets.QTextEdit()
        self.response.setReadOnly(True)
        content_layout.addWidget(self.response, 3, 0, 1, 2)

        right_panel = QtWidgets.QVBoxLayout()
        content_layout.addLayout(right_panel, 0, 2, 6, 1)

        right_panel.addWidget(QtWidgets.QLabel("📌 Pinned Files (Context)"))
        self.pinned_list = QtWidgets.QListWidget()
        self.pinned_list.setFixedHeight(160)
        right_panel.addWidget(self.pinned_list)

        pin_controls = QtWidgets.QHBoxLayout()
        right_panel.addLayout(pin_controls)

        up_btn = QtWidgets.QPushButton("↑")
        up_btn.clicked.connect(lambda: self._move_pin(-1))
        up_btn.setFixedWidth(32)
        pin_controls.addWidget(up_btn)

        down_btn = QtWidgets.QPushButton("↓")
        down_btn.clicked.connect(lambda: self._move_pin(1))
        down_btn.setFixedWidth(32)
        pin_controls.addWidget(down_btn)

        unpin_btn = QtWidgets.QPushButton("Unpin")
        unpin_btn.clicked.connect(self._unpin_selected)
        pin_controls.addWidget(unpin_btn)
        pin_controls.addStretch()

        right_panel.addWidget(QtWidgets.QLabel("Injected Context (Debug)"))
        self.memory = QtWidgets.QTextEdit()
        self.memory.setReadOnly(True)
        right_panel.addWidget(self.memory, stretch=1)

        right_panel.addWidget(QtWidgets.QLabel("Knowledge Heatmap"))
        self.heatmap_box_files = QtWidgets.QTextEdit()
        self.heatmap_box_files.setReadOnly(True)
        self.heatmap_box_files.setFixedHeight(120)
        right_panel.addWidget(self.heatmap_box_files)

        right_panel.addWidget(QtWidgets.QLabel("Memory Heatmap"))
        self.heatmap_box_core = QtWidgets.QTextEdit()
        self.heatmap_box_core.setReadOnly(True)
        self.heatmap_box_core.setFixedHeight(120)
        right_panel.addWidget(self.heatmap_box_core)

        self._apply_styles()

    def _apply_styles(self) -> None:
        palette = self.palette()
        palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor("#f5f7fb"))
        palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor("#ffffff"))
        palette.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor("#1f2937"))
        self.setPalette(palette)

        text_style = (
            "QTextEdit, QListWidget {"
            "background: #ffffff;"
            "border: 1px solid #d5dbe6;"
            "border-radius: 4px;"
            "padding: 6px;"
            "}"
        )
        self.setStyleSheet(text_style)

    def _toggle_memory(self, checked: bool) -> None:
        self.use_memory = checked

    def _toggle_memory_core(self, checked: bool) -> None:
        self.use_memory_core = checked

    def _update_cycle_status(self) -> None:
        cycle = self.assistant.active_cycle
        if not cycle:
            self.cycle_status.setText("🟡 No active cycle (context-only mode)")
            return
        staged = len(cycle.staged_edits)
        self.cycle_status.setText(
            f"🟢 Cycle: {cycle.name} | Status: {cycle.status} | Staged: {staged}"
        )

    def _refresh_pinned_panel(self) -> None:
        self.pinned_list.clear()
        for path in self.assistant.pinned_files:
            self.pinned_list.addItem(path)
        self._update_cycle_status()

    def _move_pin(self, direction: int) -> None:
        row = self.pinned_list.currentRow()
        if row < 0:
            return
        path = self.pinned_list.item(row).text()
        self.assistant.move_pinned_file(path, direction)
        self._refresh_pinned_panel()
        self._render_debug()

    def _unpin_selected(self) -> None:
        row = self.pinned_list.currentRow()
        if row < 0:
            return
        path = self.pinned_list.item(row).text()
        self.assistant.unpin_file(path)
        self._refresh_pinned_panel()
        self._render_debug()

    def _pin_file_browser(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Pin file")
        if path:
            self.assistant.pin_file(path)
            self._refresh_pinned_panel()
            self._render_debug()

    def _choose_dir(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose workspace")
        if not directory:
            return
        self.config = self.config.with_workspace(directory)
        QtWidgets.QMessageBox.information(self, "Workspace set", directory)
        self._update_cycle_status()

    def _reindex(self) -> None:
        if not self.config.workspace_path:
            QtWidgets.QMessageBox.warning(self, "Missing directory", "Choose a directory first")
            return

        self.status_dialog = IndexStatusDialog(self)
        self.status_dialog.show()

        def run_pipeline() -> None:
            self.pipeline = IndexingPipeline(
                self.memory_engine,
                self.config.knowledge_base_path(),
                chunk_size=self.config.chunk_size,
                overlap=self.config.chunk_overlap,
            )
            sink = ProgressSink(lambda e: self.progress_emitter.progress.emit(e))
            self.pipeline.run(Path(self.config.workspace_path), sink)
            self.progress_emitter.finished.emit()

        threading.Thread(target=run_pipeline, daemon=True).start()

    def _cancel(self) -> None:
        if self.pipeline:
            self.pipeline.cancel()

    def _on_progress(self, event: ProgressEvent) -> None:
        if self.status_dialog:
            self.status_dialog.update_event(event)

    def _on_index_finished(self) -> None:
        if self.status_dialog:
            self.status_dialog.close()
            self.status_dialog = None

    def _ask(self) -> None:
        q = self.query.toPlainText().strip()
        if not q:
            return

        response, _, _, debug = self.assistant.answer(
            q,
            use_memory=self.use_memory,
            use_memory_core=self.use_memory_core,
        )
        self.last_debug = debug or {}

        self.response.append(f"\n🧑 You:\n{q}\n")
        self.response.append(f"\n🤖 Assistant:\n{response}\n")
        self.query.clear()

        self._refresh_pinned_panel()
        self._render_debug()
        self._render_concept_heatmap()

    def _render_debug(self) -> None:
        debug = self.last_debug or {}
        lines: list[str] = []
        lines.append("Query Rewrite")
        lines.append(f"  Original : {debug.get('query')}")
        lines.append(f"  Rewritten: {debug.get('rewritten_query')}\n")

        def add_items(title: str, items: list[dict]) -> None:
            if not items:
                return
            lines.append(title)
            lines.append("")
            for item in items:
                retrieval = item.get("retrieval", {})
                score = retrieval.get("score", 0.0)
                rank = retrieval.get("rank")
                lines.append(
                    f"[{'PIN' if item.get('chunk_id') in self.assistant.session_pins.get(item.get('namespace'), {}) else ' '}] "
                    f"{item.get('source_path', '')} (score={score:.3f}, rank={rank})"
                )
                if retrieval:
                    lines.append("  Retrieval:")
                    for k, v in retrieval.items():
                        lines.append(f"    - {k}: {v}")
                ranking = item.get("ranking", {})
                if ranking:
                    lines.append("  Ranking:")
                    for k, v in ranking.items():
                        lines.append(f"    - {k}: {v}")
                semantic = item.get("semantic_signals", {})
                if semantic:
                    lines.append("  Semantic Signals:")
                    for k, v in semantic.items():
                        lines.append(f"    - {k}: {v}")
                pin_state = item.get("pin_state", {})
                if pin_state:
                    lines.append("  Pin State:")
                    for k, v in pin_state.items():
                        lines.append(f"    - {k}: {v}")
                tags = item.get("tags", [])
                if tags:
                    lines.append("  Tags:")
                    for tag in tags:
                        lines.append(f"    - {tag}")
                lines.append("")
                lines.append(item.get("text", ""))
                lines.append("")

        add_items("MEMORY CORE", debug.get("memory_core", []))
        add_items("KNOWLEDGE BASE", debug.get("file_memory", []))

        self.memory.setPlainText("\n".join(lines))

    def _render_concept_heatmap(self) -> None:
        self._render_heatmap_box(
            self.heatmap_box_files,
            self.last_debug.get("concept_heatmap_files") or {},
            empty_message="No semantic concepts triggered in knowledge.",
        )
        self._render_heatmap_box(
            self.heatmap_box_core,
            self.last_debug.get("concept_heatmap_memory_core") or {},
            empty_message="No semantic concepts triggered in memory.",
        )

    def _render_heatmap_box(self, box: QtWidgets.QTextEdit, heatmap: dict, empty_message: str) -> None:
        if not heatmap:
            box.setPlainText(empty_message)
            return
        lines = []
        for concept, data in heatmap.items():
            bar = "█" * int(data["normalized_dominance"] * 10)
            lines.append(
                f"{concept.replace('concept:', ''):<22} "
                f"{bar:<10} "
                f"{data['normalized_dominance']:.2f}"
            )
            lines.append(f"  chunks: {', '.join(data['contributing_chunks'])}")
        box.setPlainText("\n".join(lines))

    def _load_chat_history(self) -> None:
        for message in self.assistant.chat_store.load():
            role = "🧑 You" if message["role"] == "user" else "🤖 Assistant"
            self.response.append(f"\n{role}:\n{message['content']}\n")


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    window = VectorQtApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
