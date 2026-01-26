"""Tkinter GUI entrypoint for the Vector AI Trading Assistant."""

import tkinter as tk
from tkinter import filedialog, messagebox

from assistant import Assistant
from config import AppConfig
from file_handler import FileHandler
from memory_engine import MemoryEngine


class VectorApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Vector AI Trading Assistant")
        self.geometry("1200x800")

        self.config = AppConfig.load()
        self.memory_engine = MemoryEngine(self.config)
        self.file_handler = FileHandler(self.config, self.memory_engine)
        self.assistant = Assistant(self.config, self.memory_engine)

        self._build_ui()

    def _build_ui(self) -> None:
        top_frame = tk.Frame(self)
        top_frame.pack(fill=tk.X, padx=8, pady=8)

        self.directory_label = tk.Label(top_frame, text="No directory selected")
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

        self.status_var = tk.StringVar(value="Ready")
        status_label = tk.Label(self, textvariable=self.status_var, anchor="w")
        status_label.pack(fill=tk.X, padx=8, pady=4)

        main_frame.columnconfigure(0, weight=3)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(3, weight=1)

    def _choose_directory(self) -> None:
        directory = filedialog.askdirectory()
        if directory:
            self.config = self.config.with_workspace(directory)
            self.directory_label.config(text=directory)
            self.status_var.set(f"Selected directory: {directory}")

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
        self.response_text.delete("1.0", tk.END)
        self.response_text.insert(tk.END, response)

        self.memory_text.delete("1.0", tk.END)
        for chunk in memory_chunks:
            self.memory_text.insert(tk.END, f"{chunk.source_path}\n{chunk.text}\n\n")

        self.status_var.set(
            f"Tokens in: {stats.input_tokens} | Tokens out: {stats.output_tokens} | Cost: ${stats.estimated_cost:.4f}"
        )

    def _save_note(self) -> None:
        note = self.notes_entry.get("1.0", tk.END).strip()
        if not note:
            return
        path = self.file_handler.save_note(note)
        self.notes_entry.delete("1.0", tk.END)
        self.status_var.set(f"Saved note to {path}")


if __name__ == "__main__":
    app = VectorApp()
    app.mainloop()
