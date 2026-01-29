from __future__ import annotations
from typing import List, Dict, Any
from pathlib import Path
from collections import defaultdict
from dataclasses import replace

from openai import OpenAI

from config import AppConfig
from memory_engine import MemoryEngine, MemoryChunk, TokenStats, RetrievedItem
from reranker import Reranker
from chat_store import ChatStore
from concepts import CONCEPTS
from cycle_state import CycleState


class Assistant:
    def __init__(self, config: AppConfig, memory_engine: MemoryEngine):
        self.config = config
        self.memory_engine = memory_engine

        self.client = OpenAI()
        self.model = config.chat_model

        kb = Path(config.knowledge_base_path())
        self.chat_store = ChatStore(kb / "chat" / "history.json")

        self.enable_reranker = True
        self.reranker = Reranker()

        # ==================================================
        # Context (cycle-free intelligence layer)
        # ==================================================

        self.context_pins: Dict[str, Dict[str, RetrievedItem]] = {
            "file": {},
            "memory_core": {},
        }
        self.context_pinned_files: List[str] = []
        self.context_pinned_file_chunks: Dict[str, List[RetrievedItem]] = {}

        # ==================================================
        # Workspace authority (cycle-gated)
        # ==================================================

        self.active_cycle: CycleState | None = None

    # ==================================================
    # Backward-compatible UI proxies
    # ==================================================

    @property
    def pinned_files(self) -> List[str]:
        return list(self.context_pinned_files)

    @property
    def session_pins(self) -> Dict[str, Dict[str, RetrievedItem]]:
        return self.context_pins

    # ==================================================
    # Cycle API (authority only)
    # ==================================================

    def start_cycle(self, name: str) -> None:
        if not self.config.workspace_path:
            raise RuntimeError("Workspace must be set before starting a cycle")

        if self.active_cycle and self.active_cycle.status == "active":
            raise RuntimeError("A cycle is already active")

        cycle = CycleState(name=name)
        cycle.start()
        cycle.lock_workspace_root(self.config.workspace_path)

        self.active_cycle = cycle

    def discard_cycle(self) -> None:
        if not self.active_cycle:
            return
        self.active_cycle.discard()
        self.active_cycle = None

    def commit_cycle(self) -> None:
        if not self.active_cycle:
            raise RuntimeError("No active cycle")
        self.active_cycle.commit()
        self.active_cycle = None

    # ==================================================
    # Guard (workspace mutation only)
    # ==================================================

    def _require_cycle(self) -> CycleState:
        if not self.active_cycle or self.active_cycle.status != "active":
            raise RuntimeError("No active cycle")
        return self.active_cycle

    # =====================================================
    # Pin API (ALWAYS AVAILABLE — cycle-free)
    # =====================================================

    def pin_item(self, item: RetrievedItem) -> None:
        self.context_pins[item.namespace][item.chunk_id] = item

    def unpin_item(self, item: RetrievedItem) -> None:
        self.context_pins[item.namespace].pop(item.chunk_id, None)

    def pin_file(self, path: str) -> None:
        if path in self.context_pinned_files:
            return

        chunks = self.memory_engine.debug_search_files(path, top_k=1000)
        if not chunks:
            return

        self.context_pinned_files.append(path)
        self.context_pinned_file_chunks[path] = chunks

    def unpin_file(self, path: str) -> None:
        if path in self.context_pinned_files:
            self.context_pinned_files.remove(path)
        self.context_pinned_file_chunks.pop(path, None)

    def move_pinned_file(self, path: str, direction: int) -> None:
        if path not in self.context_pinned_files:
            return

        idx = self.context_pinned_files.index(path)
        new_idx = idx + direction

        if 0 <= new_idx < len(self.context_pinned_files):
            self.context_pinned_files[idx], self.context_pinned_files[new_idx] = (
                self.context_pinned_files[new_idx],
                self.context_pinned_files[idx],
            )

    # =====================================================
    # Pinned context assembly
    # =====================================================

    def _all_pinned_items(self) -> List[RetrievedItem]:
        items: list[RetrievedItem] = []

        for path in self.context_pinned_files:
            items.extend(self.context_pinned_file_chunks.get(path, []))

        items.extend(self.context_pins["file"].values())
        items.extend(self.context_pins["memory_core"].values())

        return items

    # =====================================================
    # Query rewrite / inference
    # =====================================================

    def _rewrite_query_for_search(self, query: str) -> str:
        try:
            r = self.client.responses.create(
                model=self.model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "Rewrite the user query to optimize vector search. "
                            "Focus on intent, concepts, and technical meaning."
                        ),
                    },
                    {"role": "user", "content": query},
                ],
                temperature=0.0,
            )
            return r.output_text.strip() or query
        except Exception:
            return query

    def _infer_query_concepts(self, query: str) -> List[str]:
        q = query.lower()
        inferred: list[str] = []

        for name, rule in CONCEPTS.items():
            keywords = rule.get("keywords", [])
            if any(k in q for k in keywords):
                inferred.append(f"concept:{name}")

        return inferred

    def _build_concept_heatmap(
        self, items: List[RetrievedItem]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Explainable concept heatmap.

        - Uses explicit concept:* tags only
        - Weight = 1 / rank (documented, stable)
        - Normalized by max observed dominance
        - Contributors are explicit chunk_ids
        """

        from collections import defaultdict

        raw_scores: Dict[str, float] = defaultdict(float)
        contributors: Dict[str, list[str]] = defaultdict(list)

        for item in items:
            tags = (item.metadata or {}).get("tags", [])
            rank = item.rank if item.rank and item.rank > 0 else 1
            weight = 1.0 / rank

            for t in tags:
                if t.startswith("concept:"):
                    raw_scores[t] += weight
                    contributors[t].append(item.chunk_id)

        if not raw_scores:
            return {}

        max_score = max(raw_scores.values()) or 1.0

        heatmap: Dict[str, Dict[str, Any]] = {}
        for concept, score in sorted(
            raw_scores.items(), key=lambda x: x[1], reverse=True
        ):
            heatmap[concept] = {
                "normalized_dominance": round(score / max_score, 4),
                "raw_dominance": round(score, 4),
                "weighting_rule": "sum(1 / rank)",
                "contributing_chunks": contributors[concept],
            }

        return heatmap



    # =====================================================
    # Answer (cycle-free intelligence)
    # =====================================================

    def answer(
        self,
        query: str,
        *,
        use_memory: bool = True,
        use_memory_core: bool = True,
    ) -> tuple[str, List[MemoryChunk], TokenStats, Dict[str, Any]]:

        # -------------------------------------------------
        # Tier 3 — Query rewrite + concept inference
        # -------------------------------------------------

        search_query = self._rewrite_query_for_search(query)
        query_concepts = self._infer_query_concepts(search_query)

        # -------------------------------------------------
        # Tier 1 / Tier 2 — Retrieval
        # -------------------------------------------------

        retrieved: list[RetrievedItem] = []

        if use_memory:
            retrieved.extend(
                self.memory_engine.debug_search_files(
                    search_query,
                    top_k=30,
                )
            )

        if use_memory_core:
            retrieved.extend(
                self.memory_engine.debug_search_memory_core(
                    query,
                    top_k=15,
                )
            )

        # -------------------------------------------------
        # Tier 3 — Reranking / semantic weighting
        # -------------------------------------------------

        if self.enable_reranker and retrieved:
            retrieved = self.reranker.rerank(
                retrieved,
                query_concepts=query_concepts,
            )

        # -------------------------------------------------
        # Namespace split (UI + debug)
        # -------------------------------------------------

        file_items = [i for i in retrieved if i.namespace == "file"]
        core_items = [i for i in retrieved if i.namespace == "memory_core"]

        # -------------------------------------------------
        # Pinned context (cycle-free)
        # -------------------------------------------------

        pinned_items = self._all_pinned_items()

        # -------------------------------------------------
        # Concept heatmap (explainable)
        # -------------------------------------------------

        concept_heatmap = self._build_concept_heatmap(retrieved)

        def _rerank_within_namespace(items: list[RetrievedItem]) -> list[RetrievedItem]:
            return [replace(item, rank=idx) for idx, item in enumerate(items, start=1)]

        concept_heatmap_files = self._build_concept_heatmap(
            _rerank_within_namespace(file_items)
        )
        concept_heatmap_memory_core = self._build_concept_heatmap(
            _rerank_within_namespace(core_items)
        )

        # -------------------------------------------------
        # Prompt assembly
        # -------------------------------------------------

        messages = [{"role": "system", "content": "You are an expert assistant."}]
        messages.extend(self.chat_store.load())

        if pinned_items:
            ctx = "\n\n".join(f"[PINNED]\n{i.text}" for i in pinned_items)
            messages.append(
                {
                    "role": "system",
                    "content": f"Pinned context (always apply):\n{ctx}",
                }
            )

        messages.append({"role": "user", "content": query})

        # -------------------------------------------------
        # LLM call
        # -------------------------------------------------

        resp = self.client.responses.create(
            model=self.model,
            input=messages,
            temperature=0.2,
        )

        output = resp.output_text.strip()

        self.chat_store.append_user(query)
        self.chat_store.append_assistant(output)

        # -------------------------------------------------
        # Debug assembly (FULL FIDELITY + TIERS)
        # -------------------------------------------------

        def debug_item(item: RetrievedItem) -> Dict[str, Any]:
            metadata = item.metadata or {}
            tags = metadata.get("tags", [])

            return {
                # Identity
                "namespace": item.namespace,
                "chunk_id": item.chunk_id,
                "source_path": item.source_path,

                # -------------------------------------------------
                # Retrieval (FACTUAL, engine-reported only)
                # -------------------------------------------------
                "retrieval": metadata.get("retrieval", {
                    "score": item.score,
                    "rank": item.rank,
                }),

                # -------------------------------------------------
                # Ranking (post-retrieval ordering only)
                # -------------------------------------------------
                "ranking": {
                    "initial_rank": item.rank,
                    "rerank_delta": metadata.get("rerank_delta"),
                    "final_position": item.rank,
                },

                # -------------------------------------------------
                # Semantic signals (DECLARED TAGS ONLY)
                # -------------------------------------------------
                "semantic_signals": {
                    "concepts": [
                        t.split(":", 1)[1]
                        for t in tags if t.startswith("concept:")
                    ],
                    "keywords": [
                        t.split(":", 1)[1]
                        for t in tags if t.startswith("keyword:")
                    ],
                    "other_tags": [
                        t for t in tags
                        if not t.startswith(("concept:", "keyword:", "path:"))
                    ],
                },

                # -------------------------------------------------
                # Pin state (authoritative)
                # -------------------------------------------------
                "pin_state": {
                    "pinned": item.chunk_id in self.context_pins.get(item.namespace, {}),
                    "pin_scope": "chunk",
                },

                # Content
                "text": item.text,
            }


        debug = {
            # Query diagnostics
            "query": query,
            "rewritten_query": search_query,
            "query_concepts": query_concepts,

            # Retrieval visibility
            "file_memory": [debug_item(i) for i in file_items],
            "memory_core": [debug_item(i) for i in core_items],

            # Pin state
            "pinned_files": list(self.pinned_files),
            "pinned_chunks": {
                "file": list(self.context_pins["file"].keys()),
                "memory_core": list(self.context_pins["memory_core"].keys()),
            },

            # Semantic diagnostics
            "concept_heatmap": concept_heatmap,
            "concept_heatmap_files": concept_heatmap_files,
            "concept_heatmap_memory_core": concept_heatmap_memory_core,
        }

        stats = TokenStats(0, 0, 0.0)
        return output, [], stats, debug



    # =====================================================
    # Chat control
    # =====================================================

    def clear_chat(self):
        self.chat_store.clear()
        self.context_pins = {"file": {}, "memory_core": {}}
        self.context_pinned_files.clear()
        self.context_pinned_file_chunks.clear()
