# Anything Extractor

A self-adaptive, self-evolving data extraction system for professional PDF documents.

Drop in a pile of PDFs and a one-liner like *"extract useful info from these research reports"* — the system figures out what to extract, builds the pipeline, judges its own quality, and evolves to get better and cheaper over time. No schema, no examples, no annotation needed.

## How It Works

Three LLM-powered roles collaborate in an evolution loop:

```
                    ┌─────────────────┐
                    │    BUILDER      │  Analyze docs, propose schema,
                    │                 │  generate Python extraction code
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │     WORKER      │  Parse PDFs, run extraction,
                    │                 │  score confidence per field
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │    OBSERVER     │  Judge quality (LLM-as-Judge),
                    │                 │  trigger Builder if quality drops
                    └────────┬────────┘
                             │
                             ▼
                       Evolution loop
```

Each role can use any LLM provider (OpenAI, Anthropic, SiliconFlow, OpenRouter, Gemini, etc.) — configured independently via `.env`.

**Builder** generates actual Python workflow code (not just prompts), validates it via AST parsing, and git-commits each version. **Worker** dynamically loads and executes these workflows. **Observer** evaluates output quality and decides when to trigger re-evolution. The loop runs until quality stabilizes or hits max iterations.

## Quick Start

### Prerequisites

- Python 3.11+
- API key for at least one LLM provider (SiliconFlow, OpenAI, Anthropic, OpenRouter, etc.)

### Install

```bash
git clone https://github.com/kitchen-engineer42/anything-extractor.git
cd anything-extractor
pip install -e .
```

### Configure

Copy `.env.example` to `.env` and fill in your API keys:

```ini
# Set the providers you need
SILICONFLOW_API_KEY=sk-...
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
OPENROUTER_API_KEY=sk-or-...

# Default provider for model names without a prefix
AE_DEFAULT_PROVIDER=siliconflow

# Models can use provider prefixes: openai/gpt-4o, anthropic/claude-sonnet-4-20250514
# Without a prefix, models route through AE_DEFAULT_PROVIDER
AE_WORKER_MODEL=Qwen/Qwen3-VL-235B-A22B-Instruct
AE_BUILDER_MODEL=anthropic/claude-opus-4-6
AE_OBSERVER_MODEL=anthropic/claude-opus-4-6
AE_DATABASE_URL=sqlite:///./data/anything_extractor.db
AE_LANGUAGE=bilingual
```

Each role (Worker, Builder, Observer) can independently use any provider. Mix and match freely — e.g. use Claude for Builder/Observer and SiliconFlow for Worker to keep extraction costs low.

### Run

```bash
# Bootstrap a new extraction task
ae new "extract useful information from these reports" --input ./my-pdfs/ --samples 3

# Run extraction on all documents
ae run "extract useful information from these reports"

# Check quality and trigger evolution
ae observe "extract useful information from these reports"
ae evolve "extract useful information from these reports"

# Export results
ae export "extract useful information from these reports" --format excel
```

## CLI Reference

| Command | Description |
|---|---|
| `ae new <desc> --input <path>` | Create task, analyze samples, generate first workflow |
| `ae run <task>` | Run extraction (with optional `--observe` and `--evolve`) |
| `ae status [<task>]` | Show task status, per-field accuracy, cost metrics |
| `ae observe <task>` | Trigger observer evaluation (`--full` for 100% sampling) |
| `ae feedback <task>` | Interactive feedback: approve, correct, or reject extractions |
| `ae evolve <task>` | Manually trigger builder evolution |
| `ae export <task> --format json\|excel` | Export results |
| `ae schema <task>` | Show current extraction schema |
| `ae history <task>` | Show evolution audit trail |
| `ae workflow <task>` | Show workflow code (`--diff 'v1 v2'` to compare versions) |
| `ae patterns` | List shared pattern library |

## Key Design Decisions

### Workflows as Python Code
Builder generates real Python modules, not prompt templates. Each workflow implements a stable contract:

```python
def extract(context: WorkflowContext) -> ExtractionResult
```

This allows mixing LLM calls with regex, code logic, and per-field model selection — all version-controlled via git.

### Progressive Cost Reduction
Two dimensions of optimization over iterations:

1. **Model downgrade** — Builder tracks per-field accuracy and downgrades from 235B to 32B to 14B to 8B when safe
2. **Code migration** — Deterministic fields (dates, IDs) migrate from LLM calls to regex at zero inference cost

```
Iter 0:   100% @ 235B                        → $X/doc
Iter 3:   30% @ 235B, 50% @ 32B, 20% regex   → ~$0.4X/doc
Iter 10:  10% @ 72B, 30% @ 14B, 60% regex    → ~$0.1X/doc
```

### Corner Case Isolation
- **Systemic issues** (>10% of docs) → rewrite the workflow
- **Corner cases** (<10%) → record in DB with pattern + resolution, checked before extraction

### Observer Non-Invasiveness
Observer judges quality but never modifies Worker output. Even if Observer is wrong, no extraction data is corrupted.

### Adaptive Sampling
Observer evaluates 100% of results early on, dropping to 5% once quality stabilizes. Random sampling remains active to catch regressions.

## Project Structure

```
src/ae/
├── config.py              # Pydantic Settings from .env
├── cli.py                 # Typer CLI (11 commands)
├── db.py                  # SQLAlchemy (SQLite / PostgreSQL)
├── models.py              # 10 ORM models
├── llm.py                 # Multi-provider LLM client (via LiteLLM)
├── pdf.py                 # PDF parsing (pymupdf + MinerU fallback)
├── builder/               # Schema proposal, code generation, git ops
├── worker/                # Workflow execution, confidence scoring, export
├── observer/              # LLM-as-Judge, sampling, feedback, triggers
└── shared/                # Types, bilingual prompts, utilities
```

Workflows live in a separate `workflows/` directory with its own git repo — Builder commits each version there independently.

## Bilingual Support

The system handles English and Chinese natively. All LLM prompts have `en`, `zh`, and `bilingual` variants controlled by `AE_LANGUAGE` in `.env`. The first test corpus is 100+ Chinese securities research reports with metadata-encoded filenames (`{券商}：{标题}_{作者}_{类别}_{日期}.pdf`).

## License

MIT
