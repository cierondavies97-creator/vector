from __future__ import annotations

import re
from typing import Iterable

# concepts.py

"""
Tier-3 semantic concept registry.
These are canonical domain ideas.
"""

CONCEPTS = {
    "buyer_liquidity": {
        "keywords": {"buyer", "liquidity", "demand"},
        "sections": {"liquidity", "market depth"},
    },
    "seller_liquidity": {
        "keywords": {"seller", "liquidity", "supply"},
        "sections": {"liquidity", "market depth"},
    },
    "market_imbalance": {
        "keywords": {"imbalance", "asymmetry"},
        "sections": {"order flow", "market structure"},
    },
    "price_discovery": {
        "keywords": {"price", "discovery"},
        "sections": {"pricing", "market structure"},
    },
}


def _normalize_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip().lower()


def _iter_sections(section_path: Iterable[str] | None) -> list[str]:
    if not section_path:
        return []
    return [s.strip().lower() for s in section_path if s and s.strip()]


def _keyword_present(haystack: str, keyword: str) -> bool:
    if not haystack or not keyword:
        return False
    pattern = r"\b" + re.escape(keyword.lower()) + r"\b"
    return re.search(pattern, haystack) is not None


def infer_semantic_tags(
    *,
    text: str,
    heading: str | None = None,
    section_path: Iterable[str] | None = None,
) -> list[str]:
    """
    Deterministic concept + keyword tagging for a chunk.
    """
    combined = " ".join(
        part for part in [_normalize_text(heading), _normalize_text(text)] if part
    )
    sections = _iter_sections(section_path)

    tags: set[str] = set()

    for name, rule in CONCEPTS.items():
        keywords = rule.get("keywords", set()) or set()
        sections_rule = {s.lower() for s in (rule.get("sections", set()) or set())}

        keyword_hits = {kw for kw in keywords if _keyword_present(combined, kw)}
        section_hit = any(sec in sections_rule for sec in sections)
        heading_hit = any(sec in _normalize_text(heading) for sec in sections_rule)

        if keyword_hits or section_hit or heading_hit:
            tags.add(f"concept:{name}")
            for kw in keyword_hits:
                tags.add(f"keyword:{kw}")

    return sorted(tags)
