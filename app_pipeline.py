
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from config import AppConfig
from memory_engine import MemoryEngine
from indexing_pipeline import IndexingPipeline, ProgressSink, ProgressEvent, Stage


class IndexStatusWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Indexing Pipeline")
        self.geometry("520x300")
        self.transient(parent)
        self.grab_set()

        self.stage = tk.StringVar(value="Idle")
        self.file = tk.StringVar(value="")

        tk.Label(self, textvariable=self.stage).pack(anchor="w", padx=10, pady=5)

        self.progress = ttk.Progressbar(self, length=460)
        self.progress.pack(padx=10, pady=5)

        tk.Label(self, textvariable=self.file).pack(anchor="w", padx=10)

        self.log = tk.Text(self, height=8)
        self.log.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

    def update(self, event: ProgressEvent):
        self.stage.set(event.stage.value)
        if event.total:
            self.progress["maximum"] = event.total
            self.progress["value"] = event.current
        if event.file:
            self.file.set(event.file)
        if event.debug:
            self.log.insert(tk.END, event.message + "\\n")
            self.log.see(tk.END)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Vector Pipeline Demo")
        self.geometry("600x200")

        self.config = AppConfig.load()
        self.memory = MemoryEngine(self.config)

        self.queue = queue.Queue()

        tk.Button(self, text="Choose Directory", command=self.choose).pack(pady=20)

    def choose(self):
        d = filedialog.askdirectory()
        if not d:
            return

        win = IndexStatusWindow(self)
        pipeline = IndexingPipeline(
            self.memory,
            self.config.knowledge_base_path()
        )

        sink = ProgressSink(lambda e: self.queue.put(e))

        def worker():
            pipeline.run(Path(d), sink)

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, lambda: self.poll(win))

    def poll(self, win):
        try:
            while True:
                event = self.queue.get_nowait()
                win.update(event)
        except queue.Empty:
            pass
        self.after(100, lambda: self.poll(win))


if __name__ == "__main__":
    App().mainloop()
