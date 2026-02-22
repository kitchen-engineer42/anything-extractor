# Anything Extractor — System Specification

## 1. Overview

**Anything Extractor (AE)** is a self-adaptive, self-evolving data extraction system for professional PDF documents (finance, law, research). The system starts with sample PDFs and a one-liner description, then grows into a tailored extraction pipeline — no pre-defined schema, no examples, no human annotation required.

Three roles collaborate in an evolution loop:

| Role | Model | Responsibility |
|------|-------|----------------|
| **Builder** | GLM-5 (SOTA coding model) | Analyze documents, propose schema, generate/modify extraction code |
| **Worker** | Qwen3-VL-235B (vision model) | Parse PDFs, run extraction workflows, score confidence |
| **Observer** | Kimi-K2.5 (reasoning model) | Judge extraction quality, sample results, collect feedback |

The system improves accuracy while reducing cost over time through model downgrading and code migration.

---

## 2. Architecture

```
User: "extract key terms from these contracts" + PDFs
                        │
                        ▼
              ┌─────────────────┐
              │    BUILDER      │  Analyze docs → Propose schema
              │                 │  Generate Python workflow code
              │                 │  Git commit to workflows/
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │     WORKER      │  Parse PDF (pymupdf / MinerU)
              │                 │  Run workflow → ExtractionResult
              │                 │  Per-field confidence scoring
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │    OBSERVER     │  LLM-as-Judge (text + vision)
              │                 │  Adaptive sampling (100% → 5%)
              │                 │  Trigger Builder if quality drops
              └────────┬────────┘
                       │
                       ▼
                 Evolution loop
```

### Data Flow

```
PDFs → [Parse] → Document records
     → [Analyze] → DocumentAnalysis
     → [Schema] → SchemaVersion
     → [Codegen] → WorkflowVersion (git committed)
     → [Extract] → Extraction records
     → [Judge] → ObserverJudgment
     → [Trigger?] → Builder diagnose → new workflow → re-extract → re-judge
     → [Export] → JSON / Excel
```

---

## 3. Project Structure

```
anything-extractor/
├── .env                          # API keys, models, DB, language config
├── pyproject.toml                # PEP 621 project definition
├── spec.md                       # This file
├── alembic.ini + migrations/     # Database migrations
│
├── src/ae/                       # Main package
│   ├── config.py                 # Pydantic Settings from .env
│   ├── cli.py                    # Typer CLI entry point (11 commands)
│   ├── db.py                     # SQLAlchemy engine + session (SQLite/PostgreSQL)
│   ├── models.py                 # 10 ORM models
│   ├── llm.py                    # SiliconFlow client (OpenAI-compatible)
│   ├── pdf.py                    # PDF parsing facade (pymupdf / MinerU / OCR)
│   │
│   ├── builder/
│   │   ├── bootstrap.py          # New task: docs → schema → workflow
│   │   ├── analyzer.py           # Diagnose systemic vs corner-case issues
│   │   ├── codegen.py            # Generate/modify Python workflows via LLM
│   │   ├── schema_mgr.py         # Schema versioning (create, activate, diff)
│   │   ├── git_ops.py            # Git ops on workflows/ repo (GitPython)
│   │   └── pattern_lib.py        # Shared patterns across tasks (EvoMap-inspired)
│   │
│   ├── worker/
│   │   ├── runner.py             # Dynamic workflow loader + executor
│   │   ├── confidence.py         # Per-field composite confidence scoring
│   │   └── postprocess.py        # JSON + Excel output with styled sheets
│   │
│   ├── observer/
│   │   ├── judge.py              # LLM-as-Judge (text + vision capable)
│   │   ├── sampler.py            # Adaptive sampling strategy (full → random)
│   │   ├── feedback.py           # Interactive CLI feedback recorder
│   │   └── trigger.py            # Quality threshold → evolution trigger
│   │
│   └── shared/
│       ├── types.py              # WorkflowContext, ExtractionResult, protocols
│       ├── prompts.py            # Bilingual prompt templates (EN/ZH/bilingual)
│       └── utils.py              # Helpers: sanitize names, validate code, parse JSON
│
├── workflows/                    # Separate git repo — Builder writes here
│   └── {task_name}/
│       ├── extract_v1.py         # Version 1 (bootstrap)
│       ├── extract_v2.py         # Version 2 (evolved)
│       └── ...
│
├── data/
│   ├── input/                    # PDFs go here
│   ├── output/                   # Results land here (JSON, Excel)
│   └── anything_extractor.db    # SQLite database (default)
│
├── logs/                         # Session transcripts
│   ├── 01_planning_session.jsonl
│   └── 02_implementation_session.jsonl
│
├── dev_log/                      # Development journal
│
└── tests/
```

