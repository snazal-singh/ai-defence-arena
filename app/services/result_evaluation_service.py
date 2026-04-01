"""
Result evaluation service for determining search result sufficiency.

This module evaluates whether retrieved search results contain enough information
to answer a user's question, and suggests follow-up searches if needed.
"""

import logging
from typing import List
from dataclasses import dataclass
import json

from app.services.llm_service import get_fast_llm

# Configure logging
logger = logging.getLogger(__name__)

@dataclass
class EvaluationResult:
    """Result of evaluating search results."""
    is_sufficient: bool
    confidence_score: float
    missing_aspects: List[str]
    reasoning: str
    suggested_refinements: List[str]

class ResultEvaluationService:
    """Service for evaluating search result sufficiency and suggesting improvements."""
    
    def __init__(self):
        """Initialize the result evaluation service."""
        logger.info("Initializing result evaluation service")
        self.llm = get_fast_llm()
        self.min_confidence_threshold = 0.7
        self.min_content_length = 200
    
    def evaluate_results(self, original_query: str, search_results: List[str],
                        iteration_count: int = 1) -> EvaluationResult:
        """
        Evaluate if search results are sufficient to answer the original query.
        
        Args:
            original_query: The user's original question
            search_results: List of search result content strings
            iteration_count: Current iteration number (affects threshold)
            
        Returns:
            EvaluationResult indicating sufficiency and suggestions
        """
        logger.info(f"Evaluating {len(search_results)} search results for query: {original_query}")
        
        # Quick checks first
        if not search_results:
            return EvaluationResult(
                is_sufficient=False,
                confidence_score=0.0,
                missing_aspects=["No search results found"],
                reasoning="No search results available",
                suggested_refinements=["Try broader search terms", "Check different information sources"]
            )
        
        # Check total content length
        total_content = " ".join(search_results)
        if len(total_content.strip()) < self.min_content_length:
            return EvaluationResult(
                is_sufficient=False,
                confidence_score=0.2,
                missing_aspects=["Insufficient content length"],
                reasoning="Search results contain too little information",
                suggested_refinements=["Search for more detailed information", "Try different keywords"]
            )
        
        # Use LLM for detailed evaluation
        try:
            evaluation = self._llm_evaluate_sufficiency(original_query, search_results)
            
            # Adjust threshold based on iteration count (be more lenient in later iterations)
            adjusted_threshold = max(0.5, self.min_confidence_threshold - (iteration_count - 1) * 0.1)
            evaluation.is_sufficient = evaluation.confidence_score >= adjusted_threshold
            
            logger.info(f"Evaluation result: sufficient={evaluation.is_sufficient}, "
                       f"confidence={evaluation.confidence_score}, iteration={iteration_count}")
            
            return evaluation
            
        except Exception as e:
            logger.error(f"Error in LLM evaluation: {e}")
            # Fallback evaluation
            return self._fallback_evaluation(original_query, search_results)
    
    def _llm_evaluate_sufficiency(self, query: str, results: List[str]) -> EvaluationResult:
        """Use LLM to evaluate result sufficiency."""
        
        # Prepare results summary for LLM
        results_summary = "\n\n".join([f"Result {i+1}:\n{result[:500]}..." 
                                     for i, result in enumerate(results[:3])])
        
        prompt = f"""Evaluate if the search results provide sufficient information to answer the user's question.

USER QUESTION: {query}

SEARCH RESULTS:
{results_summary}

EVALUATION CRITERIA:
1. Do the results directly address the main question?
2. Is there enough detail to provide a comprehensive answer?
3. Are there obvious gaps or missing information?
4. Could someone answer the question based on these results?

Respond with JSON only:
{{
    "is_sufficient": true/false,
    "confidence_score": 0.0-1.0,
    "missing_aspects": ["aspect1", "aspect2"],
    "reasoning": "brief explanation",
    "suggested_refinements": ["refinement1", "refinement2"]
}}"""

        try:
            response = self.llm.invoke(prompt)
            result_dict = json.loads(response.content.strip())
            
            return EvaluationResult(
                is_sufficient=result_dict.get("is_sufficient", False),
                confidence_score=float(result_dict.get("confidence_score", 0.5)),
                missing_aspects=result_dict.get("missing_aspects", []),
                reasoning=result_dict.get("reasoning", "LLM evaluation"),
                suggested_refinements=result_dict.get("suggested_refinements", [])
            )
            
        except Exception as e:
            logger.error(f"Error parsing LLM evaluation: {e}")
            raise
    
    def _fallback_evaluation(self, query: str, results: List[str]) -> EvaluationResult:
        """Fallback evaluation when LLM fails."""
        total_length = sum(len(result) for result in results)
        
        # Simple heuristic based on content length and keyword matching
        query_words = set(query.lower().split())
        results_text = " ".join(results).lower()
        matching_words = sum(1 for word in query_words if word in results_text)
        
        confidence = min(1.0, (total_length / 1000) * 0.3 + (matching_words / len(query_words)) * 0.7)
        
        return EvaluationResult(
            is_sufficient=confidence >= 0.6,
            confidence_score=confidence,
            missing_aspects=["Unable to determine specific gaps"],
            reasoning="Fallback evaluation based on content length and keyword matching",
            suggested_refinements=["Try more specific search terms", "Search for additional details"]
        )
    
    def generate_focused_queries(self, original_query: str, current_results: List[str],
                               missing_aspects: List[str]) -> List[str]:
        """
        Generate focused search queries based on evaluation results.
        
        Args:
            original_query: The original user question
            current_results: Current search results
            missing_aspects: Aspects that are missing from current results
            
        Returns:
            List of focused search queries
        """
        if not missing_aspects:
            return []
        
        try:
            prompt = f"""Based on the original question and what information is missing, generate 2-3 focused search queries.

ORIGINAL QUESTION: {original_query}

MISSING ASPECTS: {', '.join(missing_aspects)}

CURRENT RESULTS SUMMARY: {' '.join(current_results)[:300]}...

Generate focused search queries that would help find the missing information. 

Respond with JSON only:
{{
    "focused_queries": ["query1", "query2", "query3"]
}}"""

            response = self.llm.invoke(prompt)
            result_dict = json.loads(response.content.strip())
            
            queries = result_dict.get("focused_queries", [])
            logger.info(f"Generated {len(queries)} focused queries for missing aspects")
            
            return queries[:3]  # Limit to 3 queries
            
        except Exception as e:
            logger.error(f"Error generating focused queries: {e}")
            # Fallback: create simple variations of original query
            return [
                f"{original_query} details",
                f"{original_query} specific information",
                f"{original_query} examples"
            ][:2]


# Singleton instance
_result_evaluation_service = None

def get_result_evaluation_service() -> ResultEvaluationService:
    """Get the result evaluation service singleton instance."""
    global _result_evaluation_service
    if _result_evaluation_service is None:
        _result_evaluation_service = ResultEvaluationService()
    return _result_evaluation_service