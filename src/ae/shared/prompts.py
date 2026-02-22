"""Bilingual prompt templates (EN/ZH/bilingual)."""

from __future__ import annotations

from typing import Any

from ae.config import get_settings

# --- Prompt Storage ---

PROMPTS: dict[str, dict[str, str]] = {
    # === Builder Prompts ===
    "builder_analyze_docs": {
        "en": """You are an expert document analyst. Analyze these sample documents and determine:
1. What type of documents these are
2. The language and structure
3. Key sections and their purposes
4. What fields could be extracted

Document content (from {num_samples} sample documents):
{doc_contents}

Respond in JSON format:
{{
    "document_type": "...",
    "language": "...",
    "structure_description": "...",
    "key_sections": ["..."],
    "suggested_fields": [
        {{"name": "field_name", "type": "string|number|date|list|text|boolean", "description": "...", "required": true/false, "extraction_hint": "..."}}
    ],
    "complexity": "low|medium|high",
    "notes": ["..."]
}}""",
        "zh": """你是一位专业的文档分析师。请分析这些样本文档并确定：
1. 这些是什么类型的文档
2. 语言和结构
3. 关键章节及其用途
4. 可以提取哪些字段

文档内容（来自 {num_samples} 个样本文档）：
{doc_contents}

请以 JSON 格式回答：
{{
    "document_type": "...",
    "language": "...",
    "structure_description": "...",
    "key_sections": ["..."],
    "suggested_fields": [
        {{"name": "字段名", "type": "string|number|date|list|text|boolean", "description": "...", "description_zh": "...", "required": true/false, "extraction_hint": "..."}}
    ],
    "complexity": "low|medium|high",
    "notes": ["..."]
}}""",
        "bilingual": """You are an expert document analyst. Analyze these sample documents and determine:
你是一位专业的文档分析师。请分析这些样本文档并确定：

1. What type of documents these are / 这些是什么类型的文档
2. The language and structure / 语言和结构
3. Key sections and their purposes / 关键章节及其用途
4. What fields could be extracted / 可以提取哪些字段

Document content (from {num_samples} samples) / 文档内容（来自 {num_samples} 个样本）：
{doc_contents}

Respond in JSON format / 请以 JSON 格式回答：
{{
    "document_type": "...",
    "language": "...",
    "structure_description": "...",
    "key_sections": ["..."],
    "suggested_fields": [
        {{"name": "field_name_字段名", "type": "string|number|date|list|text|boolean", "description": "English description", "description_zh": "中文描述", "required": true/false, "extraction_hint": "How to find this field / 如何找到此字段"}}
    ],
    "complexity": "low|medium|high",
    "notes": ["..."]
}}""",
    },

    "builder_propose_schema": {
        "en": """Based on the document analysis, propose a final extraction schema.

User's task description: {task_description}

Document analysis:
{analysis}

Requirements:
- Include all fields that match the user's extraction goal
- Each field must have a clear type and extraction strategy
- Mark fields as required only if they appear in >80% of documents
- Field names should be snake_case

Respond in JSON format:
{{
    "fields": [
        {{"name": "...", "type": "string|number|date|list|text|boolean", "description": "...", "required": true/false, "extraction_hint": "..."}}
    ],
    "description": "Schema description"
}}""",
        "zh": """基于文档分析结果，提出最终的提取模式（schema）。

用户的任务描述：{task_description}

文档分析结果：
{analysis}

要求：
- 包含所有与用户提取目标匹配的字段
- 每个字段必须有明确的类型和提取策略
- 仅当字段出现在超过80%的文档中时，才标记为必需
- 字段名使用下划线分隔

请以 JSON 格式回答：
{{
    "fields": [
        {{"name": "...", "type": "string|number|date|list|text|boolean", "description": "...", "description_zh": "...", "required": true/false, "extraction_hint": "..."}}
    ],
    "description": "模式描述"
}}""",
        "bilingual": """Based on the document analysis, propose a final extraction schema.
基于文档分析结果，提出最终的提取模式。

User's task description / 用户任务描述: {task_description}

Document analysis / 文档分析:
{analysis}

Requirements / 要求:
- Include all fields matching the extraction goal / 包含所有匹配提取目标的字段
- Each field needs a clear type and extraction strategy / 每个字段需要明确的类型和提取策略
- Mark required only if present in >80% of docs / 仅当出现在80%以上文档中才标记为必需
- Field names: snake_case (English) or 中文描述

Respond in JSON / 请以 JSON 格式回答：
{{
    "fields": [
        {{"name": "field_name", "type": "string|number|date|list|text|boolean", "description": "English desc", "description_zh": "中文描述", "required": true/false, "extraction_hint": "How to extract / 提取方式"}}
    ],
    "description": "Schema description / 模式描述"
}}""",
    },

    "builder_generate_workflow": {
        "en": """Generate a Python workflow module for extracting data from documents.

Schema:
{schema}

Sample document content (for understanding the format):
{sample_content}

Document analysis:
{analysis}

Available in WorkflowContext:
- context.pages: list of page dicts with 'text', 'page_number'
- context.schema: the schema definition
- context.llm: LLM client module with chat(), chat_json(), chat_vision() functions
- context.pdf_path: path to the PDF file
- context.parse_result: full parse result
- context.filename_metadata: dict with 'broker', 'title', 'authors', 'category', 'date' from filename
- context.get_model_for_field(field_name): get the assigned model for a field
- context.track_llm_usage(calls, tokens): track LLM usage
- context.corner_cases: list of known corner cases
- context.shared_patterns: list of shared extraction patterns

The module MUST define:
```python
def extract(context) -> ExtractionResult:
    ...
```

Import ExtractionResult from ae.shared.types.

Guidelines:
- Extract metadata from filename first (zero-cost)
- Use LLM calls only for fields that need understanding
- Group related fields into single LLM calls to reduce cost
- Use context.get_model_for_field() to select the right model
- Track LLM usage with context.track_llm_usage()
- Set field_confidences between 0.0 and 1.0
- Handle missing/unextractable fields gracefully (set to None)

Generate ONLY the Python code, no markdown fences.""",
        "zh": """生成一个用于从文档中提取数据的 Python 工作流模块。

模式（Schema）：
{schema}

样本文档内容（用于理解格式）：
{sample_content}

文档分析结果：
{analysis}

WorkflowContext 中可用的属性：
- context.pages: 页面字典列表，包含 'text', 'page_number'
- context.schema: 模式定义
- context.llm: LLM 客户端模块，有 chat(), chat_json(), chat_vision() 函数
- context.pdf_path: PDF 文件路径
- context.parse_result: 完整解析结果
- context.filename_metadata: 从文件名解析的字典，包含 'broker', 'title', 'authors', 'category', 'date'
- context.get_model_for_field(field_name): 获取字段的分配模型
- context.track_llm_usage(calls, tokens): 跟踪 LLM 使用
- context.corner_cases: 已知的边缘情况列表
- context.shared_patterns: 共享的提取模式列表

模块必须定义：
```python
def extract(context) -> ExtractionResult:
    ...
```

从 ae.shared.types 导入 ExtractionResult。

指南：
- 优先从文件名提取元数据（零成本）
- 仅对需要理解的字段使用 LLM 调用
- 将相关字段分组到单个 LLM 调用中以降低成本
- 使用 context.get_model_for_field() 选择合适的模型
- 使用 context.track_llm_usage() 跟踪 LLM 使用
- 设置 field_confidences 在 0.0 到 1.0 之间
- 优雅处理缺失/无法提取的字段（设为 None）

只生成 Python 代码，不要 markdown 围栏。""",
        "bilingual": """Generate a Python workflow module for extracting data from documents.
生成一个用于从文档中提取数据的 Python 工作流模块。

Schema / 模式：
{schema}

Sample document content / 样本文档内容：
{sample_content}

Document analysis / 文档分析：
{analysis}

Available in WorkflowContext / 可用属性：
- context.pages: list of page dicts with 'text', 'page_number' / 页面列表
- context.schema: the schema definition / 模式定义
- context.llm: LLM client module with chat(), chat_json(), chat_vision() / LLM客户端
- context.pdf_path: path to PDF / PDF路径
- context.parse_result: full parse result / 完整解析结果
- context.filename_metadata: dict from filename parsing (broker, title, authors, category, date) / 文件名元数据
- context.get_model_for_field(field_name): model per field / 字段模型
- context.track_llm_usage(calls, tokens): track usage / 跟踪使用
- context.corner_cases: known corner cases / 边缘情况
- context.shared_patterns: shared patterns / 共享模式

The module MUST define / 模块必须定义:
```python
def extract(context) -> ExtractionResult:
    ...
```

Import ExtractionResult from ae.shared.types.

Guidelines / 指南:
- Extract metadata from filename first (zero-cost) / 优先从文件名提取
- Use LLM only for fields needing understanding / 仅对需理解的字段用LLM
- Group related fields into single LLM calls / 将相关字段分组调用
- Use context.get_model_for_field() for model selection / 使用模型选择
- Track LLM usage / 跟踪LLM使用
- Set field_confidences 0.0-1.0
- Handle missing fields gracefully (None) / 优雅处理缺失字段

Generate ONLY Python code, no markdown fences.
只生成 Python 代码，不要 markdown。""",
    },

    # === Worker Prompts ===
    "worker_extract_fields": {
        "en": """Extract the following fields from this document content.

Fields to extract:
{fields_description}

Document content:
{document_content}

Respond in JSON format with field names as keys.
For fields you cannot find, use null.
For list-type fields, return a JSON array.
""",
        "zh": """从以下文档内容中提取指定字段。

需要提取的字段：
{fields_description}

文档内容：
{document_content}

请以 JSON 格式回答，字段名作为键。
无法找到的字段使用 null。
列表类型的字段返回 JSON 数组。
""",
        "bilingual": """Extract the following fields from this document content.
从以下文档内容中提取指定字段。

Fields to extract / 需要提取的字段：
{fields_description}

Document content / 文档内容：
{document_content}

Respond in JSON format with field names as keys.
请以 JSON 格式回答，字段名作为键。
For fields you cannot find, use null. / 无法找到的字段使用 null。
For list-type fields, return a JSON array. / 列表类型返回数组。
""",
    },

    # === Observer Prompts ===
    "observer_judge_extraction": {
        "en": """You are a quality judge evaluating data extraction results.

Original document content:
{document_content}

Extraction schema:
{schema}

Extraction result:
{extraction_result}

For each field, evaluate:
1. Is the extracted value correct? (correct/partial/incorrect/missing)
2. Score from 0.0 to 1.0
3. Brief reasoning

Respond in JSON:
{{
    "overall_result": "correct|partial|incorrect",
    "overall_score": 0.0-1.0,
    "field_judgments": [
        {{"field_name": "...", "result": "correct|partial|incorrect|missing", "score": 0.0-1.0, "reasoning": "..."}}
    ],
    "reasoning": "Overall assessment"
}}""",
        "zh": """你是一位评估数据提取结果的质量评审员。

原始文档内容：
{document_content}

提取模式（Schema）：
{schema}

提取结果：
{extraction_result}

对每个字段评估：
1. 提取的值是否正确？（correct/partial/incorrect/missing）
2. 评分 0.0 到 1.0
3. 简要推理

请以 JSON 格式回答：
{{
    "overall_result": "correct|partial|incorrect",
    "overall_score": 0.0-1.0,
    "field_judgments": [
        {{"field_name": "...", "result": "correct|partial|incorrect|missing", "score": 0.0-1.0, "reasoning": "..."}}
    ],
    "reasoning": "总体评估"
}}""",
        "bilingual": """You are a quality judge evaluating data extraction results.
你是一位评估数据提取结果的质量评审员。

Original document content / 原始文档内容：
{document_content}

Extraction schema / 提取模式：
{schema}

Extraction result / 提取结果：
{extraction_result}

For each field, evaluate / 对每个字段评估：
1. Is the value correct? / 值是否正确？ (correct/partial/incorrect/missing)
2. Score 0.0-1.0 / 评分
3. Brief reasoning / 简要推理

Respond in JSON / 请以 JSON 格式回答：
{{
    "overall_result": "correct|partial|incorrect",
    "overall_score": 0.0-1.0,
    "field_judgments": [
        {{"field_name": "...", "result": "correct|partial|incorrect|missing", "score": 0.0-1.0, "reasoning": "..."}}
    ],
    "reasoning": "Overall assessment / 总体评估"
}}""",
    },

    "observer_judge_vision": {
        "en": """You are a quality judge with vision capabilities. Compare the extraction result against the actual PDF page image.

Extraction result:
{extraction_result}

Schema:
{schema}

Look at the PDF page image and verify each extracted field against what you see.

Respond in JSON:
{{
    "overall_result": "correct|partial|incorrect",
    "overall_score": 0.0-1.0,
    "field_judgments": [
        {{"field_name": "...", "result": "correct|partial|incorrect|missing", "score": 0.0-1.0, "reasoning": "..."}}
    ],
    "reasoning": "Overall assessment based on visual verification"
}}""",
        "zh": """你是一位具有视觉能力的质量评审员。将提取结果与实际的 PDF 页面图像进行比较。

提取结果：
{extraction_result}

模式：
{schema}

查看 PDF 页面图像，验证每个提取字段是否与你所看到的一致。

请以 JSON 格式回答：
{{
    "overall_result": "correct|partial|incorrect",
    "overall_score": 0.0-1.0,
    "field_judgments": [
        {{"field_name": "...", "result": "correct|partial|incorrect|missing", "score": 0.0-1.0, "reasoning": "..."}}
    ],
    "reasoning": "基于视觉验证的总体评估"
}}""",
        "bilingual": """You are a quality judge with vision capabilities.
你是一位具有视觉能力的质量评审员。

Compare the extraction result against the PDF page image.
将提取结果与 PDF 页面图像进行比较。

Extraction result / 提取结果：
{extraction_result}

Schema / 模式：
{schema}

Verify each field against the image / 验证每个字段。

Respond in JSON:
{{
    "overall_result": "correct|partial|incorrect",
    "overall_score": 0.0-1.0,
    "field_judgments": [
        {{"field_name": "...", "result": "correct|partial|incorrect|missing", "score": 0.0-1.0, "reasoning": "..."}}
    ],
    "reasoning": "Assessment / 评估"
}}""",
    },

    # === Builder Diagnosis ===
    "builder_diagnose_issues": {
        "en": """Analyze the observer judgments to diagnose extraction issues.

Failed/partial extractions:
{failed_extractions}

Observer judgments:
{judgments}

Current schema:
{schema}

Current workflow code:
{workflow_code}

Determine:
1. Is this a systemic issue (>10% of docs affected) or corner cases?
2. Which fields are most affected?
3. What is the root cause?
4. How should it be fixed?

Respond in JSON:
{{
    "issue_type": "systemic|corner_case",
    "affected_fields": ["..."],
    "affected_percentage": 0.0-1.0,
    "description": "...",
    "suggested_fix": "...",
    "evidence": [...]
}}""",
        "zh": """分析观察者评判结果，诊断提取问题。

失败/部分提取：
{failed_extractions}

观察者评判：
{judgments}

当前模式：
{schema}

当前工作流代码：
{workflow_code}

确定：
1. 这是系统性问题（影响>10%的文档）还是边缘情况？
2. 哪些字段受影响最大？
3. 根本原因是什么？
4. 应该如何修复？

请以 JSON 格式回答：
{{
    "issue_type": "systemic|corner_case",
    "affected_fields": ["..."],
    "affected_percentage": 0.0-1.0,
    "description": "...",
    "suggested_fix": "...",
    "evidence": [...]
}}""",
        "bilingual": """Analyze observer judgments to diagnose extraction issues.
分析观察者评判结果，诊断提取问题。

Failed/partial extractions / 失败的提取：
{failed_extractions}

Observer judgments / 评判结果：
{judgments}

Current schema / 当前模式：
{schema}

Current workflow code / 当前工作流代码：
{workflow_code}

Determine / 确定：
1. Systemic (>10%) or corner case? / 系统性还是边缘情况？
2. Most affected fields / 受影响最大的字段
3. Root cause / 根本原因
4. Fix strategy / 修复策略

Respond in JSON:
{{
    "issue_type": "systemic|corner_case",
    "affected_fields": ["..."],
    "affected_percentage": 0.0-1.0,
    "description": "...",
    "suggested_fix": "...",
    "evidence": [...]
}}""",
    },

    "builder_modify_workflow": {
        "en": """Modify the existing workflow code to fix the diagnosed issues.

Current workflow code:
{workflow_code}

Diagnosis:
{diagnosis}

Schema:
{schema}

Sample failures:
{sample_failures}

Corner cases to handle:
{corner_cases}

Generate the COMPLETE updated workflow module.
Keep the same extract() function signature.
Address the diagnosed issues while preserving working functionality.
Generate ONLY Python code, no markdown fences.""",
        "zh": """修改现有的工作流代码以修复诊断出的问题。

当前工作流代码：
{workflow_code}

诊断结果：
{diagnosis}

模式：
{schema}

失败样本：
{sample_failures}

需要处理的边缘情况：
{corner_cases}

生成完整的更新工作流模块。
保持相同的 extract() 函数签名。
修复诊断的问题同时保留正常功能。
只生成 Python 代码，不要 markdown 围栏。""",
        "bilingual": """Modify the existing workflow code to fix diagnosed issues.
修改现有工作流代码以修复诊断出的问题。

Current workflow code / 当前代码：
{workflow_code}

Diagnosis / 诊断：
{diagnosis}

Schema / 模式：
{schema}

Sample failures / 失败样本：
{sample_failures}

Corner cases / 边缘情况：
{corner_cases}

Generate COMPLETE updated workflow module.
生成完整的更新工作流模块。
Keep extract() signature, fix issues, preserve working code.
保持 extract() 签名，修复问题，保留正常代码。
ONLY Python code, no markdown. / 只生成 Python 代码。""",
    },
}


def get_prompt(name: str, language: str | None = None, **kwargs) -> str:
    """Get a prompt template by name, formatted with the given kwargs."""
    if language is None:
        language = get_settings().ae_language

    templates = PROMPTS.get(name)
    if templates is None:
        raise KeyError(f"Unknown prompt: {name}")

    template = templates.get(language, templates.get("en", ""))
    return template.format(**kwargs)
