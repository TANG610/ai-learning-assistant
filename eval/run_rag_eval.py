"""
Run offline RAG evaluation for the AI learning assistant.

Default mode evaluates retrieval only and does not call any external LLM.
Use --generate to also produce model answers for manual grading.

Examples:
    python eval/run_rag_eval.py
    python eval/run_rag_eval.py --scope-mode all
    python eval/run_rag_eval.py --generate
    python eval/run_rag_eval.py --grades eval/manual_grades.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))


DEFAULT_DATASET = PROJECT_ROOT / "eval" / "rag_eval_dataset_v0_1.jsonl"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "eval" / "results"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def chunk_id(doc_id: Any, chunk_index: Any) -> str | None:
    if doc_id is None or chunk_index is None:
        return None
    try:
        return f"{int(doc_id)}:{int(chunk_index)}"
    except (TypeError, ValueError):
        return None


def compact_result(item: dict[str, Any]) -> dict[str, Any]:
    cid = chunk_id(item.get("doc_id"), item.get("chunk_index"))
    text = item.get("text") or ""
    return {
        "chunk_id": cid,
        "doc_id": item.get("doc_id"),
        "chunk_index": item.get("chunk_index"),
        "score": item.get("score"),
        "rerank_score": item.get("rerank_score", item.get("score")),
        "vector_score": item.get("vector_score"),
        "keyword_score": item.get("keyword_score"),
        "distance": item.get("distance"),
        "retrieval_sources": item.get("retrieval_sources", []),
        "matched_terms": item.get("matched_terms", []),
        "preview": text[:220].replace("\n", " "),
    }


def first_hit_rank(results: list[dict[str, Any]], acceptable_chunks: set[str]) -> int | None:
    if not acceptable_chunks:
        return None
    for rank, item in enumerate(results, start=1):
        cid = chunk_id(item.get("doc_id"), item.get("chunk_index"))
        if cid in acceptable_chunks:
            return rank
    return None


def evaluate_retrieval_case(
    case: dict[str, Any],
    results: list[dict[str, Any]],
    ks: tuple[int, ...],
    threshold: float,
) -> dict[str, Any]:
    retrieval_cfg = case.get("retrieval") or {}
    acceptable_chunks = set(retrieval_cfg.get("acceptable_chunk_ids") or [])
    must_hit = bool(retrieval_cfg.get("must_hit")) and bool(acceptable_chunks)
    rank = first_hit_rank(results, acceptable_chunks)
    accepted_results = [
        item for item in results
        if float(item.get("score") or 0.0) > threshold
    ]
    accepted_rank = first_hit_rank(accepted_results, acceptable_chunks)

    metrics = {
        "must_hit": must_hit,
        "first_hit_rank": rank,
        "accepted_first_hit_rank": accepted_rank,
        "accepted_count": len(accepted_results),
    }
    for k in ks:
        metrics[f"hit_at_{k}"] = bool(rank is not None and rank <= k) if must_hit else None
        metrics[f"accepted_hit_at_{k}"] = (
            bool(accepted_rank is not None and accepted_rank <= k) if must_hit else None
        )
    return metrics


def summarize_retrieval(case_results: list[dict[str, Any]], ks: tuple[int, ...]) -> dict[str, Any]:
    evidence_backed = [
        item for item in case_results
        if item["retrieval_metrics"]["must_hit"]
    ]
    summary: dict[str, Any] = {
        "evidence_case_count": len(evidence_backed),
        "all_case_count": len(case_results),
    }
    if not evidence_backed:
        for k in ks:
            summary[f"recall_at_{k}"] = None
            summary[f"accepted_recall_at_{k}"] = None
        summary["mrr"] = None
        summary["accepted_mrr"] = None
        return summary

    for k in ks:
        summary[f"recall_at_{k}"] = round(
            sum(1 for item in evidence_backed if item["retrieval_metrics"][f"hit_at_{k}"])
            / len(evidence_backed),
            4,
        )
        summary[f"accepted_recall_at_{k}"] = round(
            sum(1 for item in evidence_backed if item["retrieval_metrics"][f"accepted_hit_at_{k}"])
            / len(evidence_backed),
            4,
        )

    rr_values = []
    accepted_rr_values = []
    for item in evidence_backed:
        rank = item["retrieval_metrics"]["first_hit_rank"]
        accepted_rank = item["retrieval_metrics"]["accepted_first_hit_rank"]
        rr_values.append(0.0 if rank is None else 1.0 / rank)
        accepted_rr_values.append(0.0 if accepted_rank is None else 1.0 / accepted_rank)
    summary["mrr"] = round(sum(rr_values) / len(rr_values), 4)
    summary["accepted_mrr"] = round(sum(accepted_rr_values) / len(accepted_rr_values), 4)
    return summary


def load_grades(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    grades = {}
    for row in load_jsonl(path):
        case_id = row.get("id")
        if not case_id:
            raise ValueError(f"Grade row missing id: {row}")
        grades[str(case_id)] = row
    return grades


def summarize_grades(case_results: list[dict[str, Any]], grades: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if not grades:
        return None

    graded = []
    for item in case_results:
        grade = grades.get(item["id"])
        if not grade:
            continue
        score = float(grade.get("answer_score", 0.0))
        if math.isnan(score):
            score = 0.0
        hallucination_type = str(grade.get("hallucination_type", "none") or "none")
        graded.append({
            "id": item["id"],
            "answer_score": max(0.0, min(1.0, score)),
            "hallucination_type": hallucination_type,
        })

    if not graded:
        return {
            "graded_case_count": 0,
            "answer_accuracy": None,
            "hallucination_rate": None,
        }

    hallucinated = [
        item for item in graded
        if item["hallucination_type"] not in ("none", "no")
    ]
    return {
        "graded_case_count": len(graded),
        "answer_accuracy": round(sum(item["answer_score"] for item in graded) / len(graded), 4),
        "hallucination_rate": round(len(hallucinated) / len(graded), 4),
        "hallucination_count": len(hallucinated),
    }


def build_generation_prompt(case: dict[str, Any], context_chunks: list[str]) -> str:
    context_text = "\n\n---\n\n".join(
        f"[资料片段 {i + 1}]\n{chunk}"
        for i, chunk in enumerate(context_chunks)
    )
    if not context_text:
        context_text = "（本次检索没有找到超过阈值的资料片段。）"

    return (
        "请基于给定资料回答用户问题。若资料不足，请明确说明知识库没有足够依据，"
        "不要编造。若问题前提与资料矛盾，请先纠正前提。\n\n"
        f"{context_text}\n\n---\n\n"
        f"用户问题：{case['question']}"
    )


def generate_answer(case: dict[str, Any], context_chunks: list[str]) -> str:
    from services.claude_service import LLMService

    llm = LLMService()
    if not llm.client:
        raise RuntimeError("No LLM client configured. Check MODEL_PROVIDERS or LLM_API_KEY.")
    messages = [
        {"role": "system", "content": llm.system_prompt},
        {"role": "user", "content": build_generation_prompt(case, context_chunks)},
    ]
    return llm._call(messages)


def resolve_case_doc_id(case: dict[str, Any], args: argparse.Namespace) -> int | None:
    if args.doc_id is not None:
        return args.doc_id
    if args.scope_mode == "all":
        return None

    evidence = case.get("evidence") or []
    for item in evidence:
        doc_id = item.get("doc_id")
        if doc_id is not None:
            return int(doc_id)
    return None


def run_eval(args: argparse.Namespace) -> dict[str, Any]:
    from services.document_service import DocumentService

    dataset = load_jsonl(args.dataset)
    if args.limit:
        dataset = dataset[: args.limit]
    grades = load_grades(args.grades)

    case_results = []
    for index, case in enumerate(dataset, start=1):
        print(f"[{index}/{len(dataset)}] {case['id']} {case['question']}")
        search_doc_id = resolve_case_doc_id(case, args)
        raw_results = DocumentService.search_documents(
            case["question"],
            doc_id=search_doc_id,
            top_k=args.top_k,
            user_id=args.user_id,
        )
        retrieval_metrics = evaluate_retrieval_case(case, raw_results, args.ks, args.threshold)
        context_chunks = [
            item.get("text") or ""
            for item in raw_results
            if float(item.get("score") or 0.0) > args.threshold
        ]

        assistant_answer = None
        generation_error = None
        if args.generate:
            try:
                assistant_answer = generate_answer(case, context_chunks)
            except Exception as exc:
                generation_error = str(exc)

        grade = grades.get(case["id"])
        case_results.append({
            "id": case["id"],
            "question": case["question"],
            "question_type": case.get("question_type"),
            "expected_behavior": case.get("expected_behavior"),
            "gold_answer": case.get("gold_answer"),
            "evidence": case.get("evidence", []),
            "search_doc_id": search_doc_id,
            "answer_rubric": case.get("answer_rubric", {}),
            "retrieval_metrics": retrieval_metrics,
            "retrieved": [compact_result(item) for item in raw_results],
            "assistant_answer": assistant_answer,
            "generation_error": generation_error,
            "grade": grade,
        })

    retrieval_summary = summarize_retrieval(case_results, args.ks)
    grade_summary = summarize_grades(case_results, grades)
    summary = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "dataset": str(args.dataset),
        "case_count": len(case_results),
        "user_id": args.user_id,
        "doc_id": args.doc_id,
        "scope_mode": args.scope_mode,
        "top_k": args.top_k,
        "score_threshold": args.threshold,
        "ks": list(args.ks),
        "generated_answers": bool(args.generate),
        "retrieval": retrieval_summary,
        "answers": grade_summary,
    }
    return {
        "summary": summary,
        "cases": case_results,
    }


def parse_ks(value: str) -> tuple[int, ...]:
    ks = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        k = int(part)
        if k <= 0:
            raise argparse.ArgumentTypeError("K values must be positive integers.")
        ks.append(k)
    if not ks:
        raise argparse.ArgumentTypeError("Provide at least one K value.")
    return tuple(sorted(set(ks)))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run RAG retrieval and answer evaluation.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=None, help="JSON output path.")
    parser.add_argument("--cases-output", type=Path, default=None, help="Optional JSONL per-case output path.")
    parser.add_argument("--grades", type=Path, default=None, help="Manual grades JSONL path.")
    parser.add_argument("--user-id", type=int, default=3)
    parser.add_argument("--doc-id", type=int, default=None, help="Optional document scope.")
    parser.add_argument(
        "--scope-mode",
        choices=("evidence_doc", "all"),
        default="evidence_doc",
        help=(
            "evidence_doc mirrors the app's single-document QA by searching the first "
            "evidence doc for each case. all searches the user's whole knowledge base."
        ),
    )
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--threshold", type=float, default=0.3)
    parser.add_argument("--ks", type=parse_ks, default=(3, 8), help="Comma-separated K values, e.g. 3,8.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--generate", action="store_true", help="Call configured LLM to generate answers.")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    if not args.dataset.exists():
        print(f"Dataset not found: {args.dataset}", file=sys.stderr)
        return 2

    payload = run_eval(args)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = args.output or DEFAULT_OUTPUT_DIR / f"rag_eval_{timestamp}.json"
    cases_output = args.cases_output or DEFAULT_OUTPUT_DIR / f"rag_eval_cases_{timestamp}.jsonl"
    write_json(output, payload)
    write_jsonl(cases_output, payload["cases"])

    summary = payload["summary"]
    print("\n=== Summary ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nWrote summary: {output}")
    print(f"Wrote cases:   {cases_output}")
    if not summary["answers"]:
        print("\nAnswer accuracy and hallucination rate require --grades.")
        print("Grade JSONL rows: {\"id\":\"rag_001\",\"answer_score\":1,\"hallucination_type\":\"none\"}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
