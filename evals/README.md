# RAG Eval Quick Start

## 1. 数据集格式（JSONL）

每行一条样本，字段：

- `id`: 样本 ID
- `query`: 问题文本（必填）
- `kb_id`: 知识库 ID（可空）
- `category`: 样本分类，便于按场景汇总（可空，默认 `general`）
- `retrieval_mode`: 指定该样本使用的检索模式，可选 `vector` / `fulltext` / `hybrid`
- `expected_chunk_ids`: 期望命中的 chunk_id 列表（可空）
- `expected_keywords`: 期望关键词（可空）
- `reference_answer`: 参考答案（可空）
- `must_refuse`: 是否期望模型在缺少依据时拒答（可空，默认 `false`）
- `notes`: 备注（可空）

示例见：`evals/dataset.sample.jsonl`

## 2. 评测脚本

### 检索评测

```bash
python -m evals.eval_retrieval \
  --dataset evals/dataset.sample.jsonl \
  --top-k 5 \
  --retrieval-mode hybrid \
  --output evals/reports/retrieval_report.json
```

指标：

- `hit_at_k`
- `recall_at_k`
- `mrr`
- `avg_retrieved_count`
- `avg_top_score`
- `per_category`

### 回答评测

```bash
python -m evals.eval_rag_answer \
  --dataset evals/dataset.sample.jsonl \
  --top-k 5 \
  --llm mock \
  --retrieval-mode hybrid \
  --output evals/reports/answer_report.json
```

指标：

- `avg_keyword_recall`
- `avg_reference_char_f1`
- `retrieval_hit_rate`
- `avg_answer_score`
- `avg_llm_latency_ms`
- `avg_total_latency_ms`
- `avg_completion_tokens`
- `refusal_success_rate`
- `per_category`

## 3. 说明

- `--llm mock` 用于快速联调，不代表真实效果。
- 真实评测请使用 `--llm real`，并确保 `LLM_*` 环境变量可用。
- 若样本本身指定了 `retrieval_mode`，会覆盖命令行默认值。
- `expected_chunk_ids` 适合正式黄金集；如果暂时拿不到 chunk_id，可先用 `expected_keywords` 做弱监督版本。
- `must_refuse=true` 的样本会额外统计拒答成功率，适合“知识库里没有答案时不要瞎编”的场景。
- 若未安装向量化依赖或检索发生异常，脚本会记录错误并继续生成报告。
