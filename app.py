"""Tkinter GUI entrypoint for the Vector AI Trading Assistant."""

import difflib
import importlib
import importlib.util
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

_tkdnd_spec = importlib.util.find_spec("tkinterdnd2")
if _tkdnd_spec is not None:
    _tkdnd_module = importlib.import_module("tkinterdnd2")
    DND_FILES = _tkdnd_module.DND_FILES
    TkinterDnD = _tkdnd_module.TkinterDnD
else:  # pragma: no cover - optional dependency
    DND_FILES = None
    TkinterDnD = None

from assistant import Assistant
from config import AppConfig
from editor_engine import EditorEngine
from file_handler import FileHandler
from memory_engine import MemoryEngine
from test_runner import TestRunner


class VectorApp(tk.Tk if TkinterDnD is None else TkinterDnD.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Vector AI Trading Assistant")
        self.geometry("1200x800")

        self.config = AppConfig.load()
        self.memory_engine = MemoryEngine(self.config)
        self.file_handler = FileHandler(self.config, self.memory_engine)
        self.assistant = Assistant(self.config, self.memory_engine)
        self.editor_engine = EditorEngine(TestRunner(self.config))
        self.last_query = ""
        self.last_response = ""
        self.pending_edit: dict[str, str] | None = None

        self._build_ui()
        self._register_drag_and_drop()

    def _build_ui(self) -> None:
        top_frame = tk.Frame(self)
        top_frame.pack(fill=tk.X, padx=8, pady=8)

        self.directory_label = tk.Label(
            top_frame, text="No directory selected (or drag & drop files/folders)"
        )
        self.directory_label.pack(side=tk.LEFT, padx=4)

        choose_button = tk.Button(
            top_frame, text="Choose Directory", command=self._choose_directory
        )
        choose_button.pack(side=tk.LEFT, padx=4)

        self.use_memory_var = tk.BooleanVar(value=True)
        memory_checkbox = tk.Checkbutton(
            top_frame, text="Use Memory", variable=self.use_memory_var
        )
        memory_checkbox.pack(side=tk.LEFT, padx=4)

        reindex_button = tk.Button(top_frame, text="Reindex", command=self._reindex)
        reindex_button.pack(side=tk.LEFT, padx=4)

        cycle_button = tk.Button(top_frame, text="Cycle Memory", command=self._cycle_memory)
        cycle_button.pack(side=tk.LEFT, padx=4)

        clear_button = tk.Button(top_frame, text="Clear Output", command=self._clear_output)
        clear_button.pack(side=tk.LEFT, padx=4)

        save_chat_button = tk.Button(top_frame, text="Save Chat", command=self._save_chat)
        save_chat_button.pack(side=tk.LEFT, padx=4)

        main_frame = tk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        query_label = tk.Label(main_frame, text="Query")
        query_label.grid(row=0, column=0, sticky="w")

        self.query_entry = tk.Text(main_frame, height=4)
        self.query_entry.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)

        ask_button = tk.Button(main_frame, text="Ask", command=self._ask)
        ask_button.grid(row=1, column=1, sticky="n", padx=4)

        response_label = tk.Label(main_frame, text="Response")
        response_label.grid(row=2, column=0, sticky="w")

        self.response_text = tk.Text(main_frame)
        self.response_text.grid(row=3, column=0, sticky="nsew", padx=4, pady=4)

        memory_label = tk.Label(main_frame, text="Memory Viewer")
        memory_label.grid(row=2, column=1, sticky="w")

        self.memory_text = tk.Text(main_frame, width=40)
        self.memory_text.grid(row=3, column=1, sticky="nsew", padx=4, pady=4)

        notes_label = tk.Label(main_frame, text="Notes to Memory")
        notes_label.grid(row=4, column=0, sticky="w")

        self.notes_entry = tk.Text(main_frame, height=4)
        self.notes_entry.grid(row=5, column=0, sticky="nsew", padx=4, pady=4)

        save_note_button = tk.Button(
            main_frame, text="Save Note", command=self._save_note
        )
        save_note_button.grid(row=5, column=1, sticky="n", padx=4)

        edit_label = tk.Label(main_frame, text="Safe Edit (file path + instruction)")
        edit_label.grid(row=6, column=0, sticky="w")

        self.edit_path_entry = tk.Entry(main_frame)
        self.edit_path_entry.grid(row=7, column=0, sticky="nsew", padx=4, pady=4)
        self.edit_path_entry.insert(0, "path/to/file.py")

        self.edit_instruction_entry = tk.Text(main_frame, height=3)
        self.edit_instruction_entry.grid(row=8, column=0, sticky="nsew", padx=4, pady=4)

        edit_button = tk.Button(main_frame, text="Apply Safe Edit", command=self._apply_edit)
        edit_button.grid(row=7, column=1, sticky="n", padx=4)

        preview_button = tk.Button(main_frame, text="Preview Diff", command=self._preview_edit)
        preview_button.grid(row=8, column=1, sticky="n", padx=4)

        diff_label = tk.Label(main_frame, text="Diff Preview")
        diff_label.grid(row=9, column=0, sticky="w")

        self.diff_text = tk.Text(main_frame, height=10)
        self.diff_text.grid(row=10, column=0, columnspan=2, sticky="nsew", padx=4, pady=4)

        self.token_var = tk.StringVar(value="Tokens in: 0 | Tokens out: 0 | Cost: $0.0000")
        token_label = tk.Label(self, textvariable=self.token_var, anchor="w")
        token_label.pack(fill=tk.X, padx=8, pady=2)

        self.status_var = tk.StringVar(value="Ready")
        status_label = tk.Label(self, textvariable=self.status_var, anchor="w")
        status_label.pack(fill=tk.X, padx=8, pady=4)

        main_frame.columnconfigure(0, weight=3)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(3, weight=1)
        main_frame.rowconfigure(8, weight=0)
        main_frame.rowconfigure(10, weight=1)

    def _choose_directory(self) -> None:
        directory = filedialog.askdirectory()
        if directory:
            self.config = self.config.with_workspace(directory)
            self.directory_label.config(text=directory)
            self.status_var.set(f"Selected directory: {directory}")

    def _register_drag_and_drop(self) -> None:
        if TkinterDnD is None or DND_FILES is None:
            self.status_var.set("Drag-and-drop unavailable (install tkinterdnd2).")
            return
        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, event: tk.Event) -> None:
        if not event.data:
            return
        paths = self._parse_drop_data(event.data)
        if not paths:
            return
        self.status_var.set("Indexing dropped items...")
        self.file_handler.ingest_paths(paths)
        self.status_var.set(f"Indexed {len(paths)} dropped items.")

    def _parse_drop_data(self, data: str) -> list[str]:
        if data.startswith("{") and data.endswith("}"):
            data = data[1:-1]
        parts = []
        buffer = ""
        in_brace = False
        for char in data:
            if char == "{":
                in_brace = True
                buffer = ""
            elif char == "}":
                in_brace = False
                if buffer:
                    parts.append(buffer)
                    buffer = ""
            elif char == " " and not in_brace:
                if buffer:
                    parts.append(buffer)
                    buffer = ""
            else:
                buffer += char
        if buffer:
            parts.append(buffer)
        return parts

    def _reindex(self) -> None:
        if not self.config.workspace_path:
            messagebox.showwarning("Missing directory", "Select a directory first.")
            return
        self.status_var.set("Reindexing...")
        self.file_handler.reindex_workspace(self.config.workspace_path)
        self.status_var.set("Reindex complete")

    def _cycle_memory(self) -> None:
        self.memory_engine.rotate_memory()
        self.status_var.set("Rotated memory context")

    def _clear_output(self) -> None:
        self.response_text.delete("1.0", tk.END)
        self.memory_text.delete("1.0", tk.END)

    def _ask(self) -> None:
        query = self.query_entry.get("1.0", tk.END).strip()
        if not query:
            return
        use_memory = self.use_memory_var.get()
        response, memory_chunks, stats = self.assistant.answer(query, use_memory)
        self.last_query = query
        self.last_response = response
        self.response_text.delete("1.0", tk.END)
        self.response_text.insert(tk.END, response)

        self.memory_text.delete("1.0", tk.END)
        for chunk in memory_chunks:
            rank = f"Rank {chunk.rank}" if chunk.rank is not None else "Rank ?"
            score = f"{chunk.score:.4f}" if chunk.score is not None else "n/a"
            self.memory_text.insert(
                tk.END,
                f"{rank} | Score: {score}\n{chunk.source_path}\n{chunk.text}\n\n",
            )

        self.token_var.set(
            f"Tokens in: {stats.input_tokens} | Tokens out: {stats.output_tokens} | Cost: ${stats.estimated_cost:.4f}"
        )
        self.status_var.set("Response generated.")

    def _save_note(self) -> None:
        note = self.notes_entry.get("1.0", tk.END).strip()
        if not note:
            return
        path = self.file_handler.save_note(note)
        self.notes_entry.delete("1.0", tk.END)
        if self.config.workspace_path:
            self.file_handler.reindex_workspace(self.config.workspace_path)
            self.status_var.set(f"Saved note and reindexed: {path}")
        else:
            self.file_handler.ingest_paths([self.file_handler.knowledge_base_path()])
            self.status_var.set(f"Saved note and indexed notes: {path}")

    def _save_chat(self) -> None:
        if not self.last_query or not self.last_response:
            messagebox.showwarning("No chat", "Ask a question first to save the chat.")
            return
        path = self.file_handler.save_chat(self.last_query, self.last_response)
        self.status_var.set(f"Saved chat to {path}")

    def _apply_edit(self) -> None:
        file_path = self.edit_path_entry.get().strip()
        instruction = self.edit_instruction_entry.get("1.0", tk.END).strip()
        if not file_path or not instruction:
            messagebox.showwarning("Missing input", "Provide a file path and instruction.")
            return
        if not self.pending_edit:
            messagebox.showwarning("No preview", "Preview the diff before applying.")
            return
        if (
            self.pending_edit.get("path") != file_path
            or self.pending_edit.get("instruction") != instruction
        ):
            messagebox.showwarning("Stale preview", "Preview is outdated. Regenerate it.")
            return
        self.status_var.set("Running safe edit...")
        result = self.editor_engine.edit_file_with_content(
            file_path, self.pending_edit["updated"]
        )
        self.status_var.set(result.message)
        if result.success:
            self.pending_edit = None
            self.diff_text.delete("1.0", tk.END)

    def _preview_edit(self) -> None:
        file_path = self.edit_path_entry.get().strip()
        instruction = self.edit_instruction_entry.get("1.0", tk.END).strip()
        if not file_path or not instruction:
            messagebox.showwarning("Missing input", "Provide a file path and instruction.")
            return
        try:
            original_content = Path(file_path).read_text(encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Read failed", f"Failed to read file: {exc}")
            return
        self.status_var.set("Generating diff preview...")
        updated_content = self.assistant.propose_edit(original_content, instruction)
        diff = difflib.unified_diff(
            original_content.splitlines(),
            updated_content.splitlines(),
            fromfile=file_path,
            tofile=f"{file_path} (edited)",
            lineterm="",
        )
        diff_text = "\n".join(diff).strip()
        if not diff_text:
            diff_text = "No changes proposed."
        self.diff_text.delete("1.0", tk.END)
        self.diff_text.insert(tk.END, diff_text)
        self.pending_edit = {
            "path": file_path,
            "instruction": instruction,
            "updated": updated_content,
        }
        self.status_var.set("Diff preview ready.")


if __name__ == "__main__":
    app = VectorApp()
    app.mainloop()