---

## 4. Database Schema

### Core Tables

| Table | Purpose | Key Columns |
|---|---|---|
| **tasks** | Top-level extraction task | name, description, status (bootstrapping/running/evolving/completed/failed), iteration, max_iteration, language, config (JSON) |
| **documents** | Individual PDFs | task_id, filename, file_hash (SHA256), file_path, page_count, parse_method (pymupdf/mineru), parse_result (JSON), is_sample, metadata_extracted (JSON) |
| **schema_versions** | Versioned extraction schemas | task_id, version, schema_def (JSON: fields with name/type/description/required), is_active |
| **workflow_versions** | Versioned workflow code | task_id, version, git_commit_hash, module_path, model_assignments (JSON), is_active |
| **extractions** | One doc × one workflow run | document_id, workflow_version_id, schema_version_id, iteration, result (JSON), field_confidences (JSON), overall_confidence, llm_calls, llm_tokens_used, status |
| **observer_judgments** | Observer evaluation | extraction_id, result (correct/partial/incorrect/missing), field_judgments (JSON), reasoning, used_vision, overall_score, sampling_method |
| **feedback_records** | Human corrections | judgment_id, feedback_type (correction/approval/rejection/comment), field_name, original_value, corrected_value |
| **evolution_events** | Audit trail | task_id, event_type, iteration, trigger (JSON), mutation (JSON), outcome (JSON) |
| **shared_patterns** | Cross-task reusable patterns | name, category, implementation, implementation_type (code/regex/prompt), confidence, usage_count, success_count |
| **corner_cases** | Per-task edge cases | task_id, field_name, description, pattern, resolution, resolution_type |

### Database Options
- **Default**: SQLite (`sqlite:///./data/anything_extractor.db`) — zero configuration
- **Production**: PostgreSQL (`postgresql://host:port/db`) — connection pooling, concurrency
- **Cache**: Redis (optional) — LLM response cache, real-time status

---

## 5. Workflow Contract

Builder generates Python modules that implement a stable contract:

```python
from ae.shared.types import ExtractionResult

def extract(context: WorkflowContext) -> ExtractionResult:
    """Entry point. Called by Worker for each document."""
    ...
```

### WorkflowContext (input)

| Attribute | Type | Description |
|-----------|------|-------------|
| `pages` | `list[dict]` | Parsed pages with `text`, `page_number`, `width`, `height` |
| `schema` | `dict` | Active schema definition with field specs |
| `llm` | `module` | LLM client (`chat()`, `chat_json()`, `chat_vision()`) |
| `pdf_path` | `str` | Path to original PDF file |
| `parse_result` | `dict` | Full parse result from pymupdf/mineru |
| `filename_metadata` | `dict` | Parsed from filename: `broker`, `title`, `authors`, `category`, `date` |
| `corner_cases` | `list[dict]` | Known edge cases with resolutions |
| `shared_patterns` | `list[dict]` | Reusable extraction patterns |
| `model_tiers` | `list[str]` | Available models (largest → smallest) |
| `model_assignments` | `dict[str, str]` | Per-field model overrides |
| `get_model_for_field(name)` | method | Returns assigned model for a field |
| `track_llm_usage(calls, tokens)` | method | Track LLM consumption |

### ExtractionResult (output)

| Field | Type | Description |
|-------|------|-------------|
| `fields` | `dict[str, Any]` | Extracted values keyed by field name |
| `field_confidences` | `dict[str, float]` | Per-field confidence `[0.0, 1.0]` |
| `llm_calls` | `int` | Number of LLM API calls made |
| `llm_tokens` | `int` | Total tokens consumed |
| `errors` | `list[str]` | Non-fatal errors encountered |

Builder can generate arbitrarily complex logic inside `extract()`, including:
- Zero-cost extraction from filename metadata
- Regex/pattern matching for deterministic fields
- Per-field model selection for cost optimization
- Corner case detection and special handling
- Multi-step LLM reasoning for complex fields

---

## 6. Key Design Decisions

### 6.1 Workflows as Python Code (not prompts)
Builder generates actual Python modules with a stable contract. This allows:
- Arbitrarily complex extraction logic
- Mix of LLM calls, regex, and code
- AST validation before commit
- Version control via git
- Rollback per-task

