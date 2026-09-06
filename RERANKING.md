# Reranking: What Was There Before, What Changed, How It Works

This document explains the reranking implementation added on branch `add-bge-reranker`, why it
was needed, and exactly how it fits into the existing retrieval pipeline.

---

## 1. What retrieval looked like before

`app/services/context_provider_service.py` (`get_document_context`) →
`elastic/retriever.py` (`ElasticRetriever.search`) ran **hybrid search** via LangChain's
`EnsembleRetriever`, combining two branches:

- **Keyword branch**: an Elasticsearch `bool`/`should` `match` query on `text` + `text.hindi`
  (`elastic/retriever.py`, `_create_filtered_query`). No `size` was set, so it defaulted to
  Elasticsearch's own default of **10** hits.
- **Vector branch**: `ElasticsearchStore.as_retriever()` using `bge-m3` embeddings (Ollama). No
  `search_kwargs` were passed, so it defaulted to LangChain's own default of **k=4**.

`EnsembleRetriever` merges the two ranked lists using **Reciprocal Rank Fusion (RRF)** — a fixed
formula (`score += weight / (rank + c)`) that combines *rank positions* from each branch. It never
looks at chunk content or scores relevance to the query directly.

**No reranking existed.** A repo-wide grep for `rerank`/`cross_encoder`/`cross-encoder` returned
nothing. Two look-alike scoring mechanisms exist elsewhere in the codebase
(`agentic_query_service.py`'s hardcoded keyword-boost heuristic, `search_execution_service.py`'s
`filter_and_rank_results`) but neither has any caller anywhere — both are dead code, never
executed in production.

**Also found and fixed as part of this change**: `ElasticRetriever.search(query, k=4)` passed
`k=` into `retriever.invoke(query, k=k)`, but `EnsembleRetriever._get_relevant_documents` doesn't
accept or forward that kwarg to its sub-retrievers — it was silently dropped. The real result
count was always governed by each branch's own default (10 keyword + 4 vector), regardless of
what `k` was passed.

---

## 2. Why add a reranker

RRF only knows *where* a chunk ranked in each branch, not *how relevant* it actually is to the
query. Two chunks that both landed at rank 3 in their respective branches get the same fusion
score even if one is obviously more relevant text. A cross-encoder reads the query and the chunk
**together** and scores relevance directly, which is strictly more informative than rank position
alone — the standard reason hybrid-search systems add a rerank stage after fusion.

---

## 3. Technique chosen: BGE cross-encoder (`bge-reranker-v2-m3`)

Options considered and why this one won:

| Option | Why not chosen |
|---|---|
| Cohere Rerank API | Sends document chunks to a third-party service over the network; requires an API key/cost per call; avoided for data residency and to stay consistent with this project's fully self-hosted stack. |
| LLM-based reranking (prompt the existing `qwen2.5:7b`) | No new dependency, but slower and more expensive per query than a dedicated cross-encoder, and generally lower-quality ranking. |
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | Fast and tiny, but English-tuned — this project has a `text.hindi` field and explicit Hindi query handling (`query_enrichment`), so an English-only reranker would degrade Hindi-language relevance scoring. |
| **`BAAI/bge-reranker-v2-m3`** (chosen) | Multilingual (covers Hindi), self-hosted (no external API/network egress, no new secrets), and from the same BGE model family as the `bge-m3` embeddings already used for vector search — consistent tooling choice. |

---

## 4. How it works now

```
user query
   │
   ▼
query_intent_service.classify_intent()        (unchanged — its own preliminary
                                                 ElasticRetriever.search() call for
                                                 evidence is untouched)
   │
   ▼
context_provider_service.get_document_context()
   │
   ├─ 1. _create_enhanced_search_query()        (unchanged — chat-context query enhancement)
   │
   ├─ 2. ElasticRetriever.search(
   │        enhanced_query,
   │        candidate_k=RERANKER_CANDIDATE_K=20   ← NEW: widens candidate pool
   │    )
   │        → keyword branch: ES query body now sets "size": 20   (was: unset → ES default 10)
   │        → vector branch:  as_retriever(search_kwargs={"k": 20}) (was: unset → default 4)
   │        → EnsembleRetriever fuses both branches via RRF, as before
   │        ≈ up to 40 candidates before dedup
   │
   ├─ 3. get_reranker().rerank(enhanced_query, docs, top_n=RERANKER_TOP_N=15)  ← NEW
   │        → CrossEncoder(BAAI/bge-reranker-v2-m3).predict([(query, chunk.page_content), ...])
   │        → sort descending by score, keep top 15
   │
   ├─ 4. _augment_with_full_tables()             (unchanged — fetches complete table content
   │                                                for any table chunk that survived reranking)
   │
   └─ 5. _extract_doc_info() + tables-first sort + format
            → same existing cap: max 5 non-table chunks, 15 total chunks in the final
              LLM-facing context block
```

The final 5-text/15-total cap on what's sent to the LLM is **unchanged**. What changed is *which*
15 chunks make it there — previously "whichever fused highest by RRF rank," now "whichever the
cross-encoder scores highest against the actual query text."

If the reranker fails to load (e.g. model download issue) or is disabled, `get_reranker()`
returns `None` and `get_document_context` falls back to the pre-rerank behavior unchanged — the
call site only reranks `if reranker:`, so this is a safe no-op failure mode, not a hard error.

---

## 5. Files changed

| File | Change |
|---|---|
| `elastic/reranker.py` (new) | `CrossEncoderReranker` class wrapping `sentence_transformers.CrossEncoder`; lazy-loaded singleton via `get_reranker()`, returns `None` on disable/failure. |
| `elastic/retriever.py` | Added `candidate_k` param to `search()` / `_create_ensemble_retriever()`, threaded into both branches' query bodies so the reranker gets a real candidate pool instead of an already-tiny top-k. |
| `app/services/context_provider_service.py` | `get_document_context` now requests a wider candidate pool when reranking is enabled, calls `reranker.rerank(...)` after retrieval and before table augmentation/formatting. |
| `app/core/config.py` | New settings: `ENABLE_RERANKER` (default `True`), `RERANKER_MODEL` (`BAAI/bge-reranker-v2-m3`), `RERANKER_CANDIDATE_K` (`20`), `RERANKER_TOP_N` (`15`). |
| `requirements.txt` | Added `sentence-transformers`. |

---

## 6. Config knobs

Set any of these in `.env` to override defaults:

- `ENABLE_RERANKER=false` — turn reranking off entirely, revert to raw RRF-fused order (with the
  `k=` bugfix in `retriever.py` still in effect, so branch sizes stay at their library defaults
  when this is off, matching original behavior).
- `RERANKER_MODEL=...` — swap the cross-encoder model.
- `RERANKER_CANDIDATE_K=...` — how many candidates each retrieval branch returns pre-rerank.
- `RERANKER_TOP_N=...` — how many chunks survive reranking before table augmentation/formatting.

---

## 7. Known limitations / not addressed here

- The reranker model loads synchronously on first request after process start (not at startup),
  so the very first document query after a deploy will be slower while the ~600MB model loads and
  caches in memory. Not addressed in this change — could be moved to an app-startup hook if this
  cold-start latency matters in practice.
- `get_full_table_chunks` (used by `_augment_with_full_tables`, called after reranking) still
  assumes a table can span multiple chunks sharing one `table_id` — in the current ingestion code
  (`controllers/upload.py`) a table is always exactly one chunk regardless of size, so this fetch
  is effectively a no-op today. Pre-existing behavior, left unchanged in this PR (out of scope for
  reranking).
