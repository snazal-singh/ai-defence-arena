"""
Compare document retrieval — latency and returned context — with the
cross-encoder reranker OFF (old behavior) vs ON (current behavior).

Runs the exact same `ContextProviderService.get_document_context()` call
used in the live query pipeline, toggling `settings.ENABLE_RERANKER`
in-process between runs, so this measures the real code path rather than a
synthetic approximation of it.

Usage:
    python compare_reranker.py <user_session> "query one" "query two" ...
    python compare_reranker.py <user_session> --queries-file queries.txt

Requires the same environment as the running app: reachable Elasticsearch
(ES_BASE_URL), Ollama (OLLAMA_BASE_URL, for embeddings + query enrichment),
and an index that already has documents for <user_session>.

Writes a full JSON report (queries, latencies, contexts) to --out
(default: reranker_comparison.json) and prints a latency summary to stdout.
"""

import argparse
import json
import time
from statistics import mean

from app.core.config import settings
from app.services.context_provider_service import get_context_provider_service
from elastic import reranker as reranker_module


def _run_once(provider, session: str, query: str, enable_reranker: bool):
    settings.ENABLE_RERANKER = enable_reranker
    start = time.perf_counter()
    context = provider.get_document_context(session, query)
    elapsed = time.perf_counter() - start
    chunk_count = context.count('"  \n(Source:') if context else 0
    return elapsed, chunk_count, context


def _warm_up_reranker():
    """Load the cross-encoder model once before timing so the first 'ON'
    run isn't skewed by one-time model-download/load latency."""
    settings.ENABLE_RERANKER = True
    if reranker_module.get_reranker() is None:
        print("WARNING: reranker failed to load — 'ON' runs will silently "
              "fall back to no-rerank behavior. Check logs above.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", help="user_session / index name to query against")
    parser.add_argument("queries", nargs="*", help="queries to test")
    parser.add_argument("--queries-file", help="text file, one query per line")
    parser.add_argument("--out", default="reranker_comparison.json")
    args = parser.parse_args()

    queries = list(args.queries)
    if args.queries_file:
        with open(args.queries_file, encoding="utf-8") as f:
            queries += [line.strip() for line in f if line.strip()]

    if not queries:
        parser.error("provide at least one query, or --queries-file")

    _warm_up_reranker()
    provider = get_context_provider_service()

    results = []
    for q in queries:
        before_time, before_n, before_ctx = _run_once(provider, args.session, q, enable_reranker=False)
        after_time, after_n, after_ctx = _run_once(provider, args.session, q, enable_reranker=True)

        results.append({
            "query": q,
            "latency_before_sec": round(before_time, 3),
            "latency_after_sec": round(after_time, 3),
            "latency_delta_sec": round(after_time - before_time, 3),
            "chunk_count_before": before_n,
            "chunk_count_after": after_n,
            "context_before": before_ctx,
            "context_after": after_ctx,
            "context_changed": before_ctx != after_ctx,
        })
        print(
            f"{q!r}\n"
            f"  latency:  before={before_time:.3f}s  after={after_time:.3f}s  "
            f"delta={after_time - before_time:+.3f}s\n"
            f"  chunks:   before={before_n}  after={after_n}  "
            f"changed={'yes' if before_ctx != after_ctx else 'no'}\n"
        )

    avg_before = mean(r["latency_before_sec"] for r in results)
    avg_after = mean(r["latency_after_sec"] for r in results)
    changed_count = sum(1 for r in results if r["context_changed"])

    print("=" * 60)
    print(f"Queries run:            {len(results)}")
    print(f"Avg latency before:     {avg_before:.3f}s")
    print(f"Avg latency after:      {avg_after:.3f}s")
    print(f"Avg latency delta:      {avg_after - avg_before:+.3f}s")
    print(f"Context changed on:     {changed_count}/{len(results)} queries")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({
            "results": results,
            "avg_latency_before_sec": round(avg_before, 3),
            "avg_latency_after_sec": round(avg_after, 3),
            "avg_latency_delta_sec": round(avg_after - avg_before, 3),
            "context_changed_count": changed_count,
            "total_queries": len(results),
        }, f, indent=2, ensure_ascii=False)
    print(f"\nFull report written to {args.out}")


if __name__ == "__main__":
    main()
