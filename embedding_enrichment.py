def enrich_for_embedding(*, text: str, kind: str, source: str) -> str:
    """
    Add lightweight semantic metadata before embedding.
    """
    return f"""TYPE: {kind}
SOURCE: {source}

CONTENT:
{text}
""".strip()
