from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Any

from memory_engine import RetrievedItem


# =========================================================
# Debug score breakdown
# =========================================================

@dataclass
class RerankScore:
    total: float
    semantic: float
    importance: float
    recency: float
    namespace_bias: float
    section_boost: float
    heading_boost: float
    overview_boost: float
    concept_query_boost: float


# =========================================================
# Reranker
# =========================================================

class Reranker:
    """
    Deterministic, explainable reranker.

    FAISS = recall
    Reranker = precision

    Combines:
    - semantic similarity
    - importance weighting
    - recency decay
    - namespace bias (memory core)
    - section-path relevance
    - heading/title relevance
    - overview preference
    - query ↔ concept alignment (Tier-3)
    """

    def __init__(
        self,
        *,
        weight_semantic: float = 1.0,
        weight_importance: float = 0.4,
        weight_recency: float = 0.2,
        memory_core_bias: float = 0.3,
        section_match_boost: float = 0.15,
        heading_match_boost: float = 0.1,
        overview_boost: float = 0.25,
        concept_query_boost: float = 0.3,
    ):
        self.weight_semantic = weight_semantic
        self.weight_importance = weight_importance
        self.weight_recency = weight_recency
        self.memory_core_bias = memory_core_bias
        self.section_match_boost = section_match_boost
        self.heading_match_boost = heading_match_boost
        self.overview_boost = overview_boost
        self.concept_query_boost = concept_query_boost

    # =====================================================
    # Rerank
    # =====================================================

    def rerank(
        self,
        items: List[RetrievedItem],
        *,
        query_concepts: List[str] | None = None,
    ) -> List[RetrievedItem]:

        now = datetime.utcnow()
        scored: list[tuple[RetrievedItem, RerankScore]] = []

        query_concepts_set = set(query_concepts or [])

        for item in items:
            meta: Dict[str, Any] = item.metadata or {}

            # ---------------- semantic ----------------
            semantic = float(item.score)

            # ---------------- importance ----------------
            importance = float(meta.get("importance", 1.0))

            # ---------------- recency ----------------
            recency = 0.0
            created = meta.get("created_at")
            if created:
                try:
                    dt = datetime.fromisoformat(created)
                    days = max((now - dt).days, 0)
                    recency = 1.0 / (1.0 + days / 30.0)
                except Exception:
                    pass

            # ---------------- namespace bias ----------------
            namespace_bias = (
                self.memory_core_bias
                if item.namespace == "memory_core"
                else 0.0
            )

            # ---------------- section-path relevance ----------------
            section_boost = 0.0
            section_path = meta.get("section_path") or []
            if section_path and item.text:
                text_lower = item.text.lower()
                for section in section_path:
                    if section.lower() in text_lower:
                        section_boost = self.section_match_boost
                        break

            # ---------------- heading relevance ----------------
            heading_boost = 0.0
            heading = meta.get("heading")
            if heading and item.text and heading.lower() in item.text.lower():
                heading_boost = self.heading_match_boost

            # ---------------- overview chunk ----------------
            overview = bool(meta.get("is_overview"))
            overview_score = self.overview_boost if overview else 0.0

            # ---------------- query ↔ concept alignment ----------------
            concept_query_boost = 0.0
            item_tags = set(meta.get("tags", []))

            if query_concepts_set and item_tags:
                if item_tags & query_concepts_set:
                    concept_query_boost = self.concept_query_boost

            # ---------------- total ----------------
            total = (
                self.weight_semantic * semantic
                + self.weight_importance * importance
                + self.weight_recency * recency
                + namespace_bias
                + section_boost
                + heading_boost
                + overview_score
                + concept_query_boost
            )

            scored.append(
                (
                    item,
                    RerankScore(
                        total=total,
                        semantic=semantic,
                        importance=importance,
                        recency=recency,
                        namespace_bias=namespace_bias,
                        section_boost=section_boost,
                        heading_boost=heading_boost,
                        overview_boost=overview_score,
                        concept_query_boost=concept_query_boost,
                    ),
                )
            )

        # ---------------- sort ----------------
        scored.sort(key=lambda x: x[1].total, reverse=True)

        # ---------------- attach debug ----------------
        for rank, (item, score) in enumerate(scored, start=1):
            item.rank = rank
            item.metadata["rerank"] = score.__dict__

        return [item for item, _ in scored]
