import logging
import unicodedata
from typing import Dict, Any, List, Optional

from langchain.retrievers import EnsembleRetriever
from langchain.schema import Document
from langchain_elasticsearch.retrievers import ElasticsearchRetriever
from langchain_elasticsearch import ElasticsearchStore
from langchain_ollama import OllamaEmbeddings

from .client import ElasticClient
from .index_manager import ElasticIndexManager
from app.services.llm_service import get_fast_llm
from app.config import Config


class ElasticRetriever:
    def __init__(self, index_name: str):
        self.index_name = index_name
        self.client = ElasticClient().client
        self.index_manager = ElasticIndexManager()
        self.embeddings = OllamaEmbeddings(
            model="bge-m3:latest",
            base_url=Config.OLLAMA_BASE_URL,
        )
        # Stored during search() to pass chat_context through the body_func closure
        self._current_chat_context: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(self, query: str, k: int = 4,
               chat_context: Optional[Dict[str, Any]] = None) -> Optional[List[Document]]:
        """Hybrid keyword + vector search with optional chat-context enhancement."""
        try:
            self._current_chat_context = chat_context
            retriever = self._create_ensemble_retriever()
            if not retriever:
                return None
            results = retriever.invoke(query, k=k)
            return results
        except Exception as e:
            logging.error(f"Search error: {e}")
            raise
        finally:
            self._current_chat_context = None

    def get_full_table_chunks(self, table_ids: List[str]) -> List[Document]:
        """Fetch every chunk that belongs to the given table_ids.

        Used to bypass the top-k limit and retrieve complete table content
        when a table chunk appears in the initial search results.
        """
        if not table_ids:
            return []
        try:
            should_clauses = [{"term": {"metadata.table_id": tid}} for tid in table_ids]
            response = self.client.search(
                index=self.index_name,
                body={
                    "query": {
                        "bool": {
                            "should": should_clauses,
                            "minimum_should_match": 1,
                        }
                    },
                    "size": 200,
                },
            )
            hits = response.get("hits", {}).get("hits", [])
            docs = []
            for hit in hits:
                source = hit.get("_source", {})
                content = source.get("text", source.get("page_content", ""))
                metadata = source.get("metadata", {})
                docs.append(Document(page_content=content, metadata=metadata))
            logging.info(f"Full table fetch: {len(docs)} chunks for table_ids {table_ids}")
            return docs
        except Exception as e:
            logging.error(f"Error fetching full table chunks: {e}")
            return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _create_ensemble_retriever(self, weights=(0.4, 0.6)):
        try:
            if not self.index_manager.index_exists(self.index_name):
                return None

            key_retriever = ElasticsearchRetriever(
                es_client=self.client,
                index_name=self.index_name,
                body_func=self._create_filtered_query,
                content_field="text",
            )

            vector_store = ElasticsearchStore(
                es_url="http://localhost:9200",
                index_name=self.index_name,
                embedding=self.embeddings,
            )
            vector_retriever = vector_store.as_retriever()

            return EnsembleRetriever(
                retrievers=[key_retriever, vector_retriever],
                weights=list(weights),
            )
        except Exception as e:
            logging.error(f"Error creating retriever: {e}")
            raise

    def _create_filtered_query(self, query: str) -> Dict[str, Any]:
        """Build the keyword search body; uses chat context stored by search()."""
        normalized = unicodedata.normalize("NFC", query)
        enriched = self.query_enrichment(normalized, self._current_chat_context)

        should_clauses = [
            {"match": {"text": normalized}},
            {"match": {"text.hindi": normalized}},
        ]
        if enriched and enriched != normalized:
            should_clauses += [
                {"match": {"text": enriched}},
                {"match": {"text.hindi": enriched}},
            ]

        return {
            "query": {
                "bool": {
                    "should": should_clauses,
                    "minimum_should_match": 1,
                }
            },
            "_source": ["text", "metadata.source", "metadata.page",
                        "metadata.filename", "metadata.content_type",
                        "metadata.table_id"],
        }

    def query_enrichment(self, query: str,
                         chat_context: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Rewrite the query for better retrieval; single LLM call."""
        try:
            normalized = unicodedata.normalize("NFC", query)

            if chat_context and chat_context.get("context_used"):
                context_text = chat_context.get("context", "")[:500]
                context_type = chat_context.get("context_type", "unknown")
                prompt = (
                    f"Rewrite this query for better document retrieval considering the "
                    f"conversation context:\n\nCurrent query: {normalized}\n\n"
                    f"Conversation context ({context_type}):\n{context_text}\n\n"
                    "Instructions:\n"
                    "1. Enhance the query with relevant context from the conversation\n"
                    "2. Add missing implicit information that would help find relevant documents\n"
                    "3. Include synonyms and related terms\n"
                    "4. Fix spelling/grammar if needed\n"
                    "5. Maintain the original intent\n"
                    "6. If query is in Hindi, preserve the Hindi script\n"
                    "7. Keep the enhanced query concise and focused\n\n"
                    "Provide only the enhanced query, no explanations:"
                )
            else:
                prompt = (
                    f"Rewrite this query for better document retrieval:\n"
                    "1. Fix spelling/grammar\n"
                    "2. Expand acronyms\n"
                    "3. Add implicit context\n"
                    "4. Include synonyms\n"
                    "5. Maintain original intent\n"
                    "6. If query is in Hindi, preserve the Hindi script\n\n"
                    f"Original: {normalized}\n\n"
                    "Do not include any other text or explanations."
                )

            response = get_fast_llm().invoke(prompt).content
            if not response or response.strip() == normalized:
                return None

            enhanced = response.strip()
            logging.info(f"Query enriched: '{normalized}' -> '{enhanced}'")
            return enhanced

        except Exception as e:
            logging.error(f"Query enrichment error: {e}")
            return None
