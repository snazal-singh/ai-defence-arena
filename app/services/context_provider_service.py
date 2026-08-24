"""
Context provider service.

This module provides context for user queries from different sources:
- Document-based context from Elasticsearch
- Summary-based context from abstractive summaries
- SQL-based context from database tables
"""

import logging
import os
from typing import Dict, Any, List, Optional
import re
import glob

from elastic.retriever import ElasticRetriever
from elastic.reranker import get_reranker
from controllers.sql_db import query_database
from controllers.mongodb_db import has_mongo_data, query_mongodb
from controllers.doc_summary import get_summary_service
from utils.extractText import clean_filename
from app.core.config import settings

# Configure logging
logger = logging.getLogger(__name__)


class ContextProviderService:
    """Service for providing context from different sources with chat history support."""
    
    def __init__(self):
        """Initialize the context provider service."""
        logger.info("Initializing enhanced context provider service")
        self.summary_service = get_summary_service()
        
    def get_document_context(self, user_session: str, user_query: str,
                           chat_context: Optional[Dict[str, Any]] = None) -> str:
        """
        Get document context from Elasticsearch with optional chat context enhancement.

        When table chunks appear in the initial top-k results, all chunks for
        those tables are fetched via metadata filter (bypassing top-k) so the
        LLM always receives complete table data.

        Returns:
            Formatted context string for the LLM
        """
        try:
            enhanced_query = self._create_enhanced_search_query(user_query, chat_context)

            retriever = ElasticRetriever(user_session)
            candidate_k = settings.RERANKER_CANDIDATE_K if settings.ENABLE_RERANKER else None
            docs = retriever.search(enhanced_query, chat_context=chat_context,
                                     candidate_k=candidate_k)

            logger.info(f"Retrieved {len(docs) if docs else 0} documents for query: {user_query}")
            if chat_context and chat_context.get("context_used"):
                logger.info("Used chat context to enhance search query")

            if not docs:
                return ""

            # Re-score the fused candidates against the query directly (rank
            # fusion above only combines keyword/vector rank positions, it
            # never looks at content) and cut down to the chunks actually
            # worth keeping before the table augmentation/formatting below.
            reranker = get_reranker()
            if reranker:
                docs = reranker.rerank(enhanced_query, docs, top_n=settings.RERANKER_TOP_N)
                logger.info(f"Reranked to {len(docs)} documents")

            # Augment results with complete table content when tables are found
            docs = self._augment_with_full_tables(docs, retriever)

            try:
                extracted = self._extract_doc_info(docs)
                logger.info(f"Extracted {len(extracted)} documents")
                if not extracted:
                    return ""
            except Exception as e:
                logger.error(f"Error restructuring documents: {e}")
                return ""

            # Tables first so the LLM sees complete structured data before prose
            extracted.sort(key=lambda d: (0 if d.get("content_type") == "table" else 1))

            formatted_context = ""
            text_count = 0
            total_count = 0
            for chunk in extracted:
                is_table = chunk.get("content_type") == "table"
                if not is_table:
                    text_count += 1
                    if text_count > 5:
                        continue
                if total_count >= 15:
                    break
                total_count += 1
                try:
                    formatted_context += (
                        f"[{total_count}] \"{chunk['text']}\"  \n"
                        f"(Source: {chunk['source']}, Page {chunk['page']})\n\n"
                    )
                    logger.info(
                        f"Doc {total_count}: {chunk['text'][:20]}... "
                        f"from {chunk['source']} page {chunk['page']}"
                    )
                except Exception as e:
                    logger.error(f"Error formatting context: {e}")
                    continue

            return formatted_context
        except Exception as e:
            logger.error(f"Error retrieving document context: {e}")
            return ""

    def _augment_with_full_tables(self, docs: list, retriever) -> list:
        """If any doc is a table chunk, fetch ALL chunks for that table.

        This bypasses the top-k limit so the LLM always receives the complete
        table rather than a partial fragment.
        """
        table_ids: set = set()
        for doc in docs:
            meta = doc.metadata if hasattr(doc, "metadata") else {}
            # Handle the _source nesting that keyword retriever can produce
            if "_source" in meta:
                meta = meta["_source"].get("metadata", {})
            if meta.get("content_type") == "table" and meta.get("table_id"):
                table_ids.add(meta["table_id"])

        if not table_ids:
            return docs

        full_table_docs = retriever.get_full_table_chunks(list(table_ids))
        if not full_table_docs:
            return docs

        existing_contents = {d.page_content for d in docs}
        merged = list(docs)
        for td in full_table_docs:
            if td.page_content not in existing_contents:
                merged.append(td)
                existing_contents.add(td.page_content)

        logger.info(
            f"Full table retrieval: added {len(merged) - len(docs)} extra chunks "
            f"for {len(table_ids)} table(s)"
        )
        return merged
    
    def _create_enhanced_search_query(self, user_query: str, 
                                    chat_context: Optional[Dict[str, Any]] = None) -> str:
        """
        Create an enhanced search query that includes relevant chat context.
        
        Args:
            user_query: Original user query
            chat_context: Optional chat context
            
        Returns:
            Enhanced search query
        """
        if not chat_context or not chat_context.get("context_used"):
            return user_query
        
        try:
            # Extract key information from chat context
            context_text = chat_context.get("context", "")
            context_type = chat_context.get("context_type", "")
            
            if not context_text:
                return user_query
            
            # Simple but effective enhancement based on context type
            if context_type == "reference":
                # For reference context, add key entities/topics mentioned before
                enhanced_query = self._enhance_with_references(user_query, context_text)
            elif context_type == "clarification":
                # For clarification, include the topic being clarified
                enhanced_query = self._enhance_with_clarification_context(user_query, context_text)
            elif context_type == "continuation":
                # For continuation, include the ongoing topic
                enhanced_query = self._enhance_with_continuation_context(user_query, context_text)
            else:
                # Default enhancement - add key terms from recent context
                enhanced_query = self._enhance_with_recent_context(user_query, context_text)
            
            # Log the enhancement for debugging
            if enhanced_query != user_query:
                logger.info(f"Enhanced query: '{user_query}' -> '{enhanced_query}'")
            
            return enhanced_query
            
        except Exception as e:
            logger.error(f"Error enhancing search query: {e}")
            return user_query
    
    def _enhance_with_references(self, query: str, context: str) -> str:
        """Enhance query when user references previous discussion."""
        # Find capitalized words and important terms from context
        context_words = re.findall(r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b', context)
        
        # Also look for quoted terms or technical terms
        quoted_terms = re.findall(r'"([^"]+)"', context)
        context_words.extend(quoted_terms)
        
        # Take the most relevant terms (limit to avoid query bloat)
        relevant_terms = list(set(context_words))[:3]
        
        if relevant_terms:
            # Add terms to the query
            enhancement = " ".join(relevant_terms)
            return f"{query} {enhancement}"
        
        return query
    
    def _enhance_with_clarification_context(self, query: str, context: str) -> str:
        """Enhance query for clarification requests."""
        # For clarification, the last assistant response usually contains the topic
        # Extract the main topic from the assistant's previous response
        lines = context.split('\n')
        assistant_responses = [line for line in lines if line.startswith('Assistant:')]
        
        if assistant_responses:
            last_response = assistant_responses[-1].replace('Assistant:', '').strip()
            # Extract first few meaningful words
            words = last_response.split()[:10]  # First 10 words usually contain the topic
            topic_words = [w for w in words if len(w) > 3 and w.isalpha()][:3]
            
            if topic_words:
                enhancement = " ".join(topic_words)
                return f"{query} {enhancement}"
        
        return query
    
    def _enhance_with_continuation_context(self, query: str, context: str) -> str:
        """Enhance query for continuation of previous topic."""
        # Similar to references, but focus on the most recent context
        return self._enhance_with_recent_context(query, context)
    
    def _enhance_with_recent_context(self, query: str, context: str) -> str:
        """Default enhancement using recent context."""
        # Extract key terms from the last user-assistant exchange
        lines = context.split('\n')
        
        # Get the last few lines that contain substantive content
        recent_lines = [line.strip() for line in lines[-6:] if line.strip() and len(line.strip()) > 10]
        
        if recent_lines:
            # Combine recent context
            recent_text = " ".join(recent_lines)
            
            # Extract key terms (simple keyword extraction)
            words = re.findall(r'\b[a-zA-Z]{4,}\b', recent_text)  # Words with 4+ chars
            
            # Filter out common words and take top terms
            common_words = {'user', 'assistant', 'question', 'answer', 'this', 'that', 'with', 'from', 'what', 'when', 'where', 'how', 'they', 'them', 'have', 'been', 'will', 'would', 'could', 'should', 'about', 'other', 'some', 'more', 'also', 'can'}
            key_terms = [w for w in words if w.lower() not in common_words]
            
            # Get unique terms and limit
            unique_terms = list(set(key_terms))[:3]
            
            if unique_terms:
                enhancement = " ".join(unique_terms)
                return f"{query} {enhancement}"
        
        return query
            
    def get_data_context(self, user_session: str, user_query: str,
                        source: Optional[str] = None) -> str:
        """
        Get data context from structured databases (SQL and/or MongoDB).

        Args:
            user_session: User's session identifier
            user_query: User's query
            source: Which source(s) to query — "sql", "mongo", "both", or
                None (defaults to "both" for backward compatibility). Lets
                callers that already know which source a query needs (e.g.
                intent classification's data_source hint) skip querying the
                irrelevant one instead of always hitting both.

        Returns:
            Structured query results formatted as context
        """
        sql_doc = ""
        mongo_doc = ""
        source = source or "both"
        query_sql = source in ("sql", "both")
        query_mongo = source in ("mongo", "both")

        # 1. Fetch context from SQL Database if sheet metadata exists
        sheet_metadata_path = os.path.join('users', user_session, "files", "sheet_metadata.json")
        if query_sql and os.path.exists(sheet_metadata_path):
            try:
                logger.info(f"Querying SQL database for session: {user_session}")
                res, error = query_database(user_session, user_query)
                if error:
                    logger.error(f"SQL query error: {error}")
                elif res:
                    sql_doc = res
                    logger.info("SQL query results added to context")
            except Exception as e:
                logger.error(f"Error querying SQL: {e}")

        # 2. Fetch context from this session's own MongoDB data, if any was
        # uploaded. Gated the same way as SQL above — never queried for a
        # session that has no Mongo data of its own.
        if query_mongo and has_mongo_data(user_session):
            try:
                logger.info(f"Querying MongoDB database for session: {user_session}")
                res, error = query_mongodb(user_session, user_query)
                if error:
                    logger.error(f"MongoDB query error: {error}")
                elif res:
                    mongo_doc = res
                    logger.info("MongoDB query results added to context")
            except Exception as e:
                logger.error(f"Error querying MongoDB: {e}")

        # Combine SQL and MongoDB context results
        combined_doc = ""
        if sql_doc:
            combined_doc += sql_doc
        if mongo_doc:
            if combined_doc:
                combined_doc += "\n\n"
            combined_doc += mongo_doc

        return combined_doc

            
    def get_summary_context(self, user_session: str, user_query: str, 
                         language: Optional[str] = None, 
                         folder_names: Optional[List[str]] = None) -> str:
        """
        Get summary context from abstractive summaries.
        
        Args:
            user_session: User's session identifier
            user_query: User's query
            language: Language for the summary
            folder_names: List of folder names to include in the summary
            
        Returns:
            Abstractive summary
        """
        try:
            summary = self.summary_service.summarize_document(
                user_query, user_session, language, folder_names
            )
            return summary
        except Exception as e:
            logger.error(f'Error getting summary context: {e}')
            return f"I'm sorry, but I couldn't generate a summary at this time. Error: {str(e)}"
            
    def get_previous_question(self, user_session: str) -> str:
        """
        Get the previous question asked by the user.
        
        Args:
            user_session: User's session identifier
            
        Returns:
            Previous question or empty string
        """
        prev_question_filename = f'users/{user_session}/prev_question.txt'
        
        if os.path.exists(prev_question_filename):
            with open(prev_question_filename, 'r', encoding='utf-8') as file:
                prev_qn = str(file.read())
        else:
            prev_qn = ""
        
        return prev_qn
        
    def check_resources_exist(self, user_session: str) -> Dict[str, bool]:
        """
        Check which resources exist for the given user session.
        
        Args:
            user_session: User's session identifier
            
        Returns:
            Dictionary with resource availability flags
        """
        # Check whether this session's Elasticsearch index actually exists
        # and contains at least one document. Previously hardcoded True, which
        # caused the intent classifier to always assume documents exist even for
        # sessions that only have CSV/JSON data (no uploaded PDFs/DOCX).
        try:
            from elastic.client import ElasticClient
            es = ElasticClient()
            if es.index_exists(user_session):
                count_result = es.client.count(index=user_session)
                has_documents = count_result.get("count", 0) > 0
            else:
                has_documents = False
        except Exception as e:
            # If ES is unreachable, assume documents exist to avoid breaking
            # sessions that do have docs — failing open is safer than failing shut.
            logger.warning(f"Could not verify ES index for session {user_session}: {e}. Assuming has_documents=True.")
            has_documents = True

        # Check for summaries
        files_dir = os.path.join('users', user_session, 'files')
        summary_exists = False
        if os.path.exists(files_dir):
            for file_dir in glob.glob(os.path.join(files_dir, '*')):
                if os.path.exists(os.path.join(file_dir, 'imp_sents.txt')):
                    summary_exists = True
                    break
        elif os.path.exists(os.path.join('users', user_session, 'imp_sents.txt')):
            summary_exists = True
            
        # Check for database tables by looking for sheet_metadata.json
        sheet_metadata_path = os.path.join('users', user_session, "files", "sheet_metadata.json")
        has_sql_tables = os.path.exists(sheet_metadata_path)

        # Check for this session's own uploaded Mongo data (mirrors the SQL
        # check above — no global/shared dataset check anymore).
        has_mongo_tables = has_mongo_data(user_session)

        has_data_tables = has_sql_tables or has_mongo_tables
        
        return {
            "has_documents": has_documents,
            "has_data_tables": has_data_tables,
            "has_sql_tables": has_sql_tables,
            "has_mongo_tables": has_mongo_tables,
            "has_summaries": summary_exists
        }

    
    def _extract_doc_info(self, docs):
        """
        Extract and process information from search results.
        
        Args:
            docs: List of document objects from search results
            
        Returns:
            Processed list of document information
        """
        extracted = []
        
        try:
            # Set threshold score as median of first few documents
            threshold_score = (
                docs[1].metadata.get("_score") or 
                docs[1].metadata.get("_source", {}).get("_score") or 
                3
            )
        except Exception as e:  
            logger.warning(f'Error determining threshold score: {e}')
            threshold_score = 3
        
        for doc in docs:
            try:
                # Extract metadata
                meta = (
                    doc.metadata.get('_source', {}).get('metadata', {}) 
                    if '_source' in doc.metadata else doc.metadata
                )
                source = meta.get('source', '')
                filename = meta.get('filename', '')
                page = meta.get('page', 0)

                if isinstance(page, str):
                    try:
                        page = int(page)
                    except Exception as e:
                        page = 0
                
                # Add 1 to get 1-based page number
                page = page + 1
                
                if not filename and source:
                    filename = clean_filename(source)
                
                logger.debug(f'File name: {filename}, page number: {page}')
                
                extracted.append({
                    "text": doc.page_content,
                    "source": filename,
                    "page": page,
                    "content_type": meta.get("content_type", "text"),
                })
            except Exception as e:
                logger.warning(f"Failed to extract from doc: {e}")
        
        return extracted

# Create a singleton instance
_context_provider_service = None

def get_context_provider_service() -> ContextProviderService:
    """
    Get the context provider service singleton instance.
    
    Returns:
        ContextProviderService: The context provider service instance
    """
    global _context_provider_service
    if _context_provider_service is None:
        _context_provider_service = ContextProviderService()
    return _context_provider_service