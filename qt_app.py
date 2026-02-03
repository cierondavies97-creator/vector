import json
import sys
import threading
import traceback
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
        self.file_label.setStyleSheet("color: #9aa4b2;")

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
    error = QtCore.pyqtSignal(object)
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
        self.progress_emitter.error.connect(self._on_index_error)
        self.progress_emitter.finished.connect(self._on_index_finished)
        self.status_dialog: IndexStatusDialog | None = None

        self.use_memory = True
        self.use_memory_core = True
        self.last_debug: dict = {}

        self._apply_font()
        self._build_ui()
        self._load_chat_history()
        self._update_cycle_status()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root_layout = QtWidgets.QVBoxLayout(central)
        root_layout.setContentsMargins(12, 10, 12, 12)
        root_layout.setSpacing(8)

        top_bar = QtWidgets.QHBoxLayout()
        root_layout.addLayout(top_bar)

        chat_menu = QtWidgets.QMenu(self)
        chat_menu.addAction("Save Chat…", self._export_chat)
        chat_menu.addAction("Clear Chat", self._clear_chat)

        chat_menu_btn = QtWidgets.QToolButton()
        chat_menu_btn.setText("Chat")
        chat_menu_btn.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        chat_menu_btn.setMenu(chat_menu)
        chat_menu_btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        chat_menu_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_FileDialogDetailedView))
        top_bar.addWidget(chat_menu_btn)

        index_menu = QtWidgets.QMenu(self)
        index_menu.addAction("Choose Workspace…", self._choose_dir)
        index_menu.addAction("Index Directory…", self._index_directory)
        index_menu.addAction("Reindex", self._reindex)
        index_menu.addAction("Cancel Reindex", self._cancel)

        index_menu_btn = QtWidgets.QToolButton()
        index_menu_btn.setText("Index")
        index_menu_btn.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
        index_menu_btn.setMenu(index_menu)
        index_menu_btn.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        index_menu_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserReload))
        top_bar.addWidget(index_menu_btn)

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
        self.cycle_status.setStyleSheet("color: #9aa4b2;")
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
            "QPushButton { background: #2b66d1; color: white; padding: 8px; }"
            "QPushButton:hover { background: #2458b6; }"
        )
        content_layout.addWidget(ask_btn, 1, 1, alignment=QtCore.Qt.AlignmentFlag.AlignTop)

        content_layout.addWidget(QtWidgets.QLabel("Response"), 2, 0)
        self.response = QtWidgets.QTextEdit()
        self.response.setReadOnly(True)
        content_layout.addWidget(self.response, 3, 0, 1, 2)

        self._build_pinned_dock()
        self._build_debug_dock()
        self._apply_styles()

    def _apply_font(self) -> None:
        font_candidates = ["Aptos", "Aptos (Body)", "Segoe UI", "Inter", "Arial"]
        available = set(QtGui.QFontDatabase.families())
        family = next((name for name in font_candidates if name in available), "Segoe UI")
        font = QtGui.QFont(family, 10)
        self.setFont(font)

    def _build_pinned_dock(self) -> None:
        dock = QtWidgets.QDockWidget("Pinned Files", self)
        dock.setObjectName("PinnedDock")
        dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        dock.setAllowedAreas(
            QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
            | QtCore.Qt.DockWidgetArea.RightDockWidgetArea
        )

        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        layout.addWidget(QtWidgets.QLabel("📌 Pinned Files (Context)"))
        self.pinned_list = QtWidgets.QListWidget()
        layout.addWidget(self.pinned_list)

        controls = QtWidgets.QHBoxLayout()
        up_btn = QtWidgets.QPushButton("↑")
        up_btn.clicked.connect(lambda: self._move_pin(-1))
        up_btn.setFixedWidth(32)
        controls.addWidget(up_btn)

        down_btn = QtWidgets.QPushButton("↓")
        down_btn.clicked.connect(lambda: self._move_pin(1))
        down_btn.setFixedWidth(32)
        controls.addWidget(down_btn)

        unpin_btn = QtWidgets.QPushButton("Unpin")
        unpin_btn.clicked.connect(self._unpin_selected)
        controls.addWidget(unpin_btn)
        controls.addStretch()
        layout.addLayout(controls)

        dock.setWidget(container)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    def _build_debug_dock(self) -> None:
        dock = QtWidgets.QDockWidget("Debug & Heatmaps", self)
        dock.setObjectName("DebugDock")
        dock.setFeatures(
            QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        dock.setAllowedAreas(
            QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
            | QtCore.Qt.DockWidgetArea.RightDockWidgetArea
        )

        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        layout.addWidget(QtWidgets.QLabel("Injected Context (Debug)"))
        self.memory = QtWidgets.QTextEdit()
        self.memory.setReadOnly(True)
        layout.addWidget(self.memory, stretch=1)

        layout.addWidget(QtWidgets.QLabel("Knowledge Heatmap"))
        self.heatmap_box_files = QtWidgets.QTextEdit()
        self.heatmap_box_files.setReadOnly(True)
        self.heatmap_box_files.setFixedHeight(120)
        layout.addWidget(self.heatmap_box_files)

        layout.addWidget(QtWidgets.QLabel("Memory Heatmap"))
        self.heatmap_box_core = QtWidgets.QTextEdit()
        self.heatmap_box_core.setReadOnly(True)
        self.heatmap_box_core.setFixedHeight(120)
        layout.addWidget(self.heatmap_box_core)

        dock.setWidget(container)
        self.addDockWidget(QtCore.Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _apply_styles(self) -> None:
        palette = self.palette()
        palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor("#0f1116"))
        palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor("#151a21"))
        palette.setColor(QtGui.QPalette.ColorRole.AlternateBase, QtGui.QColor("#1b222c"))
        palette.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor("#e5e7eb"))
        palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor("#e5e7eb"))
        palette.setColor(QtGui.QPalette.ColorRole.Button, QtGui.QColor("#1b222c"))
        palette.setColor(QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor("#e5e7eb"))
        palette.setColor(QtGui.QPalette.ColorRole.Highlight, QtGui.QColor("#4f8cff"))
        palette.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor("#ffffff"))
        self.setPalette(palette)

        text_style = (
            "QTextEdit, QListWidget {"
            "background: #151a21;"
            "color: #e5e7eb;"
            "border: 1px solid #2a3240;"
            "border-radius: 6px;"
            "padding: 8px;"
            "}"
            "QLabel {"
            "color: #e5e7eb;"
            "}"
            "QCheckBox {"
            "color: #e5e7eb;"
            "}"
            "QToolButton, QPushButton {"
            "background: #1b222c;"
            "color: #e5e7eb;"
            "border: 1px solid #2a3240;"
            "border-radius: 6px;"
            "padding: 6px 10px;"
            "}"
            "QToolButton:hover, QPushButton:hover {"
            "background: #232c39;"
            "}"
            "QToolButton:pressed, QPushButton:pressed {"
            "background: #2c3645;"
            "}"
            "QMenu {"
            "background: #1b222c;"
            "color: #e5e7eb;"
            "border: 1px solid #2a3240;"
            "padding: 4px;"
            "}"
            "QMenu::item:selected {"
            "background: #2b66d1;"
            "}"
            "QDockWidget::title {"
            "background: #1b222c;"
            "color: #e5e7eb;"
            "padding: 6px;"
            "font-weight: 600;"
            "border-bottom: 1px solid #2a3240;"
            "}"
            "QStatusBar {"
            "background: #0f1116;"
            "color: #9aa4b2;"
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
            try:
                self.assistant.pin_file(path)
            except Exception as exc:  # noqa: BLE001 - surface runtime dependency failures to the UI
                self._show_error(
                    "Pin file failed",
                    exc,
                    "Embedding model failed to load while pinning. "
                    "Verify torch and sentence-transformers are installed correctly.",
                )
                return
            self._refresh_pinned_panel()
            self._render_debug()

    def _choose_dir(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose workspace")
        if not directory:
            return
        self.config = self.config.with_workspace(directory)
        QtWidgets.QMessageBox.information(self, "Workspace set", directory)
        self._update_cycle_status()

    def _index_directory(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose directory to index")
        if not directory:
            return
        self._start_indexing(Path(directory))

    def _reindex(self) -> None:
        if not self.config.workspace_path:
            QtWidgets.QMessageBox.warning(self, "Missing directory", "Choose a directory first")
            return
        self._start_indexing(Path(self.config.workspace_path))

    def _start_indexing(self, workspace: Path) -> None:
        self.status_dialog = IndexStatusDialog(self)
        self.status_dialog.show()

        def run_pipeline() -> None:
            try:
                self.pipeline = IndexingPipeline(
                    self.memory_engine,
                    self.config.knowledge_base_path(),
                    chunk_size=self.config.chunk_size,
                    overlap=self.config.chunk_overlap,
                )
                sink = ProgressSink(lambda e: self.progress_emitter.progress.emit(e))
                self.pipeline.run(workspace, sink)
            except Exception as exc:  # noqa: BLE001 - surface runtime dependency failures to the UI
                self.progress_emitter.error.emit(exc)
            finally:
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

    def _on_index_error(self, exc: Exception) -> None:
        self._show_error(
            "Indexing failed",
            exc,
            "Embedding model failed to load while indexing. "
            "Verify torch and sentence-transformers are installed correctly.",
        )

    def _ask(self) -> None:
        q = self.query.toPlainText().strip()
        if not q:
            return

        try:
            response, _, _, debug = self.assistant.answer(
                q,
                use_memory=self.use_memory,
                use_memory_core=self.use_memory_core,
            )
        except Exception as exc:  # noqa: BLE001 - surface runtime dependency failures to the UI
            self._show_error(
                "Answer failed",
                exc,
                "Embedding model failed to load while answering. "
                "Verify torch and sentence-transformers are installed correctly.",
            )
            return
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

    def _clear_chat(self) -> None:
        if (
            QtWidgets.QMessageBox.question(
                self,
                "Clear chat",
                "Clear all chat history?",
            )
            == QtWidgets.QMessageBox.StandardButton.Yes
        ):
            self.assistant.clear_chat()
            self.response.clear()
            self.memory.clear()
            self.heatmap_box_files.clear()
            self.heatmap_box_core.clear()
            self._refresh_pinned_panel()

    def _export_chat(self) -> None:
        messages = self.assistant.chat_store.load()
        if not messages:
            QtWidgets.QMessageBox.information(self, "Save chat", "No chat history to save.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save chat history",
            "chat_history.json",
            "JSON Files (*.json)",
        )
        if not path:
            return
        Path(path).write_text(
            json.dumps(messages, indent=2),
            encoding="utf-8",
        )

    def _show_error(self, title: str, exc: Exception, message: str) -> None:
        dialog = QtWidgets.QMessageBox(self)
        dialog.setIcon(QtWidgets.QMessageBox.Icon.Critical)
        dialog.setWindowTitle(title)
        dialog.setText(message)
        dialog.setDetailedText("".join(traceback.format_exception(exc)))
        dialog.exec()


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    window = VectorQtApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
