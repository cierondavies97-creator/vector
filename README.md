This repository describes the consolidated **MARBLE-RAG** pipeline: **Modular + Agentic RAG** with **multimodal ingestion**, **hybrid retrieval**, **knowledge integration**, and a **hybrid reasoning layer** combining **deterministic constraints (Z3)** and **probabilistic Bayesian Networks (pgmpy)**. It is designed for **research/batch** runs and supports **industry-configurable** behavior via **Domain Packs** (construction, finance, trading, macro outlooks, business/market, geopolitics). It keeps agentic behavior bounded with workflow structure to avoid coordination overhead as systems scale [3], while still enabling advanced tool configuration (filters, sorting, structured queries) [5].

LangGraph is ideal for cyclical/stateful workflows, and LlamaIndex is strong for hierarchical/multimodal indexing if you want it for specific modules [4].

---

# 1) Core principle: “Domain-agnostic” = stable core + configurable Domain Packs

## Stable core (never changes across industries)

- Evidence model + provenance
- Ingestion → indexing → retrieval → integration → reasoning → synthesis
- Observability + evaluation + reproducibility

## Domain Pack (industry-configurable plugin)

- Industry ontology (entities/events/claims)
- Source tiers + reliability priors
- Retrieval policy (filters, time horizons, index routing)
- Deterministic constraints (e.g., accounting identities, schedule constraints)
- Bayesian Network templates (causal structures for forecasting/explanations)
- Output templates (RCA report, macro outlook memo, trading thesis, etc.)

This matches the modular approach: swap/optimize components per domain without rewriting the system [2].

---

# 2) Implementation-grade stack (small team, powerful)

## Orchestration / workflow

- **LangGraph** for stateful, cyclical workflows (agentic but controlled) [4]
- Optional: **LlamaIndex** for hierarchical indexes / multimodal document abstractions [4]

## Storage & indexes

- **S3** (raw + extracted artifacts)
- **Postgres** (EvidenceObjects, Claims, Events, Entities, Runs)
- **OpenSearch** (BM25 + filters)
- **Qdrant** (vectors for text + images; payload filters)
- **Neo4j** (event/entity/claim graph; optional but recommended for multi-hop and narrative explanations)

## Multimodal extraction

- **Unstructured.io** for PDFs/HTML/Office
- **Document AI / Azure Document Intelligence** for OCR/layout on scans
- Tables: extract to **Parquet/JSON** + keep original region images

## Models

- Strong LLM for synthesis; cheaper LLM for extraction/planning
- Text embeddings + image embeddings (CLIP/SigLIP)
- Reranker (Cohere Rerank or open reranker)

## Reasoning

- **Z3** for deterministic constraints
- **pgmpy** for Bayesian Networks (structure + inference)

## Ops / research batch

- FastAPI + workers (Celery/RQ) + OpenTelemetry + Prometheus/Grafana
- Full run artifact capture for reproducibility

---

# 3) Canonical data model (industry-neutral)

## 3.1 EvidenceObject (immutable, provenance-first)

Every extracted item becomes an EvidenceObject:

- evidence_id, doc_id, source_uri, source_type
- modality: text|image|table
- content_ref (S3 pointer), extracted text, bbox/page/row-col
- observed_time (event time if present), ingest_time
- hash, extraction_method, confidence

## 3.2 Derived objects (re-creatable)

- **Entity**: canonical entity + aliases (company, country, project, asset, commodity, person)
- **Claim**: atomic statement with qualifiers (value, unit, time, polarity, modality)
- **Event**: time-bounded occurrence (who/what/when/where)
- **Graph edges**: entity↔claim, claim↔event, event↔event (temporal/causal)

---

# 4) End-to-end pipeline (single unified flow)

## Stage A — Ingestion (batch, multimodal)

1) **Acquire** mixed sources (docs, filings, news, research PDFs, spreadsheets, images, charts, web pages, APIs).
2) **Parse/OCR/layout**:
   - text extraction + layout metadata
   - table extraction to structured form
   - image region extraction (figures/charts) + OCR captions
3) **Normalize** into EvidenceObjects with strict provenance.
4) **Persist** raw artifacts to S3; metadata to Postgres.

## Stage B — Indexing (multi-representation)

