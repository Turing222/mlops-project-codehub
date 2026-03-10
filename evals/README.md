# RAG Eval Quick Start

## 1. 数据集格式（JSONL）

每行一条样本，字段：

- `id`: 样本 ID
- `query`: 问题文本（必填）
- `kb_id`: 知识库 ID（可空）
- `expected_chunk_ids`: 期望命中的 chunk_id 列表（可空）
- `expected_keywords`: 期望关键词（可空）
- `reference_answer`: 参考答案（可空）

示例见：`evals/dataset.sample.jsonl`

## 2. 评测脚本

### 检索评测

```bash
python -m evals.eval_retrieval \
  --dataset evals/dataset.sample.jsonl \
  --top-k 5 \
  --output evals/reports/retrieval_report.json
```

指标：

- `hit_at_k`
- `recall_at_k`
- `mrr`

### 回答评测

```bash
python -m evals.eval_rag_answer \
  --dataset evals/dataset.sample.jsonl \
  --top-k 5 \
  --llm mock \
  --output evals/reports/answer_report.json
```

指标：

- `avg_keyword_recall`
- `avg_reference_char_f1`
- `retrieval_hit_rate`

## 3. 说明

- `--llm mock` 用于快速联调，不代表真实效果。
- 真实评测请使用 `--llm real`，并确保 `LLM_*` 环境变量可用。
- 若未安装 `sentence-transformers`，RAG 检索会降级为空结果（脚本仍可执行）。
