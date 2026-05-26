# RAG Evaluation Dataset

This directory contains the offline evaluation dataset for the knowledge-base QA flow.

## Dataset

- `rag_eval_dataset_v0_1.jsonl`: first manually curated golden set.

Each JSONL row is one test case. The current schema is:

```json
{
  "id": "rag_001",
  "question": "用户会问的问题",
  "question_type": "fact | concept | multi_hop | comparison | negative | contradiction",
  "gold_answer": "标准答案要点",
  "evidence": [
    {"doc_id": 10, "chunk_index": 1}
  ],
  "expected_behavior": "answer_from_evidence | refuse_or_say_unknown | correct_false_premise",
  "retrieval": {
    "must_hit": true,
    "acceptable_doc_ids": [10],
    "acceptable_chunk_ids": ["10:1"]
  },
  "answer_rubric": {
    "full_credit": "满分回答应包含的判断标准",
    "partial_credit": "部分得分条件",
    "fail": "失败条件"
  },
  "tags": ["agent", "evaluation"]
}
```

## Metrics

Retrieval metrics:

```text
Recall@K = cases where any acceptable evidence chunk is in top K / all evidence-backed cases
MRR = average of 1 / rank of first acceptable evidence chunk
```

Answer metrics:

```text
Answer Accuracy = sum(answer_score) / number of cases
```

Use `1.0` for correct, `0.5` for partially correct, and `0.0` for wrong.

Hallucination metrics:

```text
Hallucination Rate = answers with unsupported, contradictory, or fake-citation claims / all answers
```

For `negative` cases, a correct answer should say the knowledge base does not contain enough information. If the model invents an answer, count it as a hallucination.

## Runner

Run retrieval-only evaluation:

```powershell
python eval/run_rag_eval.py
```

By default, the runner evaluates cross-document/global search across the user's whole knowledge base. To mirror the app's single-document QA mode, run:

```powershell
python eval/run_rag_eval.py --scope-mode evidence_doc
```

Run a small smoke test:

```powershell
python eval/run_rag_eval.py --limit 3
```

Generate answers with the configured LLM:

```powershell
python eval/run_rag_eval.py --dataset eval/kb_cross_eval_dataset_v0_1.jsonl --generate
```

Run end-to-end automatic evaluation with LLM Judge:

```powershell
python eval/run_rag_eval.py --dataset eval/kb_cross_eval_dataset_v0_1.jsonl --top-k 8 --ks 1,3,5,8 --generate --judge rules-llm --grades-output eval/results/auto_grades.jsonl --badcases-output eval/results/badcases.jsonl
```

`--judge` modes:

- `none`: retrieval only, or generation without grading.
- `rules`: deterministic checks, mainly useful for generation errors and no-answer/refusal cases.
- `llm`: use LLM Judge for answer correctness, faithfulness, and hallucination labels.
- `rules-llm`: apply rule fallback, then prefer LLM Judge when an answer exists.

Compute answer accuracy and hallucination rate from manual or auto grades:

```powershell
python eval/run_rag_eval.py --grades eval/manual_grades.jsonl
```

Manual grade rows use this JSONL shape:

```json
{"id":"rag_001","answer_score":1,"hallucination_type":"none","notes":"正确"}
```

`answer_score` should be `1`, `0.5`, or `0`. `hallucination_type` should be `none`, `unsupported`, `contradiction`, `wrong_citation`, or another short label agreed by the reviewer.

Recommended workflow:

1. Curate or review the Golden Set.
2. Run retrieval metrics automatically.
3. Run `--generate --judge rules-llm` for automatic answer grading.
4. Review only the exported badcases.
5. Promote confirmed badcases back into the Golden Set.

## Suggested Coverage

The first set intentionally mixes:

- single-chunk factual questions
- concept explanation questions
- multi-chunk synthesis questions
- contradiction traps
- negative/no-answer questions

Next expansion target: 50-100 cases, with at least 15% negative cases and at least 20% multi-hop cases.
