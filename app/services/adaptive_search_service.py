"""
Adaptive search service for iterative context retrieval.

This module handles iterative searching with result evaluation,
duplicate removal, and context combination.
"""

import logging
from typing import Dict, Any, List, Optional, Generator
from dataclasses import dataclass, asdict

from app.services.result_evaluation_service import get_result_evaluation_service
from app.services.context_provider_service import get_context_provider_service

# Configure logging
logger = logging.getLogger(__name__)

@dataclass
class AdaptiveSearchResult:
    """Result from adaptive search process."""
    success: bool
    total_iterations: int
    final_content: str
    all_results: List[str]
    evaluation_history: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

class AdaptiveSearchService:
    """Service for adaptive iterative search."""
    
    def __init__(self):
        """Initialize the adaptive search service."""
        logger.info("Initializing adaptive search service")
        self.evaluation_service = get_result_evaluation_service()
        self.context_service = get_context_provider_service()
        self.max_iterations = 3
        self.min_content_threshold = 500
    
    def execute_adaptive_search(self, original_query: str, user_session: str,
                              chat_context: Optional[Dict[str, Any]] = None) -> Generator[Dict[str, Any], None, None]:
        """
        Perform adaptive search with iterative refinement.
        
        Args:
            original_query: User's original question
            user_session: User session identifier
            chat_context: Optional chat context for query enhancement
            
        Yields:
            Streaming events for frontend, including final result as 'search_result' event
        """
        logger.info(f"Starting adaptive search for: {original_query}")
        
        # Check available resources
        resources = self.context_service.check_resources_exist(user_session)
        
        # Initialize tracking variables
        all_results = []
        evaluation_history = []
        current_query = original_query
        
        # Enhance initial query with chat context
        if chat_context and chat_context.get("context_used"):
            enhanced_query = self._enhance_query_with_context(original_query, chat_context)
            yield {
                'type': 'thinking_start',
                'content': f"Analyzing your question with conversation context..."
            }
        else:
            enhanced_query = original_query
            yield {
                'type': 'thinking_start',
                'content': f"Analyzing your question..."
            }
        
        # Initial search
        yield {
            'type': 'search_start',
            'content': {
                'query': enhanced_query,
                'iteration': 1,
                'search_type': 'initial'
            }
        }
        
        try:
            # Execute initial search
            initial_results = self._execute_search(enhanced_query, user_session, resources)
            all_results.extend(initial_results)
            
            yield {
                'type': 'search_complete',
                'content': {
                    'results_found': len(initial_results),
                    'iteration': 1
                }
            }
            
            # Evaluate initial results
            yield {
                'type': 'analyzing',
                'content': "Evaluating search results..."
            }
            
            evaluation = self.evaluation_service.evaluate_results(original_query, initial_results, 1)
            evaluation_history.append({
                'iteration': 1,
                'evaluation': evaluation.reasoning,
                'sufficient': evaluation.is_sufficient,
                'confidence': evaluation.confidence_score
            })
            
            # Iterative search if needed
            iteration = 1
            while (not evaluation.is_sufficient and 
                   iteration < self.max_iterations and 
                   evaluation.suggested_refinements):
                
                iteration += 1
                
                # Generate focused queries
                focused_queries = self.evaluation_service.generate_focused_queries(
                    original_query, all_results, evaluation.missing_aspects
                )
                
                if not focused_queries:
                    break
                
                # Execute focused search
                for i, focused_query in enumerate(focused_queries):
                    yield {
                        'type': 'search_start',
                        'content': {
                            'query': focused_query,
                            'iteration': iteration,
                            'search_type': 'focused'
                        }
                    }
                    
                    focused_results = self._execute_search(focused_query, user_session, resources)
                    all_results.extend(focused_results)
                    
                    yield {
                        'type': 'search_complete',
                        'content': {
                            'results_found': len(focused_results),
                            'iteration': iteration,
                            'query_index': i + 1
                        }
                    }
                
                # Re-evaluate with all results
                yield {
                    'type': 'analyzing',
                    'content': f"Re-evaluating with {len(all_results)} total results..."
                }
                
                evaluation = self.evaluation_service.evaluate_results(original_query, all_results, iteration)
                evaluation_history.append({
                    'iteration': iteration,
                    'evaluation': evaluation.reasoning,
                    'sufficient': evaluation.is_sufficient,
                    'confidence': evaluation.confidence_score
                })
                
                if evaluation.is_sufficient:
                    break
            
            # Deduplicate and combine results
            yield {
                'type': 'synthesis_start',
                'content': f"Combining and analyzing {len(all_results)} search results..."
            }
            
            final_content = self._deduplicate_and_combine_results(all_results)
            
            # Create final result
            final_result = AdaptiveSearchResult(
                success=len(all_results) > 0,
                total_iterations=iteration,
                final_content=final_content,
                all_results=all_results,
                evaluation_history=evaluation_history,
                metadata={
                    'original_query': original_query,
                    'enhanced_query': enhanced_query,
                    'final_evaluation': evaluation.reasoning,
                    'confidence_score': evaluation.confidence_score,
                    'resources_used': resources
                }
            )
            
            logger.info(f"Adaptive search completed: {iteration} iterations, "
                       f"{len(all_results)} results, sufficient={evaluation.is_sufficient}")
            
            # Yield the final result as a special event
            yield {
                'type': 'search_result',
                'content': final_result.to_dict()
            }
            
        except Exception as e:
            logger.error(f"Error in adaptive search: {e}")
            
            # Yield partial results if available
            error_result = AdaptiveSearchResult(
                success=False,
                total_iterations=iteration if 'iteration' in locals() else 1,
                final_content=self._deduplicate_and_combine_results(all_results) if all_results else "",
                all_results=all_results,
                evaluation_history=evaluation_history,
                metadata={
                    'error': str(e),
                    'original_query': original_query
                }
            )
            
            yield {
                'type': 'search_result', 
                'content': error_result.to_dict()
            }
    
    def _enhance_query_with_context(self, query: str, chat_context: Dict[str, Any]) -> str:
        """Enhance query with chat context information."""
        if not chat_context or not chat_context.get("context_used"):
            return query
        
        context_text = chat_context.get("context", "")
        if context_text:
            # Create a focused enhancement based on context type
            context_type = chat_context.get("context_type", "recent")
            
            if context_type == "reference":
                enhanced = f"{query} (considering previous discussion: {context_text[:200]}...)"
            elif context_type == "clarification":
                enhanced = f"{query} (clarification of: {context_text[:200]}...)"
            else:
                enhanced = f"{query} (context: {context_text[:200]}...)"
                
            return enhanced
        
        return query
    
    def _execute_search(self, query: str, user_session: str, 
                       resources: Dict[str, bool]) -> List[str]:
        """Execute search and return results as strings."""
        results = []
        
        try:
            # Search documents if available
            if resources.get('has_documents', False):
                doc_context = self.context_service.get_document_context(
                    user_session, query
                )
                if doc_context and doc_context.strip():
                    results.append(doc_context)
            
            # Search data if available
            if resources.get('has_data_tables', False):
                data_context = self.context_service.get_data_context(user_session, query)
                if data_context and data_context.strip():
                    results.append(data_context)
            
            # Search summaries if available and no other results
            if not results and resources.get('has_summaries', False):
                summary_context = self.context_service.get_summary_context(user_session, query)
                if summary_context and summary_context.strip():
                    results.append(summary_context)
            
        except Exception as e:
            logger.error(f"Error executing search for query '{query}': {e}")
        
        return results
    
    def _deduplicate_and_combine_results(self, results: List[str]) -> str:
        """Remove duplicates and combine results into single content."""
        if not results:
            return ""
        
        # Simple deduplication based on content similarity
        unique_results = []
        seen_fingerprints = set()
        
        for result in results:
            if not result or not result.strip():
                continue
                
            # Create a simple fingerprint
            fingerprint = self._create_content_fingerprint(result)
            
            if fingerprint not in seen_fingerprints:
                seen_fingerprints.add(fingerprint)
                unique_results.append(result)
        
        logger.info(f"Deduplication: {len(results)} -> {len(unique_results)} unique results")
        
        # Combine results with clear separation
        if len(unique_results) == 1:
            return unique_results[0]
        else:
            combined = ""
            for i, result in enumerate(unique_results, 1):
                combined += f"\n\n=== Source {i} ===\n{result}"
            return combined
    
    def _create_content_fingerprint(self, content: str, threshold: int = 100) -> str:
        """Create a simple fingerprint for content deduplication."""
        # Normalize content
        normalized = ' '.join(content.lower().split())
        
        # Use first and last parts as fingerprint
        if len(normalized) <= threshold:
            return normalized
        
        return normalized[:threshold//2] + "..." + normalized[-threshold//2:]


# Singleton instance
_adaptive_search_service = None

def get_adaptive_search_service() -> AdaptiveSearchService:
    """
    Get the adaptive search service singleton instance.
    
    Returns:
        AdaptiveSearchService: The adaptive search service instance
    """
    global _adaptive_search_service
    if _adaptive_search_service is None:
        _adaptive_search_service = AdaptiveSearchService()
    return _adaptive_search_service