### 6.2 Separate Git Repo for Workflows
`workflows/` has its own `.git`. Evolution history is independent of project code. GitPython handles programmatic commits, diffs, and version listing.

### 6.3 Observer Non-Invasiveness
Observer produces judgments alongside extractions — never modifies Worker output. Even if Observer is wrong, no data is corrupted. Judgments are advisory.

### 6.4 Corner Case Isolation
- **Systemic issue** (>10% docs affected) → rewrite workflow
- **Corner case** (<10% docs) → add to `corner_cases` table with pattern + resolution
- Worker checks corner cases via pattern match before standard extraction

### 6.5 Progressive Cost Reduction

**Dimension 1 — Model Downgrade**: Builder tracks per-field accuracy across model tiers and downgrades when safe:

| Tier | Model | Use Case |
|------|-------|----------|
| 0 | 235B vision | Bootstrap, complex fields |
| 1 | 32B | Good accuracy, lower cost |
| 2 | 14B | Sufficient for well-understood fields |
| 3 | 8B | Near-minimum cost, simple fields |

**Dimension 2 — Code Migration**: For deterministic patterns:

```
LLM call → regex / Python code → zero inference cost
```

### 6.6 Confidence Scoring
Per-field composite score from 5 components:
1. LLM self-confidence (weight: 0.30)
2. Extraction method prior (weight: 0.15)
3. Historical accuracy (weight: 0.25)
4. Source text clarity (weight: 0.20)
5. Corner case match (weight: 0.10)

### 6.7 Adaptive Sampling
Observer sampling rate decreases as quality stabilizes:

| Iteration | Sampling Rate | Strategy |
|-----------|--------------|----------|
| 0 | 100% | Full evaluation (bootstrap) |
| 1–3 | 50% | Priority + random |
| 4–9 | 20% | Priority + random |
| 10+ | 5% | Regression detection only |

Priority sampling always evaluates failed and low-confidence extractions first.

---

## 7. Bootstrap Sequence

```
ae new "extract key terms from these contracts" --input ./pdfs/

1. Create Task record (status=BOOTSTRAPPING)
2. Ingest PDFs → Document records (hash, parse, mark samples)
3. Builder analyzes sample docs (LLM → DocumentAnalysis)
4. Builder proposes schema (LLM → SchemaVersion v1)
5. Builder generates initial workflow Python code (LLM → code)
6. Git commit to workflows/{task}/extract_v1.py
7. Task.status = RUNNING, Task.iteration = 0
```

## 8. Evolution Loop

```
Worker runs → Observer samples & judges → Trigger check
  │                                           │
  │  NO (quality OK)                    YES (quality drop)
  │  → Store output, done               → Builder diagnoses
  │                                           │
  │                              ┌────────────┴────────────┐
  │                         Corner case              Systemic issue
  │                         → Add to DB              → Rewrite workflow
  │                              └────────────┬────────────┘
  │                                           │
  │                                     Git commit new version
  │                                     Re-run on failed docs
  │                                     Re-observe to verify
  │                                     iteration += 1
  └───────────────────────────────────────────┘
```

Evolution stops when `task.iteration >= MAX_ITERATIONS` (default 20). The system then enters production mode: Worker runs with locked workflow, Observer does random sampling only, Builder not invoked unless user runs `ae evolve`.

---

## 9. CLI Reference

| Command | Description |
|---|---|
| `ae new <desc> --input <path> [--samples N]` | Create task, run full bootstrap |
| `ae run <task> [--input <path>] [--observe/--no-observe] [--evolve/--no-evolve]` | Run extraction (optionally ingest new docs, observe, auto-evolve) |
| `ae status [<task>]` | Show task status, per-field accuracy, cost metrics |
| `ae observe <task> [--full] [--vision]` | Trigger observer evaluation |
| `ae feedback <task>` | Interactive feedback mode (approve/correct/reject) |
| `ae evolve <task>` | Manually trigger builder evolution |
| `ae export <task> --format json\|excel [--output <path>]` | Export results |
| `ae schema <task>` | Show current extraction schema |
| `ae history <task>` | Show evolution audit trail |
| `ae workflow <task> [--diff 'v1 v2']` | Show/diff workflow code |
| `ae patterns` | List shared pattern library |

---

## 10. Configuration (.env)

