"""
Cross-encoder reranker applied after hybrid (keyword + vector) retrieval.

EnsembleRetriever's rank fusion never looks at chunk content — it only
combines the keyword and vector branches' rank positions. This module scores
each (query, chunk) pair directly with a cross-encoder, so the chunks that
actually end up in the LLM's context are the ones most relevant to the
query, not just the ones that happened to rank well in either branch alone.
"""

import logging
import threading
from typing import List, Optional

from langchain.schema import Document

from app.core.config import settings

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    def __init__(self, model_name: str):
        # Imported lazily so environments with ENABLE_RERANKER=false never
        # need sentence-transformers installed.
        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(model_name)
        logger.info(f"Loaded cross-encoder reranker: {model_name}")

    def rerank(self, query: str, docs: List[Document],
               top_n: Optional[int] = None) -> List[Document]:
        if not docs:
            return docs

        pairs = [(query, doc.page_content) for doc in docs]
        scores = self.model.predict(pairs)

        ranked = [doc for doc, _ in sorted(
            zip(docs, scores), key=lambda pair: pair[1], reverse=True
        )]
        return ranked[:top_n] if top_n else ranked


_reranker_lock = threading.Lock()
_reranker_instance: Optional[CrossEncoderReranker] = None
_reranker_load_failed = False


def get_reranker() -> Optional[CrossEncoderReranker]:
    """Lazily load the singleton reranker (model load happens on first use).

    Returns None if reranking is disabled or the model failed to load, so
    callers can fall back to unreranked results instead of erroring out.
    """
    global _reranker_instance, _reranker_load_failed

    if not settings.ENABLE_RERANKER or _reranker_load_failed:
        return None

    if _reranker_instance is None:
        with _reranker_lock:
            if _reranker_instance is None and not _reranker_load_failed:
                try:
                    _reranker_instance = CrossEncoderReranker(settings.RERANKER_MODEL)
                except Exception as e:
                    logger.error(f"Failed to load reranker model '{settings.RERANKER_MODEL}': {e}")
                    _reranker_load_failed = True
                    return None

    return _reranker_instance
