from __future__ import annotations

import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from config import AppConfig
from assistant import Assistant
from memory_engine import MemoryEngine
from indexing_pipeline import IndexingPipeline, ProgressSink, ProgressEvent


class VectorApp(tk.Tk):
    def __init__(
        self,
        config: AppConfig,
        memory_engine: MemoryEngine,
        assistant: Assistant,
    ):
        super().__init__()
        self.title("Vector Assistant")
        self.geometry("1200x800")

        self.config = config
        self.memory_engine = memory_engine
        self.assistant = assistant

        self.queue = queue.Queue()
        self.pipeline = None

        self._build_ui()

    def _build_ui(self):
        tk.Button(self, text="Choose Directory", command=self.choose).pack()
        tk.Button(self, text="Reindex", command=self.reindex).pack()

        self.query = tk.Text(self, height=4)
        self.query.pack(fill=tk.X)

        tk.Button(self, text="Ask", command=self.ask).pack()

        self.response = tk.Text(self)
        self.response.pack(fill=tk.BOTH, expand=True)

    def choose(self):
        d = filedialog.askdirectory()
        if d:
            self.config = self.config.with_workspace(d)

    def reindex(self):
        if not self.config.workspace_path:
            messagebox.showwarning("Missing directory", "Choose directory first")
            return

        self.pipeline = IndexingPipeline(self.config, self.memory_engine)
        threading.Thread(
            target=self.pipeline.run,
            args=(Path(self.config.workspace_path), ProgressSink(lambda e: None)),
            daemon=True,
        ).start()

    def ask(self):
        q = self.query.get("1.0", tk.END).strip()
        if not q:
            return
        answer, _, _ = self.assistant.answer(q)
        self.response.delete("1.0", tk.END)
        self.response.insert(tk.END, answer)
