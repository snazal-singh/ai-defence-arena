"""
Result synthesis service for combining multiple search results into coherent answers.

This module handles the synthesis of search results from multiple sources,
applying reasoning and creating comprehensive responses.
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
import time

from app.services.search_execution_service import SearchResult
from app.services.reasoning_strategy_service import SearchStrategy
from app.services.llm_service import get_comprehensive_llm, get_streaming_llm, LLMType
from langchain.callbacks.base import BaseCallbackHandler

# Configure logging
logger = logging.getLogger(__name__)

@dataclass
class SynthesisResult:
    """Result of the synthesis process."""
    answer: str
    reasoning_steps: List[str]
    confidence_level: str
    follow_up_questions: List[str]
    synthesis_metadata: Dict[str, Any]
    answer_completeness: Optional[str] = None

class ResultSynthesisService:
    """Service for synthesizing multiple search results into coherent answers."""
    
    def __init__(self):
        """Initialize the result synthesis service."""
        logger.info("Initializing result synthesis service")
        self.llm = get_comprehensive_llm()
        self.max_sources_in_response = 10
    
    def synthesize_results(self, search_results: List[SearchResult],
                          original_query: str,
                          strategy: SearchStrategy,
                          language: Optional[str] = None) -> SynthesisResult:
        """
        Synthesize multiple search results into a comprehensive answer.
        
        Args:
            search_results: List of search results from execution
            original_query: The original user query
            strategy: The search strategy that was used
            language: Preferred response language
            
        Returns:
            SynthesisResult with comprehensive answer and metadata
        """
        logger.info(f"Synthesizing {len(search_results)} search results")
        
        # Filter and prepare results
        successful_results = [r for r in search_results if r.success and r.content.strip()]
        
        if not successful_results:
            return self._create_no_results_response(original_query, language)
        
        # Create synthesis prompt
        synthesis_prompt = self._create_synthesis_prompt(
            successful_results, original_query, strategy, language
        )
        
        # Try synthesis with retry logic
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                # Generate synthesis
                logger.info(f"Synthesis attempt {attempt + 1}, prompt length: {len(synthesis_prompt)} characters")
                response = self.llm.invoke(synthesis_prompt)
                
                # Log raw response for debugging
                logger.debug(f"Raw LLM response (first 1000 chars): {response.content[:1000]}")
                
                synthesis_response = self._parse_synthesis_response(response.content)
                
                # Validate the response has actual content
                if not synthesis_response.get('answer') or synthesis_response['answer'] == self._get_default_value('answer'):
                    raise ValueError("Empty or default answer received")
                
                logger.info(f"Successfully parsed synthesis response on attempt {attempt + 1}")
                
                # Create final result
                return SynthesisResult(
                    answer=synthesis_response.get('answer', ''),
                    reasoning_steps=synthesis_response.get('reasoning_steps', []),
                    confidence_level=synthesis_response.get('confidence_level', 'medium'),
                    follow_up_questions=synthesis_response.get('follow_up_questions', []),
                    synthesis_metadata={
                        'total_sources': len(successful_results),
                        'strategy_used': strategy.reasoning,
                        'synthesis_approach': strategy.synthesis_approach,
                        'synthesis_attempts': attempt + 1
                    },
                    answer_completeness=synthesis_response.get('answer_completeness', 'fully answered')
                )
                
            except Exception as e:
                logger.error(f"Error during synthesis attempt {attempt + 1}: {e}")
                if attempt == max_retries:
                    logger.error("All synthesis attempts failed, using fallback")
                    return self._create_fallback_synthesis(successful_results, original_query, language)
                else:
                    # Add a small delay before retry
                    time.sleep(1)
    
    def _create_synthesis_prompt(self, results: List[SearchResult],
                               original_query: str,
                               strategy: SearchStrategy,
                               language: Optional[str] = None) -> str:
        """Create a comprehensive prompt for result synthesis."""
        
        # Prepare search results with citation mapping
        results_text, citation_map = self._format_results_with_citations(results)
        
        # Create the main synthesis prompt
        prompt = f"""You are an expert research analyst tasked with synthesizing multiple search results into a comprehensive, accurate answer.

ORIGINAL QUERY: {original_query}

RESEARCH STRATEGY USED:
{strategy.reasoning}

SEARCH RESULTS WITH CITATIONS:
{results_text}

CITATION MAPPING:
{json.dumps(citation_map, indent=2)}

YOUR TASK:
Create a comprehensive answer following these steps:

1. **REASONING**: show your analysis process
2. **COMPREHENSIVE ANSWER**: 
    - Carefully analyze the context to extract relevant data, policies, requirements, or specifications.
    - Provide a complete and detailed answer that addresses the user's question.
    - Organize your response using headings, bullets, or numbering for clarity.
    - Avoid speculation or adding content not grounded in the provided context.
    - If information is missing, clearly state that it is not found in the current context.
   - Use proper citations in format [filename.ext, Page X]
   - Choose the most effective format to explain the answer:
     * Use bullet points or numbered lists for multiple items, steps, or requirements
     * Use paragraphs for explanations, context, or narrative information
     * Use a combination when needed for clarity
   - Be thorough and include all relevant information from sources
3. **FOLLOW-UP QUESTIONS**: Generate maximum 3 relevant follow-up questions only which can be answered based on the provided information

RESPONSE FORMAT - IMPORTANT:
Generate a valid JSON object with EXACTLY this structure (no duplicates!):
{{
    "reasoning": "<your reasoning approach>"
    "answer": "<your comprehensive answer with [filename.ext, Page X] citations>",
    "confidence_level": "high|medium|low",
    "follow_up_questions": [
        "Question 1?",
        "Question 2?",
        "Question 3?"
    ]
}}

# ANSWER FORMATTING GUIDELINES
    **CRITICAL**: Analyze the user's question and determine the appropriate response style.

    **Format for detailed responses:**
    - **Use clear headings and subheadings** (## Main Topic, ### Subtopic)
    - **Create numbered or bulleted lists** for multiple items
    - **Provide thorough explanations** for each point
    - **Organize information logically** with smooth flow and readability
    - **Include all relevant details** from the context

    Examples:
    ```
    ### Types of Life Insurance Policies

    #### 1. **Term Life Insurance** [source.pdf, Page 5]
    - **Definition**: Provides coverage for a specific period...
    - **Benefits**: Lower premiums, flexibility...
    - **Limitations**: No cash value, temporary coverage...

    #### 2. **Whole Life Insurance** [source.pdf, Page 6]
    - **Definition**: Permanent coverage with cash value...
    - **Benefits**: Guaranteed death benefit, cash accumulation...
    ```

CRITICAL INSTRUCTIONS:
1. Generate ONLY ONE JSON object - no duplicates or repetitions
2. Ensure the JSON is properly formatted and valid
3. Include ALL relevant details from the sources - do not summarize or truncate
4. Use the most effective format (bullets, paragraphs, or mixed) based on the content
5. Every factual claim must have a citation
"""

        # Add language specification if provided
        if language:
            prompt += f"\n\nLANGUAGE: Provide your answer in {language}."
        else:
            # default language of original query
            prompt += "\n\nLANGUAGE: Provide your answer in the same language as the original query."
        
        prompt += "\n\nGenerate ONLY the JSON response. Start with { and end with }."

        return prompt
    
    def _format_results_with_citations(self, results: List[SearchResult]) -> Tuple[str, Dict[str, str]]:
        """
        Format search results with proper citation information.
        
        Returns:
            Tuple of (formatted_results_text, citation_mapping)
        """
        formatted_results = []
        citation_map = {}
        
        for i, result in enumerate(results, 1):
            search_type = result.metadata.get('search_type', 'unknown')
            
            # Create source header
            source_key = f"Source {i}"
            source_header = f"[{source_key}] ({search_type.upper()})"
            
            # Build citation string
            citation_parts = []
            if result.source_info:
                if result.source_info.get('file_name'):
                    file_name = result.source_info['file_name']
                    page_no = result.source_info.get('page_no', 0)
                    citation = f"[{file_name}, Page {page_no}]"
                    citation_parts.append(f"{file_name}, Page {page_no}")
                    citation_map[source_key] = citation
                    source_header += f" - {file_name}, Page {page_no}"
            
            # If no source info, try to extract from content
            if source_key not in citation_map:
                # Look for citation patterns in the content itself
                citation_pattern = r'\(Source:\s*([^,]+),\s*Page\s*(\d+)\)'
                matches = re.findall(citation_pattern, result.content)
                if matches:
                    file_name, page_no = matches[0]
                    citation = f"[{file_name}, Page {page_no}]"
                    citation_map[source_key] = citation
                    source_header += f" - {file_name}, Page {page_no}"
                else:
                    citation_map[source_key] = "[Unknown Source]"
            
            # Format content (truncate if too long)
            content = result.content
            
            formatted_results.append(f"{source_header}:\n{content}\n")
        
        return "\n".join(formatted_results), citation_map

    def _parse_synthesis_response(self, response_content: str) -> Dict[str, Any]:
        """Parse the JSON response from the synthesis LLM."""
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
            
            # Attempt to fix common JSON errors
            # Remove any duplicate keys by parsing line by line
            lines = cleaned_response.split('\n')
            seen_keys = set()
            filtered_lines = []
            brace_count = 0
            skip_until_brace = False
            
            for line in lines:
                # Count braces to track nesting
                brace_count += line.count('{') - line.count('}')
                
                # Check if this line contains a key we've already seen
                if '"reasoning_steps"' in line and 'reasoning_steps' in seen_keys:
                    skip_until_brace = True
                    continue
                elif '"answer"' in line and 'answer' in seen_keys:
                    skip_until_brace = True
                    continue
                elif '"follow_up_questions"' in line and 'follow_up_questions' in seen_keys:
                    skip_until_brace = True
                    continue
                    
                # Skip lines until we close the duplicate section
                if skip_until_brace:
                    if ']' in line or ('}' in line and brace_count == 1):
                        skip_until_brace = False
                    continue
                
                # Track which keys we've seen
                for key in ['reasoning_steps', 'answer', 'confidence_level', 'follow_up_questions']:
                    if f'"{key}"' in line:
                        seen_keys.add(key)
                
                filtered_lines.append(line)
            
            cleaned_response = '\n'.join(filtered_lines)
            
            # Parse JSON
            parsed = json.loads(cleaned_response)
            
            # Validate required fields
            required_fields = ['reasoning_steps', 'answer', 'confidence_level', 'follow_up_questions']
            for field in required_fields:
                if field not in parsed:
                    parsed[field] = self._get_default_value(field)
            
            # Ensure follow_up_questions is a list and has max 3 items
            if isinstance(parsed.get('follow_up_questions'), list):
                parsed['follow_up_questions'] = parsed['follow_up_questions'][:3]
            
            return parsed
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse synthesis response as JSON: {e}")
            logger.error(f"Response content: {response_content[:500]}...")
            return self._extract_fallback_content(response_content)
    
    def _get_default_value(self, field: str) -> Any:
        """Get default value for missing fields."""
        defaults = {
            'reasoning_steps': [
                "Step 1 - Information Analysis: Analyzed available information from sources",
                "Step 2 - Pattern Recognition: Identified key patterns and themes", 
                "Step 3 - Cross-Validation: Cross-referenced information across sources",
                "Step 4 - Gap Analysis: Noted any limitations in available data",
                "Step 5 - Synthesis: Combined information to formulate comprehensive answer"
            ],
            'answer': "Based on the available information...",
            'confidence_level': 'medium',
            'follow_up_questions': [],
            'answer_completeness': 'partially answered'
        }
        return defaults.get(field, "")
    
    def _extract_fallback_content(self, response_content: str) -> Dict[str, Any]:
        """Extract content when JSON parsing fails."""
        # Try to extract answer from the response text
        answer_match = re.search(r'"answer":\s*"([^"]+)"', response_content)
        answer = answer_match.group(1) if answer_match else response_content[:1000]
        
        return {
            'reasoning_steps': ["Unable to parse detailed reasoning"],
            'answer': answer,
            'confidence_level': 'low',
            'follow_up_questions': []
        }
    
    def _create_no_results_response(self, original_query: str, 
                                  language: Optional[str] = None) -> SynthesisResult:
        """Create a response when no search results are available."""
        no_results_message = (
            "I couldn't find any relevant information in your documents or data to answer this question. "
            "This could be because the information isn't available in your uploaded files, or the question "
            "might need to be rephrased to better match the available content."
        )
        
        if language:
            # In a real implementation, you might want to translate this
            no_results_message = f"[Response in {language}] " + no_results_message
        
        return SynthesisResult(
            answer=no_results_message,
            reasoning_steps=["No relevant search results found", "Unable to provide answer based on available data"],
            sources_used=[],
            confidence_level='low',
            follow_up_questions=[
                "Could you try rephrasing your question?",
                "Do you have additional documents that might contain this information?"
            ],
            synthesis_metadata={
                'total_sources': 0,
                'strategy_used': 'fallback',
                'synthesis_approach': 'no_results_handling'
            }
        )
    
    def _create_fallback_synthesis(self, results: List[SearchResult],
                                 original_query: str,
                                 language: Optional[str] = None) -> SynthesisResult:
        """Create a fallback synthesis when the main synthesis fails."""
        logger.info("Creating fallback synthesis")
        
        # Simple concatenation of results with basic formatting
        combined_content = ""
        sources_used = []
        
        for i, result in enumerate(results[:5], 1):  # Limit to top 5 results
            combined_content += f"\n\nFrom Source {i}:\n{result.content[:800]}"
            
            sources_used.append({
                'source_number': i,
                'search_type': result.metadata.get('search_type', 'unknown'),
                'content_length': len(result.content)
            })
        
        fallback_answer = f"Based on the available information:{combined_content}"
        
        if language:
            fallback_answer = f"[Response in {language}] {fallback_answer}"
        else:
            fallback_answer = f"[Response in the same language as the original query] {fallback_answer}"
        
        return SynthesisResult(
            answer=fallback_answer,
            reasoning_steps=["Fallback synthesis due to processing error", "Combined available search results"],
            sources_used=sources_used,
            confidence_level='medium',
            follow_up_questions=[],
            synthesis_metadata={
                'total_sources': len(results),
                'strategy_used': 'fallback',
                'synthesis_approach': 'simple_concatenation'
            }
        )

    def synthesize_results_stream(self, search_results: List[SearchResult],
                              original_query: str,
                                strategy: SearchStrategy,
                                language: Optional[str] = None):
        """
        Synthesize results with streaming support.

        Yields chunks of the answer as they're generated.
        """
        logger.info(f"Synthesizing {len(search_results)} search results with streaming")

        # Filter successful results
        successful_results = [r for r in search_results if r.success and r.content.strip()]

        if not successful_results:
            yield {
                'type': 'answer_chunk',
                'content': "I couldn't find any relevant information to answer your question.",
                'is_first': True
            }
            yield {
                'type': 'sources',
                'content': []
            }
            return

        # Create synthesis prompt
        synthesis_prompt = self._create_synthesis_prompt(
            successful_results, original_query, strategy, language
        )

        try:
            # Create a custom callback for streaming
            class StreamingCallback(BaseCallbackHandler):
                def __init__(self, yield_func):
                    self.buffer = ""
                    self.is_first = True
                    self.yield_func = yield_func

                def on_llm_new_token(self, token: str, **kwargs) -> None:
                    self.buffer += token
                    # Yield when we have a complete sentence or enough content
                    if (token in '.!?\n' and len(self.buffer) > 50) or len(self.buffer) > 100:
                        self.yield_func({
                            'type': 'answer_chunk',
                            'content': self.buffer,
                            'is_first': self.is_first
                        })
                        self.is_first = False
                        self.buffer = ""

                def on_llm_end(self, response, **kwargs) -> None:
                    if self.buffer:
                        self.yield_func({
                            'type': 'answer_chunk',
                            'content': self.buffer,
                            'is_first': self.is_first
                        })

            # Storage for yielded data
            yielded_data = []
            
            def capture_yield(data):
                yielded_data.append(data)

            # Create callback
            callback = StreamingCallback(capture_yield)

            # Get streaming LLM with callback
            streaming_llm = get_streaming_llm(LLMType.COMPREHENSIVE, callbacks=[callback])

            # Run inference
            response = streaming_llm.invoke(synthesis_prompt)

            # Yield all captured chunks
            for item in yielded_data:
                yield item

            # If no chunks were yielded (fallback), yield the complete response
            if not yielded_data:
                yield {
                    'type': 'answer_chunk',
                    'content': response.content if hasattr(response, 'content') else str(response),
                    'is_first': True
                }

            # Send follow-up questions
            yield {
                'type': 'questions',
                'content': [
                    "What specific aspects would you like me to elaborate on?",
                    "Do you need more details about any particular finding?",
                    "Would you like me to search for additional information?"
                ]
            }

        except Exception as e:
            logger.error(f"Streaming synthesis error: {e}")
            yield {
                'type': 'error',
                'content': f"Error during synthesis: {str(e)}"
            }


# Create a singleton instance
_result_synthesis_service = None

def get_result_synthesis_service() -> ResultSynthesisService:
    """
    Get the result synthesis service singleton instance.
    
    Returns:
        ResultSynthesisService: The result synthesis service instance
    """
    global _result_synthesis_service
    if _result_synthesis_service is None:
        _result_synthesis_service = ResultSynthesisService()
    return _result_synthesis_service