1) **Chunking** (section-aware; pack can override).
2) **OpenSearch** BM25 index for exact match.
3) **Qdrant** vector index:
   - text embeddings for chunks/claims
   - image embeddings for figures/regions
   - table semantic views (caption + headers + row summaries)
4) **Graph seed** (optional):
   - lightweight entity linking + co-mention edges into Neo4j.

## Stage C — Run initialization (research job)

1) Create run_id, store budgets and model versions.
2) Select **Domain Pack**:
   - user chooses (finance/trading/macro/geopolitics/construction)
   - or auto-select via classifier (optional)
3) Load pack: schemas, priors, BN templates, constraints, retrieval policy, output template.

## Stage D — Planning & decomposition (agentic but bounded)

1) Classify task: “explain past event”, “forecast”, “scenario analysis”, “compare hypotheses”, “risk assessment”.
2) Decompose into sub-questions (multi-hop).
3) Route retrieval: hybrid search vs graph traversal vs table-first vs image-first.
4) Set retrieval filters:
   - time horizon (e.g., last 7 days for trading; last 10 years for macro history)
   - source tiers (official stats > filings > reputable news > social)

This is where you exploit advanced tool configuration (filters/sorting/structured queries) rather than only text queries [5].

## Stage E — Retrieval (hybrid + iterative)

For each sub-question:

1) Retrieve candidates from:
   - OpenSearch (BM25)
   - Qdrant (dense)
   - Neo4j (graph neighborhood expansion)
2) Fuse results (RRF/weighted).
3) Rerank top-N.
4) Add to CandidateEvidenceSet.

Iterate if uncertainty remains (bounded by budgets).

## Stage F — Integration (dedup, conflict, timeline, structured extraction)

1) Deduplicate and cluster near-duplicates.
2) Extract structured **Claims/Events** using pack schema.
3) Normalize:
   - units/currencies
   - time ranges
   - entity resolution
4) Conflict detection:
   - same claim, different values
   - inconsistent timelines
5) Build/update Evidence Graph (Postgres + Neo4j).

Integration is treated as a first-class stage (not just prompt stuffing), aligning with “intelligent knowledge integration” emphasis [6].

## Stage G — Reasoning (deterministic + Bayesian Networks)

### G1 Deterministic (Z3)

- Compile constraints from:
  - extracted events (ordering, durations)
  - pack rules (industry constraints)
- Output:
  - consistent timelines
  - contradiction explanations (and minimal inconsistent evidence sets)

### G2 Probabilistic (Bayesian Networks via pgmpy)

- Choose BN template from pack (e.g., “macro recession risk”, “geopolitical escalation”, “construction delay drivers”, “earnings surprise drivers”).
- Map claims/events into BN evidence with reliability priors.
- Run inference:
  - posterior over hypotheses (causes) and forecasts (outcomes)
- Output:
  - ranked hypotheses with probabilities
  - sensitivity: which evidence moved the posterior most

### G3 Reasoning-driven retrieval loop

If:

- Z3 contradictions suggest missing disambiguating evidence, or
- BN posterior is too flat,

then generate targeted retrieval queries and loop back to Stage E (bounded). This keeps the system “agentic” but controlled—important because coordination complexity and overhead are real in multi-agent systems [3].

## Stage H — Synthesis (final answer + explanation + citations)

Generate a report using pack templates:

- **Executive summary**
- **Timeline** (for past events)
- **Most likely explanation** (with posterior)
- **Alternative scenarios** (with probabilities)
- **Key drivers & leading indicators**
- **Risks / unknowns / what evidence would change the conclusion**
- **Evidence table with citations** (EvidenceObject IDs)

Hard rule: no key claim without provenance.

## Stage I — Run artifacts + evaluation (research batch)

Persist everything:

- retrieval plan, retrieved IDs, rerank scores
- extracted claims/events/entities
- Z3 constraints + results
- BN structure/CPDs/evidence/posteriors
- final report + citations

Offline evaluation:

- retrieval metrics (Recall@k, nDCG)
- citation correctness
- contradiction rate
- BN calibration (Brier score)
- regression tests per Domain Pack

---

# 5) Domain Packs for your industries (what changes per pack)

