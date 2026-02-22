Anything-Extractor: System Design                                                                                  
                                                        
 Context

 Build a self-adaptive, self-evolving data extraction system for professional PDF documents (finance, law). The
 system starts with sample PDFs + a one-liner description and grows into a tailored extraction pipeline — no
 pre-defined schema, no examples, no human annotation. Three roles (Worker, Observer, Builder) collaborate in an
 evolution loop that improves accuracy while reducing cost over time.

 ---
 Architecture Overview

 User: "extract key terms from these contracts" + PDFs
                         │
                         ▼
               ┌─────────────────┐
               │    BUILDER      │  (GLM-5 — SOTA coding model)
               │  Analyze docs   │
               │  Propose schema │
               │  Generate code  │
               │  Git commit     │
               └────────┬────────┘
                        │ generates Python workflow module
                        ▼
               ┌─────────────────┐
               │     WORKER      │  (Qwen3-VL-235B — cheap vision model)
               │  Parse PDF      │
               │  Run workflow   │
               │  Score confidence│
               └────────┬────────┘
                        │ extraction results
                        ▼
               ┌─────────────────┐
               │    OBSERVER     │  (Kimi-K2.5 — SOTA reasoning model)
               │  Judge quality  │
               │  Sample/review  │
               │  Collect feedback│
               └────────┬────────┘
                        │ triggers Builder if quality drops
                        ▼
                  Evolution loop

 ---
 Project Structure

 anything-extractor/
 ├── .env                          # API keys, models, DB, language
 ├── pyproject.toml                # Dependencies (PEP 621)
 ├── alembic.ini + migrations/     # DB migrations
 │
 ├── src/ae/                       # Main package
 │   ├── config.py                 # Pydantic Settings from .env
 │   ├── cli.py                    # Typer CLI entry point
 │   ├── db.py                     # SQLAlchemy engine + session
 │   ├── models.py                 # All ORM models
 │   ├── llm.py                    # SiliconFlow client (OpenAI-compatible)
 │   ├── pdf.py                    # PDF parsing facade (pymupdf / MinerU / OCR)
 │   │
 │   ├── worker/
 │   │   ├── runner.py             # Dynamic workflow loader + executor
 │   │   ├── confidence.py         # Per-field confidence scoring
 │   │   └── postprocess.py        # JSON + Excel output
 │   │
 │   ├── observer/
 │   │   ├── judge.py              # LLM-as-Judge (vision-capable)
 │   │   ├── sampler.py            # Sampling strategy (full → random)
 │   │   ├── feedback.py           # CLI feedback recorder
 │   │   └── trigger.py            # When to call Builder
 │   │
 │   ├── builder/
 │   │   ├── bootstrap.py          # New task: docs → schema → workflow
 │   │   ├── analyzer.py           # Corner case vs systemic issue
 │   │   ├── codegen.py            # Generate/modify Python workflows
 │   │   ├── schema_mgr.py         # Schema versioning
 │   │   ├── git_ops.py            # Git ops on workflows/ repo
 │   │   └── pattern_lib.py        # Shared patterns across tasks
 │   │
 │   └── shared/
 │       ├── types.py              # TypedDicts, enums, protocols
 │       ├── prompts.py            # Bilingual prompt templates (EN/ZH)
 │       └── utils.py
 │
 ├── workflows/                    # Separate git repo — Builder writes here
 │   └── {task_name}/extract_v{N}.py
 │
 ├── data/
 │   ├── input/                    # PDFs go here
 │   └── output/                   # Results land here
 │
 └── tests/

 ---
 Data Model (PostgreSQL + Redis)

 Core Tables

 Table: tasks
 Purpose: Top-level extraction task
 Key Columns: name, description, status, iteration, max_iteration, language, config (JSONB)
 ────────────────────────────────────────
 Table: documents
 Purpose: Individual PDFs
 Key Columns: task_id, filename, file_hash, page_count, parse_method, parse_result (JSONB), is_sample
 ────────────────────────────────────────
 Table: schema_versions
 Purpose: Versioned extraction schemas
 Key Columns: task_id, version, schema_def (JSONB), is_active
 ────────────────────────────────────────
 Table: workflow_versions
 Purpose: Versioned workflow code
 Key Columns: task_id, version, git_commit_hash, module_path, pipeline_nodes (JSONB), confidence_config (JSONB),
   model_assignments (JSONB), is_active
 ────────────────────────────────────────
 Table: extractions
 Purpose: One doc × one workflow run
 Key Columns: document_id, workflow_version_id, schema_version_id, iteration, result (JSONB), field_confidences
   (JSONB), overall_confidence, llm_calls, llm_tokens_used
 ────────────────────────────────────────
 Table: observer_judgments
 Purpose: Observer evaluation
 Key Columns: extraction_id, result (enum), field_judgments (JSONB), reasoning, used_vision, overall_score,
   sampling_method
 ────────────────────────────────────────
 Table: feedback_records
 Purpose: Human corrections
 Key Columns: judgment_id, feedback_type, field_name, original_value, corrected_value, comment
 ────────────────────────────────────────
 Table: evolution_events
 Purpose: Audit trail (EvoMap-inspired)
 Key Columns: task_id, event_type, iteration, trigger (JSONB), mutation (JSONB), outcome (JSONB)
 ────────────────────────────────────────
 Table: shared_patterns
 Purpose: Cross-task reusable patterns
 Key Columns: name, category, implementation, implementation_type, confidence, usage_count, success_count
 ────────────────────────────────────────
 Table: corner_cases
 Purpose: Per-task edge cases
 Key Columns: task_id, field_name, description, pattern, resolution, resolution_type

 Redis (ephemeral cache only)

 ┌──────────────────┬──────────────────────────┬─────┐
 │       Key        │         Purpose          │ TTL │
 ├──────────────────┼──────────────────────────┼─────┤
 │ pdf:{hash}:pages │ Cached parsed pages      │ 24h │
 ├──────────────────┼──────────────────────────┼─────┤
 │ llm:cache:{hash} │ LLM response cache       │ 1h  │
 ├──────────────────┼──────────────────────────┼─────┤
 │ task:{id}:status │ Real-time status for CLI │ 5m  │
 └──────────────────┴──────────────────────────┴─────┘

 ---
 Key Design Decisions

 1. Workflows as Python Code

 Builder generates actual Python modules with a stable contract:
 def extract(context: WorkflowContext) -> ExtractionResult
 WorkflowContext provides: pages, schema, llm client (with model selection per call), pdf parser, corner cases,
 shared patterns, model tier list. Builder can generate arbitrarily complex logic inside extract(), including
 choosing different models for different fields. Code is validated via AST parsing before commit.

 2. Separate Git Repo for Workflows

 workflows/ has its own .git. Workflow evolution history is independent of project code. Rollback is per-task. Uses
  GitPython for programmatic git ops.

 3. Observer Non-Invasiveness

 Observer produces judgments alongside extractions — never modifies Worker output. Even if Observer is wrong, no
 data is corrupted.

 4. Corner Case Isolation

 - Systemic issue (>10% docs affected) → rewrite workflow
 - Corner case (<10% docs) → add to corner_cases table with pattern + resolution
 - Worker checks corner cases via pattern match before standard extraction (high threshold, RAG-like)

 5. Progressive Cost Reduction (Model Downgrade + Code Migration)

 The cost reduction strategy has two dimensions: model downsizing AND code migration.

 Dimension 1: Model Downgrade — SiliconFlow offers many model sizes. Builder tracks per-field accuracy across
 models and downgrades when safe:
 Tier 0 (bootstrap):  235B vision model     → highest cost, highest capability
 Tier 1:              72B model              → good accuracy, lower cost
 Tier 2:              32B model              → sufficient for well-understood fields
 Tier 3:              14B / 8B model         → near-minimum cost, simple fields
 The Worker workflow specifies which model to use per field. Builder downgrades field-by-field: if a field
 maintains >95% accuracy on a smaller model, lock it to that model.

 Dimension 2: Code Migration — For fields with highly predictable patterns:
 LLM call → regex / Python code → zero inference cost
 This only applies when patterns are truly deterministic (dates, IDs, fixed-format fields).

 Combined progression:
 Iter 0:  100% @ 235B model                         → ~$X/doc
 Iter 3:  30% @ 235B, 50% @ 32B, 20% code/regex     → ~$0.4X/doc
 Iter 10: 10% @ 72B, 30% @ 14B, 60% code/regex      → ~$0.1X/doc
 Builder's optimize_for_cost() handles both dimensions: per-field model selection + code migration.

 6. Confidence Scoring

 Per-field composite score from: LLM self-confidence, extraction method prior, historical accuracy, source text
 clarity, corner case match. Builder tunes weights based on Observer calibration.

 7. Shared Pattern Library (EvoMap-inspired)

 Successful field extraction patterns promoted to shared library. New tasks check library during bootstrap.
 Patterns have confidence scores updated by usage stats.

 ---
 Bootstrap Sequence

 ae new "extract key terms from these contracts" --input ./pdfs/

 1. Create Task record (status=BOOTSTRAPPING)
 2. Ingest PDFs → Document records (compute hash, mark as sample)
 3. Builder analyzes docs (vision model looks at pages → DocumentAnalysis)
 4. Builder proposes schema (field names, types, descriptions)
 5. Builder generates initial workflow Python code
 6. Git commit to workflows/{task}/extract_v1.py
 7. Worker runs extraction on all sample docs
 8. Observer judges ALL results (100% sampling at iter 0)
 9. CLI displays: schema, sample results, accuracy assessment
 10. Optional: user provides feedback → triggers evolution
 11. Task.status=RUNNING, Task.iteration=1

 Evolution Loop

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

 Observer sampling rate: 100% early → 5% when stable (auto-computed). Random sampling always active to catch
 regressions.

 Evolution stops when task.iteration >= MAX_ITERATIONS (from .env). At that point, the system enters production
 mode: Worker runs with locked workflow, Observer does random sampling only, Builder is not invoked unless user
 explicitly runs ae evolve.

 ---
 CLI Commands

 ┌──────────────────────────────────────┬─────────────────────────────────────────────┐
 │               Command                │                 Description                 │
 ├──────────────────────────────────────┼─────────────────────────────────────────────┤
 │ ae new <desc> --input <path>         │ Create task, run full bootstrap             │
 ├──────────────────────────────────────┼─────────────────────────────────────────────┤
 │ ae run <task> [--input <path>]       │ Run extraction (optionally ingest new docs) │
 ├──────────────────────────────────────┼─────────────────────────────────────────────┤
 │ ae status [<task>]                   │ Show task status, accuracy, cost metrics    │
 ├──────────────────────────────────────┼─────────────────────────────────────────────┤
 │ ae observe <task> [--full]           │ Trigger observer evaluation                 │
 ├──────────────────────────────────────┼─────────────────────────────────────────────┤
 │ ae feedback <task>                   │ Interactive feedback mode                   │
 ├──────────────────────────────────────┼─────────────────────────────────────────────┤
 │ ae evolve <task>                     │ Manually trigger builder evolution          │
 ├──────────────────────────────────────┼─────────────────────────────────────────────┤
 │ ae export <task> --format json|excel │ Export results                              │
 ├──────────────────────────────────────┼─────────────────────────────────────────────┤
 │ ae schema <task>                     │ Show current extraction schema              │
 ├──────────────────────────────────────┼─────────────────────────────────────────────┤
 │ ae history <task>                    │ Show evolution history                      │
 ├──────────────────────────────────────┼─────────────────────────────────────────────┤
 │ ae workflow <task> [--diff v1 v2]    │ Show/diff workflow code                     │
 ├──────────────────────────────────────┼─────────────────────────────────────────────┤
 │ ae patterns                          │ List shared pattern library                 │
 └──────────────────────────────────────┴─────────────────────────────────────────────┘

 ---
 .env Configuration

 # --- API Keys ---
 SILICONFLOW_API_KEY=sk-...
 SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
 MINERU_API_KEY=eyJ...

 # --- LLM Models (initial assignment, Builder may adjust worker models per field) ---
 AE_WORKER_MODEL=Qwen/Qwen3-VL-235B-A22B-Instruct
 AE_BUILDER_MODEL=Pro/zai-org/GLM-5
 AE_OBSERVER_MODEL=Pro/moonshotai/Kimi-K2.5
 AE_OBSERVER_VISION_MODEL=Qwen/Qwen3-VL-235B-A22B-Instruct

 # --- Model Downgrade Tiers (Builder uses these for cost optimization) ---
 # Comma-separated from largest to smallest. Builder tries downgrading field-by-field.
 AE_WORKER_MODEL_TIERS=Qwen/Qwen3-VL-235B-A22B-Instruct,Qwen/Qwen2.5-72B-Instruct,Qwen/Qwen2.5-32B-Instruct,Qwen/Qw
 en2.5-14B-Instruct,Qwen/Qwen2.5-7B-Instruct

 # --- Database ---
 AE_DATABASE_URL=postgresql://localhost:5432/anything_extractor
 AE_REDIS_URL=redis://localhost:6379/0

 # --- Language (en | zh | bilingual) ---
 AE_LANGUAGE=bilingual

 # --- Evolution ---
 MAX_ITERATIONS=20

 # --- Paths ---
 AE_WORKFLOWS_DIR=./workflows
 AE_DATA_DIR=./data

 ---
 Dependencies

 [project]
 name = "anything-extractor"
 version = "0.1.0"
 requires-python = ">=3.11"
 dependencies = [
     "typer>=0.9",
     "openai>=1.0",
     "sqlalchemy>=2.0",
     "alembic>=1.12",
     "psycopg2-binary",
     "redis>=5.0",
     "pymupdf>=1.23",
     "pydantic>=2.0",
     "pydantic-settings",
     "openpyxl",
     "rich",
     "gitpython",
 ]

 [project.scripts]
 ae = "ae.cli:app"

 ---
 Implementation Order

 1. Foundation: config.py, db.py, models.py, llm.py, pdf.py
 2. CLI skeleton: cli.py with new and status commands
 3. Builder bootstrap: bootstrap.py, schema_mgr.py, codegen.py, git_ops.py
 4. Worker: runner.py, confidence.py, postprocess.py
 5. Observer: judge.py, sampler.py, trigger.py
 6. Evolution loop: analyzer.py, full codegen modification, wire trigger → builder
 7. Polish: feedback.py, remaining CLI commands, pattern_lib.py, cost optimization

 ---
 Bilingual Design

 All prompts in src/ae/shared/prompts.py are stored in three variants: en, zh, bilingual. The AE_LANGUAGE setting
 controls which variant is used. Since the first corpus is Chinese research reports, the system must handle Chinese
  natively — field names, schema descriptions, and extraction instructions all support Chinese. In bilingual mode,
 prompts include both languages so the LLM can handle mixed-language documents.

 Key bilingual requirements:
 - Schema field descriptions in both languages (e.g., {"name": "公司名称/company_name", ...})
 - Observer judgment prompts reference document content in original language
 - CLI output renders Chinese text correctly (Rich library handles this)
 - Filename parsing understands Chinese characters (the corpus filenames encode metadata:
 {券商}：{标题}_{作者}_{类别}_{日期}.pdf)

 ---
 First Corpus: Research Reports

 The first real dataset is corpus_research_report_202602/ containing ~100+ Chinese securities research reports
 organized by date:

 corpus_research_report_202602/
 ├── 2026-02-06/   (~49 PDFs)
 ├── 2026-02-09/
 ├── 2026-02-10/
 ├── 2026-02-11/
 ├── 2026-02-12/
 └── 2026-02-13/

 Document categories (parsed from filenames): 晨午晚报 (morning briefs), 行业研究 (industry research), 公司研究
 (company research), 策略研究 (strategy research), 宏观经济 (macroeconomics)

 Filename structure: {证券公司}：{报告标题}_{作者}_{类别}_{日期}.pdf

 This corpus will be used for the first bootstrap test:
 ae new "从这些研报中提取有用的信息" --input ./corpus_research_report_202602/

 ---
 Verification

 1. Bootstrap test: ae new "从这些研报中提取有用的信息" --input ./corpus_research_report_202602/ — verify schema
 proposal (should discover fields like 券商名称, 报告标题, 研究领域, 核心观点, 投资建议, etc.), workflow
 generation, first extraction run, observer judgment
 2. Evolution test: Provide negative feedback on a field → verify Builder diagnoses issue, generates new workflow
 version, git commits, re-runs, accuracy improves
 3. Model downgrade test: After 3+ iterations, verify Builder starts downgrading stable fields to smaller models
 (e.g., 235B→72B→32B)
 4. Code migration test: After 5+ iterations, verify deterministic fields (dates, broker names) migrate from LLM to
  regex
 5. Max iteration test: Verify system stops evolving after MAX_ITERATIONS=20 iterations
 6. Multi-task test: Create two tasks, verify shared patterns propagate from task A to task B
 7. Export test: ae export <task> --format excel → verify correct Excel output with Chinese content