"""
Creative reasoning service with adaptive search implementation.

This module implements the new adaptive search approach:
1. Direct search with original + enhanced query
2. Evaluate results sufficiency
3. Iterative focused searches if needed
4. Final synthesis with streaming support
"""

import logging
import time
from typing import Dict, Any, Optional, Generator
import json
import traceback

from app.services.adaptive_search_service import get_adaptive_search_service, AdaptiveSearchResult
from app.services.result_synthesis_service import get_result_synthesis_service
from app.services.context_provider_service import get_context_provider_service
from app.services.llm_service import get_standard_llm
from utils.language_codes import ISO_TO_NAME

# Configure logging
logger = logging.getLogger(__name__)

class CreativeReasoningService:
    """Main service for creative mode query processing with adaptive search."""
    
    def __init__(self):
        """Initialize the creative reasoning service."""
        logger.info("Initializing creative reasoning service with adaptive search")
        self.adaptive_search_service = get_adaptive_search_service()
        self.synthesis_service = get_result_synthesis_service()
        self.context_service = get_context_provider_service()
        self.llm = get_standard_llm()
        
        # Configuration
        self.max_processing_time = 120  # seconds
    
    def process_creative_query_stream(self, user_query: str, user_session: str,
                                    input_language: int = 23, output_language: int = 23,
                                    filenames: Optional[list] = None, has_csvxl: bool = False,
                                    chat_context: Optional[Dict[str, Any]] = None,
                                    chat_id: str = None) -> Generator[Dict[str, Any], None, None]:
        """
        Process a query using creative reasoning mode with adaptive search and streaming.
        
        Yields events for each step of the process.
        """
        start_time = time.time()
        logger.info(f"Processing creative query with adaptive search: {user_query} (chat: {chat_id})")
        
        try:
            # Check available resources
            available_resources = self.context_service.check_resources_exist(user_session)
            available_resources['has_data_tables'] = has_csvxl or available_resources.get('has_data_tables', False)
            
            if not any(available_resources.values()):
                yield {
                    'type': 'error',
                    'content': 'No documents or data available for analysis'
                }
                return
            
            # Execute adaptive search with streaming
            search_result = None
            for event in self.adaptive_search_service.execute_adaptive_search(
                user_query, user_session, chat_context
            ):
                # Check if this is the final search result
                if event.get('type') == 'search_result':
                    search_result_dict = event.get('content', {})
                    search_result = AdaptiveSearchResult(
                        success=search_result_dict.get('success', False),
                        total_iterations=search_result_dict.get('total_iterations', 1),
                        final_content=search_result_dict.get('final_content', ''),
                        all_results=search_result_dict.get('all_results', []),
                        evaluation_history=search_result_dict.get('evaluation_history', []),
                        metadata=search_result_dict.get('metadata', {})
                    )
                else:
                    # Yield regular streaming events
                    yield self._ensure_json_serializable(event)
            
            # If we didn't get the search result through iteration, it means there was an error
            if search_result is None:
                logger.error("No search result received from adaptive search")
                yield {
                    'type': 'error',
                    'content': 'Search execution failed - no results received'
                }
                return
            
            # Check if we have any content to work with
            if not search_result.success or not search_result.final_content.strip():
                logger.warning(f"Search result unsuccessful or empty content. Success: {search_result.success}, Content length: {len(search_result.final_content) if search_result.final_content else 0}")
                yield {
                    'type': 'complete',
                    'content': {
                        'answer': "I couldn't find relevant information to answer your question. Please try rephrasing or check if your documents contain the information you're looking for.",
                        'questions': []
                    }
                }
                return
            
            # Generate final answer using synthesis service
            yield {
                'type': 'synthesis_start',
                'content': 'Creating comprehensive answer...'
            }
            
            # Get language name
            language_name = self._get_language_name(output_language)
            
            logger.info(f"Starting synthesis for {len(search_result.final_content)} characters of content")
            
            # Create a simple synthesis (no complex strategy needed for adaptive approach)
            try:
                synthesis_response = self._synthesize_adaptive_results(
                    search_result, user_query, language_name
                )
                logger.info(f"Synthesis completed, response length: {len(synthesis_response)}")
                
                # Parse JSON response like simple mode
                final_answer, questions = self._parse_synthesis_response(synthesis_response)
                logger.info(f"Parsed answer length: {len(final_answer)}, questions: {len(questions)}")
                
            except Exception as e:
                logger.error(f"Error in synthesis: {e}")
                yield {
                    'type': 'error',
                    'content': f'Error creating answer: {str(e)}'
                }
                return
            
            # Stream the final answer
            yield {
                'type': 'answer_chunk',
                'content': final_answer
            }

            # Stream questions if any from synthesis
            if questions:

                yield {
                    'type': 'questions',
                    'content': questions
                }
                logger.info(f"Streamed {len(questions)} questions from synthesis")
            # Generate follow-up questions if none were provided
            else:
                try:
                    questions = self._generate_follow_up_questions(search_result, user_query)
                    logger.info(f"Generated {len(questions)} follow-up questions")
                except Exception as e:
                    logger.error(f"Error generating follow-up questions: {e}")
                    questions = []
                yield {
                    'type': 'questions',
                    'content': questions
                }
            
            # Final completion
            processing_time = time.time() - start_time
            yield {
                'type': 'complete',
                'content': {
                    'processing_time': processing_time,
                    'total_iterations': search_result.total_iterations,
                    'confidence_score': search_result.metadata.get('confidence_score', 0.8),
                    'chat_id': chat_id
                }
            }
            
        except Exception as e:
            logger.error(f"Error in streaming creative query: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")
            yield {
                'type': 'error',
                'content': f'Processing error: {str(e)}'
            }

    def process_creative_query(self, user_query: str,
                             user_session: str,
                             available_resources: Dict[str, bool],
                             input_language: int = 23,
                             output_language: int = 23,
                             filenames: Optional[list] = None,
                             chat_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Process a query using creative reasoning mode (non-streaming version).
        
        Args:
            user_query: The user's question
            user_session: User's session identifier
            available_resources: Dict indicating what resources are available
            input_language: Input language code
            output_language: Output language code
            filenames: Optional list of specific filenames to focus on
            chat_context: Optional chat context for query enhancement
            
        Returns:
            Enhanced response with reasoning steps
        """
        start_time = time.time()
        chat_id = chat_context.get('chat_id') if chat_context else None
        logger.info(f"Processing creative query (non-streaming): {user_query} (chat: {chat_id})")
        
        try:
            # Execute adaptive search (non-streaming)
            search_events = []
            search_result = None
            
            for event in self.adaptive_search_service.execute_adaptive_search(
                user_query, user_session, chat_context
            ):
                if event.get('type') == 'search_result':
                    search_result_dict = event.get('content', {})
                    search_result = AdaptiveSearchResult(
                        success=search_result_dict.get('success', False),
                        total_iterations=search_result_dict.get('total_iterations', 1),
                        final_content=search_result_dict.get('final_content', ''),
                        all_results=search_result_dict.get('all_results', []),
                        evaluation_history=search_result_dict.get('evaluation_history', []),
                        metadata=search_result_dict.get('metadata', {})
                    )
                else:
                    search_events.append(event)
            
            if not search_result or not search_result.success:
                return self._create_fallback_response(user_query, output_language)
            
            # Synthesize results
            language_name = self._get_language_name(output_language)
            synthesis_response = self._synthesize_adaptive_results(search_result, user_query, language_name)
            
            # Parse JSON response
            final_answer, questions_from_synthesis = self._parse_synthesis_response(synthesis_response)
            
            # Generate follow-up questions if not provided
            if not questions_from_synthesis:
                questions = self._generate_follow_up_questions(search_result, user_query)
            else:
                questions = questions_from_synthesis
            
            processing_time = time.time() - start_time
            
            # Format as legacy response for compatibility
            return {
                "answer": final_answer,
                "questions": questions,
                "creative_reasoning": {
                    "strategy_used": "adaptive_search",
                    "reasoning_steps": [
                        f"Iteration {eval['iteration']}: {eval['evaluation']}" 
                        for eval in search_result.evaluation_history
                    ],
                    "confidence_level": search_result.metadata.get('confidence_score', 0.8),
                    "total_iterations": search_result.total_iterations,
                    "search_approach": "direct_then_iterative",
                    "chat_id": chat_id
                },
                "processing_metadata": {
                    "processing_time": processing_time,
                    "total_iterations": search_result.total_iterations,
                    "final_evaluation": search_result.metadata.get('final_evaluation', 'completed'),
                    "chat_id": chat_id
                }
            }
            
        except Exception as e:
            logger.error(f"Error in creative query processing: {e}")
            processing_time = time.time() - start_time
            return self._create_error_response(user_query, str(e), processing_time, output_language, chat_id)
    
    def _ensure_json_serializable(self, event: Any) -> Dict[str, Any]:
        """Ensure event is JSON serializable."""
        if hasattr(event, 'to_dict'):
            return event.to_dict()
        elif isinstance(event, dict):
            return event
        else:
            # Convert to string if not serializable
            return {'type': 'unknown', 'content': str(event)}
    
    def _parse_synthesis_response(self, response_content: str) -> tuple:
        """Parse JSON response from synthesis LLM."""
        try:
            # Clean up the response
            cleaned_response = response_content.strip()
            
            # Remove any markdown code block markers
            if '```json' in cleaned_response:
                start = cleaned_response.find('```json') + 7
                end = cleaned_response.rfind('```')
                if end > start:
                    cleaned_response = cleaned_response[start:end].strip()
            elif '```' in cleaned_response:
                cleaned_response = cleaned_response.replace('```', '').strip()
            
            # Find the first { and last } to extract just the JSON
            first_brace = cleaned_response.find('{')
            last_brace = cleaned_response.rfind('}')
            if first_brace >= 0 and last_brace > first_brace:
                cleaned_response = cleaned_response[first_brace:last_brace + 1]

            logger.info(f'cleaned response for parsing: {cleaned_response}')
            
            # Parse JSON
            parsed = json.loads(cleaned_response, strict=False)
            
            answer = parsed.get('answer', '')
            questions = parsed.get('relevant_questions', [])
            
            return answer, questions
            
        except Exception as e:
            logger.error(f"Failed to parse synthesis JSON: {e}")
            # Fallback to treating as plain text
            return response_content, []

    def _synthesize_adaptive_results(self, search_result, user_query: str, language: str) -> str:
        """Synthesize results from adaptive search into final answer."""
        try:            
            logger.info(f"Synthesizing results with {len(search_result.final_content)} characters of content")
            
            # Create synthesis prompt using same format as simple mode
            prompt = f"""You are a document analysis assistant that provides accurate, well-cited responses based on provided document excerpts.

Return response ONLY as valid JSON with this structure:
{{
"answer": "Full answer text with inline citations [filename.pdf, Page X]",
"relevant_questions": ["question1?", ...]
}}

CITATION INSTRUCTIONS:
**CRITICAL**: You must cite sources inline throughout your answer. For every statement, fact, or piece of information you include:

1. **Immediate Citation**: Add a citation immediately after each sentence or logical sequence that comes from the document context
2. **Citation Format**: Use this exact format: [filename.pdf, Page X] 
3. **Accuracy**: Only cite sources that are explicitly provided in the context below
4. **No Hallucination**: Do not make up sources, page numbers, or filenames that are not in the provided context
5. **Complete Coverage**: Every factual statement in your answer should have a corresponding citation

CONTEXT:
{search_result.final_content}

USER QUESTION: 
{user_query}

ANSWER FORMATTING GUIDELINES
Analyze the user's question and determine the appropriate response style.

Format for detailed responses:
- **Create numbered or bulleted lists** for multiple items
- **Provide thorough explanations** for each point
- **Organize information logically** with smooth flow and readability
- **Include all relevant details** from the context

Examples:
```
Types of Life Insurance Policies
1. **Term Life Insurance** [source.pdf, Page 5]
- **Definition**: Provides coverage for a specific period...
- **Benefits**: Lower premiums, flexibility...
- **Limitations**: No cash value, temporary coverage...
2. **Whole Life Insurance** [source.pdf, Page 6]
- **Definition**: Permanent coverage with cash value...
- **Benefits**: Guaranteed death benefit, cash accumulation...
```
Generate ONLY the JSON response. Do not include any other text or explanations.
Include ALL relevant details from the sources - do not summarize or truncate
{"Answer in " + language if language != 'English' else "Answer in English"}."""

            logger.debug(f"Synthesis prompt length: {len(prompt)} characters")
            response = self.llm.invoke(prompt)
            result = response.content.strip()
            logger.info(f"LLM synthesis completed, result length: {len(result)}")
            return result
            
        except Exception as e:
            logger.error(f"Error in synthesis: {e}")
            # Fallback to simple content return
            fallback = f"Based on the available information:\n\n{search_result.final_content[:2000]}..."
            logger.info(f"Using fallback synthesis, length: {len(fallback)}")
            return fallback
    
    def _generate_follow_up_questions(self, search_result, user_query: str) -> list:
        """Generate relevant follow-up questions."""
        try:            
            prompt = f"""Based on the user's question and the search results found, generate 2-3 relevant follow-up questions.

ORIGINAL QUESTION: {user_query}

SEARCH SUMMARY: Found information across {search_result.total_iterations} iterations with confidence {search_result.metadata.get('confidence_score', 'moderate')}.

Generate follow-up questions that:
1. Can be answered with the available information
2. Explore related aspects of the topic
3. Help the user understand the topic better

Respond with JSON:
{{"questions": ["question1?", "question2?", "question3?"]}}"""

            response = self.llm.invoke(prompt)
            cleaned_response = response.content.strip()
            # Remove any markdown code block markers
            if '```json' in cleaned_response:
                start = cleaned_response.find('```json') + 7
                end = cleaned_response.rfind('```')
                if end > start:
                    cleaned_response = cleaned_response[start:end].strip()
            elif '```' in cleaned_response:
                cleaned_response = cleaned_response.replace('```', '').strip()
            
            # Find the first { and last } to extract just the JSON
            first_brace = cleaned_response.find('{')
            last_brace = cleaned_response.rfind('}')
            if first_brace >= 0 and last_brace > first_brace:
                cleaned_response = cleaned_response[first_brace:last_brace + 1]
            
            logger.info(f'cleaned response for questions parsing: {cleaned_response}')
            result = json.loads(cleaned_response, strict=False)
            return result.get('questions', [])
            
        except Exception as e:
            logger.error(f"Error generating follow-up questions: {e}")
            return [
                "Elaborate on the main findings.",
                "Provide more details on specific aspects.",
                "Search for additional information related to this topic."
            ]
    
    def _create_fallback_response(self, user_query: str, output_language: int) -> Dict[str, Any]:
        """Create a fallback response when search fails."""
        language_name = self._get_language_name(output_language)
        
        fallback_message = (
            "I was unable to find sufficient information to answer your question. "
            "This might be because the information isn't available in your uploaded files, "
            "or the question might need to be rephrased to better match the available content."
        )
        
        if language_name != 'English':
            fallback_message = f"[Response in {language_name}] {fallback_message}"
        
        return {
            "answer": fallback_message,
            "questions": [
                "Could you try rephrasing your question?",
                "Do you have additional documents that might contain this information?"
            ],
            "creative_reasoning": {
                "strategy_used": "fallback",
                "reasoning_steps": ["Search execution failed", "Providing fallback response"],
                "confidence_level": "low"
            }
        }
    
    def _create_error_response(self, user_query: str, error_message: str,
                             processing_time: float, output_language: int, chat_id: str = None) -> Dict[str, Any]:
        """Create an error response."""
        language_name = self._get_language_name(output_language)
        
        error_response = (
            "I encountered an error while processing your question using creative reasoning. "
            "Please try again or use the standard mode for this query."
        )
        
        if language_name != 'English':
            error_response = f"[Response in {language_name}] {error_response}"
        
        return {
            "answer": error_response,
            "questions": [],
            "creative_reasoning": {
                "strategy_used": "error_handling",
                "reasoning_steps": ["Error occurred during processing"],
                "confidence_level": "low",
                "error_details": error_message,
                "chat_id": chat_id
            },
            "processing_metadata": {
                "processing_time": processing_time,
                "status": "error",
                "chat_id": chat_id
            }
        }
    
    def _get_language_name(self, language_code: str) -> str:
        """Get the language name from its ISO 639-1 code."""
        return ISO_TO_NAME.get(str(language_code), "English")
    
    def should_use_creative_mode(self, mode: str, query_complexity: Optional[str] = None) -> bool:
        """Determine if creative mode should be used."""
        return mode == 'creative'
    
    def get_creative_mode_info(self) -> Dict[str, Any]:
        """Get information about creative mode capabilities."""
        return {
            "name": "Creative Reasoning Mode",
            "description": "Adaptive search with iterative information gathering",
            "features": [
                "Initial direct search with context enhancement",
                "Intelligent result evaluation and sufficiency checking",
                "Iterative focused searches for missing information", 
                "Automatic deduplication and result combination",
                "Real-time streaming of search progress"
            ],
            "best_for": [
                "Complex questions requiring comprehensive information",
                "Research queries needing multiple information sources",
                "Questions where initial search may be insufficient",
                "Exploratory analysis with adaptive depth"
            ],
            "processing_time": "10-120 seconds depending on complexity",
            "max_iterations": 3,
            "search_approach": "adaptive_iterative"
        }


# Create a singleton instance
_creative_reasoning_service = None

def get_creative_reasoning_service() -> CreativeReasoningService:
    """Get the creative reasoning service singleton instance."""
    global _creative_reasoning_service
    if _creative_reasoning_service is None:
        _creative_reasoning_service = CreativeReasoningService()
    return _creative_reasoning_service