# Vector Assistant (Best-Design Spec)

## Goal
Build a **local-first desktop AI assistant** that helps traders and developers explore large codebases and documents using natural language, while maximizing **privacy, reproducibility, and auditability**.

## Design Principles
- **Local-first memory**: parsing, embeddings, and retrieval run locally; only prompt context is sent to the LLM.
- **Deterministic + observable**: every retrieval step is explainable with explicit metadata and logged decisions.
- **Reproducible indexing**: embedding model + chunking parameters are versioned and tracked alongside the index.
- **Strict boundaries**: separate ingestion/indexing, retrieval, and UI/control-plane concerns.
- **Config-first**: all behavior is configuration-driven; no silent mutation of live config.

---

## Architecture (Best Design)
| Layer | Responsibility | Notes |
| --- | --- | --- |
| GUI | Desktop UI for queries, memory inspection, and controls | Tkinter-based UI for local operation |
| Ingestion | Parse supported formats, normalize text, chunk content | Deterministic and versioned |
| Embedding | Local dense embeddings | Model configurable via config |
| Retrieval | **Hybrid retrieval**: lexical + dense → merge → rerank | Designed for high recall + auditability |
| Reranking | Learned or deterministic rerankers with explicit constraints | Configurable weights & policy rules |
| Evaluation | Golden query sets + metrics (Recall@K/MRR/nDCG) | Regression gating + drift monitoring |
| Storage | Local vector index + metadata | Versioned and auditable |

---

## Core Modules (Current Repo Map)
- `app.py`: GUI entrypoint
- `assistant.py`: Orchestrates query → retrieval → prompt assembly
- `memory_engine.py`: Embedding, indexing, retrieval primitives
- `indexing_pipeline.py`: Deterministic ingestion pipeline
- `semantic_chunker.py`: Chunking utilities
- `embedding_enrichment.py`: Optional embedding enrichment
- `config.py`: All configuration (models, limits, paths)

> **Note:** File editing/refactor tooling is intentionally **removed** from this design scope.

---

## Retrieval Pipeline (Target State)
1. **Ingestion**
   - Parse supported formats (txt, md, pdf, docx, xlsx, pptx, json)
   - Normalize + deduplicate
2. **Chunking**
   - Heading-aware semantic chunking
   - Multi-granularity support (section + paragraph + sentence)
3. **Embedding**
   - Local embeddings (configurable model)
   - Embedding provenance saved with the index
4. **Hybrid Retrieval**
   - Dense retrieval (vector index)
   - Lexical retrieval (BM25/FTS)
   - Merge + dedupe (e.g., RRF)
5. **Reranking**
   - Deterministic reranker by default
   - Optional learned cross-encoder
   - Constraint rules (e.g., prefer peer-reviewed sources)
6. **Prompt Assembly**
   - Retrieved context is injected in a structured, inspectable format
   - Pinned context is always applied
7. **Evaluation & Drift Monitoring**
   - Golden query sets
   - Recall@K/MRR/nDCG metrics
   - Embedding drift detection and regression alerts

---

## Memory & Querying (Guaranteed Behaviors)
- **Local embeddings + local retrieval**
- **Top-k retrieval is injected into the prompt**
- **Debug view shows exactly what was used**
- **Pinned context is always preserved**
- **Memory can be toggled on/off**

---

## Privacy & Cost Efficiency
- Parsing, embedding, and retrieval remain local
- Only the prompt + selected context is sent to the LLM

---

## Running the App
```bash
python app.py
```

---

## Roadmap (Near-Term)
1. Add evaluation harness + golden query sets
2. Add index provenance + config hashes
3. Add lexical retrieval + hybrid merge strategy
4. Add learned reranker with policy constraints
5. Add drift monitoring and regression gating

---

## Non-Goals (Explicit)
- **No automated code editing or refactor execution**
- **No cloud-based embeddings or vector storage**
- **No silent config mutation**

---

## Summary
Vector Assistant is a **local-first, retrieval-augmented desktop assistant** focused on **privacy, auditability, and reproducibility**. The design prioritizes hybrid retrieval, explicit metadata, and evaluation-driven iteration.