Below are concrete pack examples for your target areas. Each pack ships: schema + priors + BN templates + constraints + retrieval policy + output template.

## 5.1 Construction pack

- **Entities**: Project, Contractor, Subcontractor, Permit, Material, Site, Milestone
- **Events**: PermitIssued, DeliveryDelayed, InspectionFailed, WeatherEvent, ChangeOrder
- **Z3 constraints**:
  - milestone ordering, critical path constraints, resource exclusivity
- **BN templates**:
  - DelayDrivers → (Weather, SupplyChain, Labor, Permitting, Rework) → ScheduleSlip
- **Retrieval policy**:
  - prioritize contracts, schedules, inspection logs, change orders
- **Output**: RCA + schedule risk forecast

## 5.2 Finance / corporate fundamentals pack

- **Entities**: Company, Subsidiary, Segment, KPI, Guidance
- **Events**: EarningsRelease, GuidanceChange, RatingAction, M&A rumor/announcement
- **Z3 constraints**:
  - accounting identities (Assets = Liabilities + Equity), period consistency
- **BN templates**:
  - EarningsSurpriseDrivers → (Demand, FX, Costs, OneOffs) → EPS surprise
- **Retrieval policy**:
  - filings > transcripts > reputable research > news
- **Output**: earnings explanation memo + forward risks

## 5.3 Trading / markets pack

- **Entities**: Asset, Venue, OrderFlowProxy, VolatilityRegime
- **Events**: MacroPrint, FedDecision, GeopoliticalShock, LiquidityEvent
- **Z3 constraints**:
  - market calendar/timezone ordering, event windows, causality guardrails (“cannot react before release time”)
- **BN templates**:
  - Regime → (Liquidity, Vol, RiskAppetite) → ExpectedMove distribution bucket
- **Retrieval policy**:
  - strict time filters, high recency weighting, source tiering
- **Output**: trading thesis + scenario tree + invalidation levels

## 5.4 Macroeconomy outlook pack

- **Entities**: Country, CentralBank, Indicator (CPI, PMI, GDP), Sector
- **Events**: PolicyChange, InflationShock, SupplyShock
- **Z3 constraints**:
  - indicator release schedules, definitional consistency across revisions
- **BN templates**:
  - Growth/Inflation latent states → (PMI, CPI, Jobs, Credit) → RecessionRisk
- **Retrieval policy**:
  - official stats + central bank comms prioritized
- **Output**: macro outlook report + probability-weighted scenarios

## 5.5 Geopolitics forecasting pack

- **Entities**: Country, Alliance, Leader, Region, Commodity chokepoint
- **Events**: Sanction, MilitaryMove, Election, TreatyBreakdown
- **Z3 constraints**:
  - timeline consistency, actor capability constraints (optional)
- **BN templates**:
  - EscalationRisk → (DomesticPressure, MilitaryPosture, ExternalSupport, EconomicStress) → ConflictProbability
- **Retrieval policy**:
  - source reliability priors are crucial; heavy conflict clustering
- **Output**: forecast brief + scenario probabilities + key triggers

---

# 6) Plugin contract (how packs “act as configurable plugins”)

## Pack interface (YAML + optional Python hooks)

- pack.yaml: retrieval policy, source tiers, time horizons, output template, and fusion configuration (strategy: rrf|weighted; weights; rrf_k)
- schemas/*.json: entity/event/claim schema
- reasoning/bayesnet_templates.yaml: BN structures
- reasoning/cpds_priors.json: CPDs priors + source reliability priors
- reasoning/z3_constraints.py: constraint builders
- prompts/*.jinja: extraction/decomposition/synthesis prompts

## Runtime injection points

- Planner uses pack decomposition + routing rules
- Retriever uses pack filters + fusion weights
- Integrator uses pack schema + conflict rules
- Reasoner loads pack BN + CPDs + Z3 constraints
- Composer uses pack report template

---

# 7) Practical note: keep it powerful but not “too agentic”

Given real-world coordination/overhead issues in multi-agent systems [3], the recommended pattern is:

- **One LangGraph workflow** with **specialist nodes** (planner/retriever/integrator/reasoner/composer)
- Optional “multi-agent” only inside bounded substeps (e.g., parallel retrieval workers), consistent with hierarchical/managed multi-agent benefits [9].
