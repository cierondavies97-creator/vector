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
