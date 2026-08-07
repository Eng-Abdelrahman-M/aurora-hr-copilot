"""Evaluate the agentic RAG system against evaluation/questions.json.

Metrics
  Answer quality : gold-keyword match, citation accuracy (expected doc cited),
                   groundedness (every [POL-*] cited in the answer text was
                   actually returned by a tool this turn — checked
                   programmatically, no judge model).
  Agent behavior : tool selection accuracy, workflow completion, action safety
                   (no unconfirmed ticket creation), refusal/clarification.
  System         : latency p50 / p95.

Usage:  python evaluation/run_eval.py [--limit N] [--out results.md]
Ablation:  RAG_K=1 python evaluation/run_eval.py --limit 8   (vs default k)
Fixed seed: questions run in file order; temperature is 0.
"""
import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# .env loader (same as app.main)
_env = ROOT / ".env"
if _env.exists():
    import os
    for line in _env.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

from app.agent import Agent  # noqa: E402

CITE_RE = re.compile(r"POL-[A-Z]+-\d+")


def grade(q, result, elapsed):
    answer = result["answer"]
    used_tools = {t["tool"] for t in result["trace"]}
    cited_ids = {c["doc_id"] for c in result["citations"]}
    answer_refs = set(CITE_RE.findall(answer))

    g = {"id": q["id"], "category": q["category"], "latency_s": round(elapsed, 1)}

    # tool selection: every expected tool used, no forbidden tool used
    g["tool_selection"] = set(q.get("expected_tools", [])) <= used_tools
    if q.get("expected_tools_any"):
        g["tool_selection"] = g["tool_selection"] and bool(
            set(q["expected_tools_any"]) & used_tools)
    g["action_safety"] = not (set(q.get("forbidden_tools", [])) & used_tools)

    # citation accuracy: expected docs actually cited in the answer text
    expected = set(q.get("expected_docs", []))
    g["citation_accuracy"] = expected <= answer_refs
    if q.get("expected_docs_any"):
        g["citation_accuracy"] = g["citation_accuracy"] and bool(
            set(q["expected_docs_any"]) & answer_refs)

    # groundedness: no doc id appears in the answer that tools didn't return
    g["grounded"] = answer_refs <= cited_ids if answer_refs else True

    # answer correctness: all gold keywords present (case-insensitive)
    low = answer.lower()
    g["keywords"] = all(k.lower() in low for k in q.get("gold_keywords", []))

    # refusal handling: out-of-scope questions must not carry policy citations
    if q.get("expect_refusal"):
        g["keywords"] = not answer_refs and len(result["citations"]) == 0

    # workflow completion = the turn produced a usable, safe, on-tool answer
    g["completed"] = g["tool_selection"] and g["action_safety"] and g["keywords"]
    return g


async def main(limit=None, out="results.md"):
    questions = json.loads((ROOT / "evaluation" / "questions.json").read_text())
    if limit:
        questions = questions[:limit]

    agent = Agent()
    await agent.start()
    rows = []
    try:
        for q in questions:
            t0 = time.perf_counter()
            try:
                result = await agent.run(q["question"], history=[])
            except Exception as e:
                rows.append({"id": q["id"], "category": q["category"], "error": str(e)[:120],
                             "latency_s": round(time.perf_counter() - t0, 1),
                             "tool_selection": False, "action_safety": True,
                             "citation_accuracy": False, "grounded": False,
                             "keywords": False, "completed": False})
                print(f"{q['id']} ERROR {e}")
                continue
            rows.append(grade(q, result, time.perf_counter() - t0))
            r = rows[-1]
            print(f"{q['id']} {'PASS' if r['completed'] else 'fail'} "
                  f"tools={r['tool_selection']} cite={r['citation_accuracy']} "
                  f"grounded={r['grounded']} kw={r['keywords']} {r['latency_s']}s")
    finally:
        await agent.stop()

    def pct(key, subset=None):
        pool = [r for r in rows if subset is None or r["category"] in subset]
        return f"{100 * sum(r[key] for r in pool) / len(pool):.0f}%" if pool else "n/a"

    lats = sorted(r["latency_s"] for r in rows)
    p50 = statistics.median(lats)
    p95 = lats[max(0, int(len(lats) * 0.95) - 1)]

    cite_pool = [r for r in rows if r["category"] in ("policy_simple", "multi_doc", "escalation")]
    md = [
        "# Evaluation results",
        "",
        f"Questions: {len(rows)} · Model: temperature 0 · Retrieval k: "
        f"{__import__('os').environ.get('RAG_K', 'default 5')}",
        "",
        "| Metric | Score |",
        "|---|---|",
        f"| Workflow completion | {pct('completed')} |",
        f"| Tool selection accuracy | {pct('tool_selection')} |",
        f"| Citation accuracy (policy questions) | "
        f"{100 * sum(r['citation_accuracy'] for r in cite_pool) / max(len(cite_pool), 1):.0f}% |",
        f"| Groundedness (no uncited doc refs) | {pct('grounded')} |",
        f"| Gold-keyword answer match | {pct('keywords')} |",
        f"| Action safety (no unconfirmed writes) | {pct('action_safety')} |",
        f"| Latency p50 / p95 | {p50:.1f}s / {p95:.1f}s |",
        "",
        "## Per-question",
        "",
        "| id | category | tools | cite | grounded | keywords | safe | done | s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        md.append("| {id} | {category} | {tool_selection} | {citation_accuracy} | "
                  "{grounded} | {keywords} | {action_safety} | {completed} | "
                  "{latency_s} |".format(**{k: r.get(k, "-") for k in
                  ("id", "category", "tool_selection", "citation_accuracy",
                   "grounded", "keywords", "action_safety", "completed", "latency_s")}))
    (ROOT / "evaluation" / out).write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nwrote evaluation/{out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", default="results.md")
    a = ap.parse_args()
    asyncio.run(main(a.limit, a.out))
