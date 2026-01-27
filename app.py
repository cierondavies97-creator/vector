import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from assistant import Assistant
from config import AppConfig
from indexing_pipeline import IndexingPipeline, ProgressSink, ProgressEvent
from memory_engine import MemoryEngine, RetrievedItem


# ============================================================
# Index Status Popup
# ============================================================

class IndexStatusWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Indexing Progress")
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
        if not self.winfo_exists():
            return

        self.stage.set(event.stage.value)
        if event.total:
            self.progress["maximum"] = event.total
            self.progress["value"] = event.current
        if event.file:
            self.file.set(event.file)
        if event.debug:
            self.log.insert(tk.END, event.message + "\n")
            self.log.see(tk.END)


# ============================================================
# Main App
# ============================================================

class VectorApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Vector Assistant")
        self.geometry("1450x900")

        self.config = AppConfig.load()
        self.memory_engine = MemoryEngine(self.config)
        self.assistant = Assistant(self.config, self.memory_engine)

        self.queue: queue.Queue[ProgressEvent] = queue.Queue()
        self.pipeline: IndexingPipeline | None = None

        self.use_memory = tk.BooleanVar(value=True)
        self.use_memory_core = tk.BooleanVar(value=True)

        self.last_debug: dict = {}

        self._pin_tag_map: dict[str, RetrievedItem] = {}
        self._ctx_item: RetrievedItem | None = None

        self._build_ui()
        self._load_chat_history()
        self._update_cycle_status()

    # ========================================================
    # UI
    # ========================================================

    def _build_ui(self):
        # ---------- Menu ----------
        menubar = tk.Menu(self)
        self.configure(menu=menubar)

        chat_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Chat", menu=chat_menu)
        chat_menu.add_command(label="Clear Chat", command=self._clear_chat)
        chat_menu.add_command(
            label="Summarize Chat → Memory Core",
            command=self._summarize_chat_to_memory,
        )

        # ---------- Top bar ----------
        top = tk.Frame(self)
        top.pack(fill=tk.X, padx=8, pady=4)

        tk.Button(top, text="Choose Directory", command=self._choose_dir).pack(side=tk.LEFT)
        tk.Button(top, text="Reindex", command=self._reindex).pack(side=tk.LEFT, padx=4)
        tk.Button(top, text="Cancel Indexing", command=self._cancel).pack(side=tk.LEFT, padx=4)

        tk.Button(top, text="📌 Pin File…", command=self._pin_file_browser).pack(side=tk.LEFT, padx=10)

        tk.Checkbutton(top, text="Use Knowledge Base", variable=self.use_memory).pack(side=tk.LEFT, padx=12)
        tk.Checkbutton(top, text="Use Memory Core", variable=self.use_memory_core).pack(side=tk.LEFT, padx=6)

        # ---------- Cycle status bar ----------
        cycle_bar = tk.Frame(self)
        cycle_bar.pack(fill=tk.X, padx=8, pady=(0, 6))

        self.cycle_status = tk.StringVar(value="🟡 No active cycle")
        tk.Label(cycle_bar, textvariable=self.cycle_status, anchor="w").pack(fill=tk.X)

        # ---------- Main ----------
        main = tk.Frame(self)
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # ---------- Left column ----------
        tk.Label(main, text="Query").grid(row=0, column=0, sticky="w")
        self.query = tk.Text(main, height=4)
        self.query.grid(row=1, column=0, sticky="nsew")

        tk.Button(main, text="Ask", command=self._ask).grid(row=1, column=1, padx=6)

        tk.Label(main, text="Response").grid(row=2, column=0, sticky="w")
        self.response = tk.Text(main)
        self.response.grid(row=3, column=0, sticky="nsew")

        # ---------- Right column ----------
        right = tk.Frame(main)
        right.grid(row=0, column=2, rowspan=6, sticky="nsew", padx=(8, 0))

        tk.Label(right, text="📌 Pinned Files (Context)").pack(anchor="w")
        self.pinned_list = tk.Listbox(right, height=8)
        self.pinned_list.pack(fill=tk.X)

        btns = tk.Frame(right)
        btns.pack(fill=tk.X, pady=4)

        tk.Button(btns, text="↑", width=3, command=lambda: self._move_pin(-1)).pack(side=tk.LEFT)
        tk.Button(btns, text="↓", width=3, command=lambda: self._move_pin(1)).pack(side=tk.LEFT, padx=2)
        tk.Button(btns, text="Unpin", command=self._unpin_selected).pack(side=tk.LEFT, padx=6)

        tk.Label(right, text="Injected Context (Debug)").pack(anchor="w", pady=(8, 0))
        self.memory = tk.Text(right, width=55)
        self.memory.pack(fill=tk.BOTH, expand=True)
        self.memory.tag_configure("pin", foreground="blue", underline=True)
        self.memory.bind("<Button-1>", self._on_left_click)
        self.memory.bind("<Button-3>", self._on_right_click)

        tk.Label(right, text="Concept Heatmap").pack(anchor="w", pady=(6, 0))
        self.heatmap_box = tk.Text(right, height=6)
        self.heatmap_box.pack(fill=tk.X)

        main.columnconfigure(0, weight=3)
        main.columnconfigure(2, weight=2)
        main.rowconfigure(3, weight=1)

        self.context_menu = tk.Menu(self, tearoff=0)
        self.context_menu.add_command(label="📌 Pin / Unpin Item", command=self._ctx_toggle_pin)
        self.context_menu.add_command(label="📌 Pin Entire File", command=self._ctx_pin_file)

    # ========================================================
    # Cycle status
    # ========================================================

    def _update_cycle_status(self):
        cycle = self.assistant.active_cycle
        if not cycle:
            self.cycle_status.set("🟡 No active cycle (context-only mode)")
            return

        staged = len(cycle.staged_edits)
        self.cycle_status.set(
            f"🟢 Cycle: {cycle.name} | Status: {cycle.status} | Staged: {staged}"
        )

    # ========================================================
    # Pin panel helpers (cycle-free)
    # ========================================================

    def _refresh_pinned_panel(self):
        self.pinned_list.delete(0, tk.END)
        for p in self.assistant.pinned_files:
            self.pinned_list.insert(tk.END, p)
        self._update_cycle_status()

    def _move_pin(self, direction: int):
        sel = self.pinned_list.curselection()
        if not sel:
            return
        path = self.pinned_list.get(sel[0])
        self.assistant.move_pinned_file(path, direction)
        self._refresh_pinned_panel()
        self._render_debug()

    def _unpin_selected(self):
        sel = self.pinned_list.curselection()
        if not sel:
            return
        path = self.pinned_list.get(sel[0])
        self.assistant.unpin_file(path)
        self._refresh_pinned_panel()
        self._render_debug()

    # ========================================================
    # Pin interactions
    # ========================================================

    def _pin_file_browser(self):
        path = filedialog.askopenfilename()
        if path:
            self.assistant.pin_file(path)
            self._refresh_pinned_panel()
            self._render_debug()

    def _on_left_click(self, event):
        index = self.memory.index(f"@{event.x},{event.y}")
        for tag in self.memory.tag_names(index):
            if tag.startswith("pin:"):
                item = self._pin_tag_map.get(tag)
                if item:
                    self._toggle_pin(item)
                    self._render_debug()
                return

    def _on_right_click(self, event):
        self._ctx_item = None
        index = self.memory.index(f"@{event.x},{event.y}")
        for tag in self.memory.tag_names(index):
            if tag.startswith("pin:"):
                self._ctx_item = self._pin_tag_map.get(tag)
                break
        if self._ctx_item:
            self.context_menu.tk_popup(event.x_root, event.y_root)

    def _toggle_pin(self, item: dict):
        namespace = item["namespace"]
        chunk_id = item["chunk_id"]

        if chunk_id in self.assistant.session_pins.get(namespace, {}):
            self.assistant.unpin_item_by_id(namespace, chunk_id)
        else:
            self.assistant.pin_item_by_id(namespace, chunk_id)


    def _ctx_toggle_pin(self):
        if self._ctx_item:
            self._toggle_pin(self._ctx_item)
            self._render_debug()

    def _ctx_pin_file(self):
        if self._ctx_item and self._ctx_item.namespace == "file":
            self.assistant.pin_file(self._ctx_item.source_path)
            self._refresh_pinned_panel()
            self._render_debug()

    # ========================================================
    # Indexing / Chat / Debug
    # ========================================================

    def _choose_dir(self):
        d = filedialog.askdirectory()
        if not d:
            return

        self.config = self.config.with_workspace(d)
        messagebox.showinfo("Workspace set", d)
        self._update_cycle_status()

    def _reindex(self):
        if not self.config.workspace_path:
            messagebox.showwarning("Missing directory", "Choose a directory first")
            return

        popup = IndexStatusWindow(self)
        self.pipeline = IndexingPipeline(
            self.memory_engine,
            self.config.knowledge_base_path(),
            chunk_size=self.config.chunk_size,
            overlap=self.config.chunk_overlap,
        )

        sink = ProgressSink(lambda e: self.queue.put(e))
        threading.Thread(
            target=lambda: self.pipeline.run(Path(self.config.workspace_path), sink),
            daemon=True,
        ).start()
        self.after(100, lambda: self._poll(popup))

    def _cancel(self):
        if self.pipeline:
            self.pipeline.cancel()

    def _poll(self, popup):
        if not popup.winfo_exists():
            return
        try:
            while True:
                popup.update(self.queue.get_nowait())
        except queue.Empty:
            pass
        self.after(100, lambda: self._poll(popup))

    def _ask(self):
        q = self.query.get("1.0", tk.END).strip()
        if not q:
            return

        response, _, _, debug = self.assistant.answer(
            q,
            use_memory=self.use_memory.get(),
            use_memory_core=self.use_memory_core.get(),
        )

        self.last_debug = debug or {}

        self.response.insert(tk.END, f"\n🧑 You:\n{q}\n")
        self.response.insert(tk.END, f"\n🤖 Assistant:\n{response}\n")
        self.response.see(tk.END)
        self.query.delete("1.0", tk.END)

        self._refresh_pinned_panel()
        self._render_debug()
        self._render_concept_heatmap()

    # ========================================================
    # Rendering
    # ========================================================

    def _render_debug(self):
        self.memory.delete("1.0", tk.END)
        self._pin_tag_map.clear()

        debug = self.last_debug or {}

        # ===============================
        # Header
        # ===============================
        self.memory.insert(
            tk.END,
            "Query Rewrite\n"
            f"  Original : {debug.get('query')}\n"
            f"  Rewritten: {debug.get('rewritten_query')}\n\n"
        )

        def insert_item(item: dict):
            namespace = item["namespace"]
            chunk_id = item["chunk_id"]

            pinned = chunk_id in self.assistant.session_pins.get(namespace, {})
            marker = "[PIN]" if pinned else "[ ]"

            tag = f"pin:{namespace}:{chunk_id}"
            self._pin_tag_map[tag] = item

            # -------------------------------
            # Clickable header line ONLY
            # -------------------------------
            start = self.memory.index(tk.END)
            self.memory.insert(
                tk.END,
                f"{marker} {item.get('source_path', '')} "
                f"(score={item.get('score', 0):.3f}, rank={item.get('rank')})\n"
            )
            end = self.memory.index(tk.END)

            # Apply pin tag ONLY to header line
            self.memory.tag_add(tag, start, end)
            self.memory.tag_add("pin", start, end)

            # -------------------------------
            # Rerank diagnostics
            # -------------------------------
            if item.get("rerank_delta") is not None:
                delta = item["rerank_delta"]
                self.memory.insert(
                    tk.END,
                    f"  Rerank delta: {delta:+.3f}\n"
                )

            # -------------------------------
            # Tag grouping (plain text)
            # -------------------------------
            tags = item.get("tags", [])
            groups = {
                "concept": [],
                "keyword": [],
                "path": [],
                "meta": [],
            }

            for t in tags:
                if ":" in t:
                    prefix, value = t.split(":", 1)
                    if prefix in groups:
                        groups[prefix].append(value)
                    else:
                        groups["meta"].append(t)
                else:
                    groups["meta"].append(t)

            if groups["concept"]:
                self.memory.insert(tk.END, "  Concepts:\n")
                for c in groups["concept"]:
                    self.memory.insert(tk.END, f"    - {c}\n")

            if groups["keyword"]:
                self.memory.insert(tk.END, "  Keywords:\n")
                for k in groups["keyword"]:
                    self.memory.insert(tk.END, f"    - {k}\n")

            # -------------------------------
            # Paths (ordered, reconstructed)
            # -------------------------------
            if groups["path"]:
                self.memory.insert(tk.END, "  Paths:\n")

                path_parts = groups["path"]

                for i, part in enumerate(path_parts):
                    is_last = i == len(path_parts) - 1
                    suffix = "" if is_last else "/"
                    self.memory.insert(
                        tk.END,
                        f"    - {part}{suffix}\n"
                    )


            if groups["meta"]:
                self.memory.insert(tk.END, "  Metadata:\n")
                for m in groups["meta"]:
                    self.memory.insert(tk.END, f"    - {m}\n")

            # -------------------------------
            # Content
            # -------------------------------
            self.memory.insert(tk.END, "\n")
            self.memory.insert(tk.END, f"{item['text']}\n\n")

        # ===============================
        # MEMORY CORE
        # ===============================
        memory_core = debug.get("memory_core", [])
        if memory_core:
            self.memory.insert(tk.END, "MEMORY CORE\n\n")
            for item in memory_core:
                insert_item(item)

        # ===============================
        # KNOWLEDGE BASE
        # ===============================
        file_memory = debug.get("file_memory", [])
        if file_memory:
            self.memory.insert(tk.END, "KNOWLEDGE BASE\n\n")
            for item in file_memory:
                insert_item(item)





    def _render_concept_heatmap(self):
        self.heatmap_box.delete("1.0", tk.END)
        heatmap = self.last_debug.get("concept_heatmap") or {}
        if not heatmap:
            self.heatmap_box.insert(tk.END, "No semantic concepts triggered.\n")
            return
        for c, s in heatmap.items():
            self.heatmap_box.insert(
                tk.END,
                f"{c.replace('concept:', ''):<25} {'█' * int(s * 10)} {s:.2f}\n"
            )

    # ========================================================
    # Chat control
    # ========================================================

    def _load_chat_history(self):
        for m in self.assistant.chat_store.load():
            role = "🧑 You" if m["role"] == "user" else "🤖 Assistant"
            self.response.insert(tk.END, f"\n{role}:\n{m['content']}\n")

    def _clear_chat(self):
        if messagebox.askyesno("Clear chat", "Clear all chat history?"):
            self.assistant.clear_chat()
            self.response.delete("1.0", tk.END)
            self.memory.delete("1.0", tk.END)
            self.heatmap_box.delete("1.0", tk.END)
            self._refresh_pinned_panel()

    def _summarize_chat_to_memory(self):
        summary = self.assistant.summarize_chat_to_memory()
        messagebox.showinfo(
            "Memory Core",
            summary if summary else "Nothing to summarize.",
        )


if __name__ == "__main__":
    VectorApp().mainloop()