```ini
# --- API Keys ---
SILICONFLOW_API_KEY=sk-...
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
MINERU_API_KEY=eyJ...

# --- LLM Models ---
AE_WORKER_MODEL=Qwen/Qwen3-VL-235B-A22B-Instruct
AE_BUILDER_MODEL=Pro/zai-org/GLM-5
AE_OBSERVER_MODEL=Pro/moonshotai/Kimi-K2.5
AE_OBSERVER_VISION_MODEL=Qwen/Qwen3-VL-235B-A22B-Instruct

# --- Model Downgrade Tiers (largest → smallest) ---
AE_WORKER_MODEL_TIERS=Qwen/Qwen3-VL-235B-A22B-Instruct,Qwen/Qwen3-32B,Qwen/Qwen3-14B,Qwen/Qwen3-8B

# --- Database ---
AE_DATABASE_URL=sqlite:///./data/anything_extractor.db
# AE_DATABASE_URL=postgresql://localhost:5432/anything_extractor
AE_REDIS_URL=

# --- Language (en | zh | bilingual) ---
AE_LANGUAGE=bilingual

# --- Evolution ---
MAX_ITERATIONS=20

# --- Paths ---
AE_WORKFLOWS_DIR=./workflows
AE_DATA_DIR=./data
```

---

## 11. Dependencies

```toml
dependencies = [
    "typer>=0.9",           # CLI framework
    "openai>=1.0",          # SiliconFlow API client (OpenAI-compatible)
    "sqlalchemy>=2.0",      # ORM
    "alembic>=1.12",        # DB migrations
    "psycopg2-binary",      # PostgreSQL driver
    "redis>=5.0",           # Optional cache
    "pymupdf>=1.23",        # PDF text extraction
    "pydantic>=2.0",        # Data validation
    "pydantic-settings",    # .env configuration
    "openpyxl",             # Excel export
    "rich",                 # Terminal UI
    "gitpython",            # Workflow git operations
    "httpx",                # HTTP client (MinerU API)
]
```

---

## 12. Bilingual Design

All prompts in `src/ae/shared/prompts.py` are stored in three variants: `en`, `zh`, `bilingual`. The `AE_LANGUAGE` setting controls which variant is used.

Key bilingual requirements:
- Schema field descriptions in both languages
- Observer judgment prompts reference document content in original language
- CLI output renders Chinese text correctly (Rich library)
- Filename parsing understands Chinese characters: `{券商}：{标题}_{作者}_{类别}_{日期}.pdf`

---

## 13. First Corpus: Chinese Research Reports

**Directory**: `corpus_research_report_202602/` containing 100+ Chinese securities research reports organized by date (2026-02-06 through 2026-02-13).

**Document categories**: 晨午晚报 (morning briefs), 行业研究 (industry research), 公司研究 (company research), 策略研究 (strategy research), 宏观经济 (macroeconomics)

**Filename structure**: `{证券公司}：{报告标题}_{作者}_{类别}_{日期}.pdf`

**Bootstrap command**: `ae new "从这些研报中提取有用的信息" --input ./corpus_research_report_202602/`

**Auto-discovered schema** (10 fields): broker_institution, report_title, publication_date, analyst_author, disclaimer, report_category, core_viewpoints, market_data, key_news_items, mentioned_companies

---

## 14. Verification Checklist

| Test | Description | Status |
|------|-------------|--------|
| Bootstrap | `ae new` — schema proposal, workflow generation, git commit | ✅ Verified |
| Extraction | Worker runs workflow on 3 docs, all succeed | ✅ Verified |
| Observer | LLM-as-Judge evaluates 3 extractions (avg 0.72) | ✅ Verified |
| Evolution | Diagnose systemic issue → new workflow v2 → re-extract → re-judge | ✅ Verified |
| JSON Export | `ae export --format json` | ✅ Verified |
| Excel Export | `ae export --format excel` with color-coded confidence | ✅ Verified |
| Status Dashboard | Per-field accuracy, cost tracking | ✅ Verified |
| Workflow Diff | `ae workflow --diff '1 2'` shows Builder's changes | ✅ Verified |
| History | Evolution audit trail | ✅ Verified |
| Model downgrade | After 3+ iterations, Builder downgrades stable fields | ⬜ Pending |
| Code migration | Deterministic fields migrate from LLM to regex | ⬜ Pending |
| Max iteration | System stops evolving after MAX_ITERATIONS | ⬜ Pending |
| Multi-task | Shared patterns propagate between tasks | ⬜ Pending |
| Full corpus | Run on all 100+ documents | ⬜ Pending |
