"""
This module provides response generation for different types of queries:
- General chat responses (no document context)
- Summary responses (using abstractive summaries)
- Document query responses (using document context)
- Data query responses (using SQL results)
- Hybrid responses (using multiple contexts)
"""

import json
import logging
import re
from typing import Dict, Any, Optional

from app.services.llm_service import get_standard_llm
from utils.translation import translate_to_indic

# Configure logging
logger = logging.getLogger(__name__)

class ResponseGeneratorService:
    """Service for generating responses to user queries."""
    
    def __init__(self):
        """Initialize the response generator service."""
        logger.info("Initializing response generator service")
        # Use standard LLM for most response generation tasks
        self.llm = get_standard_llm()
        
        # Question type patterns for intelligent detection
        self._init_question_patterns()
        
    def _init_question_patterns(self):
        """Initialize patterns for detecting question types."""
        # Patterns that indicate need for detailed/pointwise answers
        self.detailed_patterns = [
            r'\b(explain|describe|elaborate|discuss|analyze|break\s*down|detail)\b',
            r'\b(how\s+(does|do|to|can)|why\s+(does|do|is|are))\b',
            r'\b(what\s+are\s+the\s+(steps|benefits|advantages|disadvantages|differences|types|kinds|ways|methods|factors|reasons|causes|effects|impacts))\b',
            r'\b(list\s+(the|all)?|enumerate|outline)\b',
            r'\b(compare|contrast|differentiate|distinguish)\b',
            r'\b(process|procedure|methodology|approach|strategy)\b',
            r'\b(advantages?\s+and\s+disadvantages?|pros?\s+and\s+cons?)\b',
            r'\b(breakdown|analysis|overview|summary|comprehensive)\b',
            r'\b(tell\s+me\s+about|give\s+me\s+(details?|information)\s+about)\b'
        ]
        
        # Patterns that indicate need for direct/specific answers
        self.direct_patterns = [
            r'^\s*(what\s+is|who\s+is|when\s+(is|was|did)|where\s+(is|was))\s+',
            r'^\s*(how\s+much|how\s+many|what\s+time|what\s+date)\s+',
            r'\b(yes\s+or\s+no|true\s+or\s+false)\b',
            r'^\s*(is|are|was|were|does|do|did|can|could|will|would|should)\s+',
            r'\b(definition\s+of|meaning\s+of|what\s+does\s+\w+\s+mean)\b',
            r'\b(exact|specific|precise|particular)\b.*\b(number|amount|date|time|name|value)\b'
        ]
        
        # Compile patterns for efficiency
        self.detailed_compiled = [re.compile(pattern, re.IGNORECASE) for pattern in self.detailed_patterns]
        self.direct_compiled = [re.compile(pattern, re.IGNORECASE) for pattern in self.direct_patterns]
    
    def generate_general_chat_response(self, user_query: str, language: Optional[str] = None,
                                     chat_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Generate a response for general chat queries.
        
        Args:
            user_query: User's query
            language: Preferred response language
            chat_context: Optional chat context information
            
        Returns:
            Response data
        """
        # Create prompt for LLM with optional chat context
        prompt = self._create_general_chat_prompt(user_query, language, chat_context)
        
        # Generate response from LLM - use fast LLM for simple responses
        try:
            logger.info(f'Generating general chat response with approx token count: {len(prompt.split()) * 1.33}')
            # llm_response = self.fast_llm.invoke(prompt)
            llm_response = self.llm.invoke(prompt)
            logger.info(f'Generated general chat response')
            response = str(llm_response.content)
            response = self._translate_response(response, language)

            return {"answer": response}
        except Exception as e:
            logger.error(f'Error generating general chat response: {e}')
            return {"answer": "I'm sorry, I encountered an error while processing your request. Please try again."}
    
    def generate_document_response(self, user_query: str, context: str, 
                                 language: Optional[str] = None,
                                 chat_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Generate a response for document queries with adaptive formatting.
        
        Args:
            user_query: User's query
            context: Document context
            language: Preferred response language
            chat_context: Optional chat context information
            
        Returns:
            Response data
        """
        # Create prompt for LLM with chat context and adaptive style detection
        prompt = self._create_document_prompt(user_query, context, language, chat_context)
        
        # Generate response from LLM
        try:
            logger.info(f'Generating response with approx token count: {len(prompt.split()) * 1.33}')
            llm_response = self.llm.invoke(prompt)
            logger.info(f'Generated response: {str(llm_response.content)}')
            response_text = str(llm_response.content)
            response_text = self._translate_response(response_text, language)

            # Extract components from the response
            # cleaned_response, questions = self._extract_structured_response(response_text)

            return {
                "answer": response_text,
                "questions": []
            }
        except Exception as e:
            logger.error(f'Error generating document response: {e}')
            return {
                "answer": "I encountered an error while processing your query. Please try again or rephrase your question.",
                "questions": []
            }
            
    def generate_data_response(self, user_query: str, sql_context: str, 
                            language: Optional[str] = None,
                            chat_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Generate a response for data queries with optional chat context.
        
        Args:
            user_query: User's query
            sql_context: SQL query results context
            language: Preferred response language
            chat_context: Optional chat context information
            
        Returns:
            Response data
        """
        # Create prompt for LLM with chat context
        prompt = self._create_data_prompt(user_query, sql_context, language, chat_context)
        
        # Generate response from LLM
        try:
            logger.info(f'Generating data response with approx token count: {len(prompt.split()) * 1.33}')
            llm_response = self.llm.invoke(prompt)
            logger.info(f'Generated data response')
            response_text = str(llm_response.content)
            response_text = self._translate_response(response_text, language)

            # Extract components from the response
            # cleaned_response, questions = self._extract_structured_response(response_text)

            return {
                "answer": response_text,
                "questions": []
            }

        except Exception as e:
            logger.error(f'Error generating data response: {e}')

            # if is_valid_json(cleaned_responsex)

            return {
                "answer": "I encountered an error while analyzing the data. Please try again or rephrase your question.",
                "questions": []
            }
    
    def parse_cleaned_response(cleaned_response):
        """
        Robust function to parse nested JSON responses.
        
        Args:
            cleaned_response: Can be dict, string, or other types
            
        Returns:
            dict: {
                "parsed_answer": str or None,
                "parsed_questions": list or None
            }
        """
        
        # Case 1: If input is a plain string (not containing valid JSON)
        if isinstance(cleaned_response, str):
            try:
                # Try to parse the string as JSON
                cleaned_response = json.loads(cleaned_response)
            except (json.JSONDecodeError, TypeError):
                # If it's just a plain string, return None for both
                return {
                    "parsed_answer": None,
                    "parsed_questions": None
                }
        
        # Case 2: If it's not a dict at this point, return None for both
        if not isinstance(cleaned_response, dict):
            return {
                "parsed_answer": None,
                "parsed_questions": None
            }
        
        # Case 3: Parse the dict structure
        answer_field = cleaned_response.get('answer', '')
        questions_field = cleaned_response.get('questions', [])
        
        # Try to parse the answer field as nested JSON
        if isinstance(answer_field, str) and answer_field.strip():
            try:
                # Parse the nested JSON string
                answer_json = json.loads(answer_field)
                
                if isinstance(answer_json, dict):
                    parsed_answer = answer_json.get('answer', '')
                    parsed_questions = answer_json.get('relevant_questions', [])
                else:
                    # If parsed JSON is not a dict, use original values
                    parsed_answer = answer_field
                    parsed_questions = questions_field
                    
            except (json.JSONDecodeError, TypeError):
                # If answer field is not valid JSON, use it as is
                parsed_answer = answer_field
                parsed_questions = questions_field
        else:
            # If answer field is empty or not a string
            parsed_answer = answer_field
            parsed_questions = questions_field
        
        return {
            "parsed_answer": parsed_answer,
            "parsed_questions": parsed_questions
        }
    def generate_hybrid_response(self, user_query: str, document_context: str, 
                               sql_context: str,
                               language: Optional[str] = None,
                               chat_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Generate a response for hybrid queries needing both document and data contexts.
        
        Args:
            user_query: User's query
            document_context: Document context
            sql_context: SQL query results context
            language: Preferred response language
            chat_context: Optional chat context information
            
        Returns:
            Response data
        """
        # Create prompt for LLM with chat context
        prompt = self._create_hybrid_prompt(user_query, document_context, sql_context, language, chat_context)
        
        # Generate response from LLM
        try:
            logger.info(f'Generating hybrid response with approx token count: {len(prompt.split()) * 1.33}')
            llm_response = self.llm.invoke(prompt)
            logger.info(f'Generated hybrid response')
            response_text = str(llm_response.content)
            response_text = self._translate_response(response_text, language)

            # Extract components from the response
            # cleaned_response, questions = self._extract_structured_response(response_text)

            return {
                "answer": response_text,
                "questions": []
            }
        except Exception as e:
            logger.error(f'Error generating hybrid response: {e}')
            return {
                "answer": "I encountered an error while processing your query. Please try again or rephrase your question.",
                "questions": []
            }

    def generate_document_aware_chat_response(self, user_query: str, documents_info: Dict[str, Any],
                                       language: Optional[str] = None,
                                       chat_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Generate a response for general chat when documents are available.
        This handles cases where the user has selected documents but is asking general questions.
        
        Args:
            user_query: User's query
            documents_info: Information about available documents
            language: Preferred response language
            chat_context: Optional chat context information
            
        Returns:
            Response data
        """
        # Create prompt for LLM with chat context
        prompt = self._create_document_aware_chat_prompt(user_query, documents_info, language, chat_context)
        
        # Generate response from LLM - use fast LLM for simple responses
        try:
            # llm_response = self.fast_llm.invoke(prompt)
            llm_response = self.llm.invoke(prompt)
            logger.info(f'Generated document-aware chat response')
            response = str(llm_response.content)
            response = self._translate_response(response, language)

            return {
                "answer": response,
                "questions": []
            }
        except Exception as e:
            logger.error(f'Error generating document-aware chat response: {e}')
            return {"answer": "I'm sorry, I encountered an error while processing your request. Please try again."}
    
    def _create_general_chat_prompt(self, user_query: str, language: Optional[str] = None,
                                  chat_context: Optional[Dict[str, Any]] = None) -> str:
        """Create prompt for general chat with optional chat context."""
        prompt = f"""You are icarKno, a document assistant created by Carnot Research Pvt Ltd.
The user has not uploaded any documents yet. Respond conversationally and briefly.
If relevant, mention they can upload files or select a knowledge container to ask document-specific questions.
Do not make up information or answer factual questions from general knowledge.

"""
        
        # Add chat context if available
        if chat_context and chat_context.get("context_used"):
            context_text = chat_context.get("context", "")
            prompt += f"\nPrevious conversation context:\n{context_text}\n\n"
        
        language_instruction = self._get_language_instruction(language)
        
        prompt += f"""Question:
        ```{user_query}```

        {language_instruction}
        """

        return prompt
    
    def _create_document_prompt(self, user_question: str, context: str, language: Optional[str] = None,
                          chat_context: Optional[Dict[str, Any]] = None) -> str:

    # Extract image description from question if present
        image_description = ""
        if "\n\nImage Description:" in user_question:
            parts = user_question.split("\n\nImage Description:")
            user_question = parts[0].strip()
            image_description = parts[1].strip()

        prompt = f"""You are a document assistant. Answer ONLY using the information in the CONTEXT below.

    STRICT RULES:
    - Use ONLY information explicitly stated in the CONTEXT. Do not add, infer, or assume anything beyond it.
    - Do NOT expand abbreviations, acronyms, or short forms unless the full form is explicitly written in the CONTEXT.
    - Do NOT use any prior knowledge, general knowledge, or external information.
    - If the answer is not in the CONTEXT, respond exactly: "The information is not available in the provided documents."
    - Do not guess, speculate, or fill gaps with plausible-sounding information.
    - Use bullet points or structure only if required to explain the answer; otherwise answer directly.
    """

        if chat_context and chat_context.get("context_used"):
            context_text = chat_context.get("context", "")
            prompt += f"""
    Previous conversation history:
    {context_text}
    """
        language_instruction = self._get_language_instruction(language)
        
        # Inject image description into CONTEXT
        if image_description:
            context = f"{context}\n\n[Image Provided by User]: {image_description}"

        prompt += f"""
    CONTEXT:
    {context}

    QUESTION:
    {user_question}

    {language_instruction}

    Generate ONLY the answer. No preamble, no commentary.
    """
        return prompt
    
    def _create_data_prompt(self, user_query: str, sql_context: str, language: Optional[str] = None,
                          chat_context: Optional[Dict[str, Any]] = None) -> str:
        """Create prompt for data queries with adaptive formatting."""
        prompt = f"""You are a data assistant. Answer ONLY using the data provided in the DATA CONTEXT below.

STRICT RULES:
- Use ONLY the values, figures, and facts present in the DATA CONTEXT. Do not infer or extrapolate beyond what is shown.
- Do NOT expand abbreviations or short forms unless explicitly defined in the DATA CONTEXT.
- Do NOT use external knowledge or assumptions to fill gaps.
- If the data does not contain enough information to answer the question, say: "The data does not contain sufficient information to answer this."
- Do not mention SQL, queries, or table names in your response.
- Report numbers and values exactly as they appear in the data.
"""

        # Add chat context if available
        if chat_context and chat_context.get("context_used"):
            context_text = chat_context.get("context", "")
            prompt += f"""
Previous conversation context:
{context_text}
"""

        language_instruction = self._get_language_instruction(language)

        prompt += f"""
DATA CONTEXT:
{sql_context}

QUESTION: {user_query}

{language_instruction}

Generate ONLY the answer. No preamble, no commentary.
"""

        return prompt
    
    def _create_hybrid_prompt(self, user_query: str, document_context: str, sql_context: str,
                            language: Optional[str] = None, chat_context: Optional[Dict[str, Any]] = None) -> str:
        """Create prompt for hybrid queries with adaptive formatting."""
        prompt = f"""You are a document and data assistant. Answer ONLY using the DOCUMENT CONTEXT and DATA CONTEXT provided below.

STRICT RULES:
- Use ONLY information explicitly present in the DOCUMENT CONTEXT or DATA CONTEXT. Do not add, infer, or assume anything beyond them.
- Do NOT expand abbreviations, acronyms, or short forms unless the full form is explicitly written in the provided contexts.
- Do NOT use any external or general knowledge.
- If the answer is not present in either context, respond exactly: "The information is not available in the provided documents or data."
- Do not mention SQL, queries, or table names in your response.
- Report numbers and values exactly as they appear in the data.
"""

        # Add chat context if available
        if chat_context and chat_context.get("context_used"):
            context_text = chat_context.get("context", "")
            prompt += f"""
Previous conversation context:
{context_text}
"""

        language_instruction = self._get_language_instruction(language)

        prompt += f"""
DOCUMENT CONTEXT:
{document_context}

DATA CONTEXT:
{sql_context}

QUESTION: {user_query}

{language_instruction}

Generate ONLY the answer. No preamble, no commentary.
"""

        return prompt
    
    def _create_document_aware_chat_prompt(self, user_query: str, documents_info: Dict[str, Any],
                                         language: Optional[str] = None,
                                         chat_context: Optional[Dict[str, Any]] = None) -> str:
        """Create prompt for document-aware chat with chat context."""
        prompt = f"""You are icarKno, a document assistant created by Carnot Research Pvt Ltd.
The user has documents loaded but is asking a general question. Respond conversationally and briefly.
Do not make up information or answer factual questions from general knowledge — only reference the documents if directly relevant.

Documents available:
- Files: {documents_info.get('file_count', 'unknown')}
- Types: {', '.join(documents_info.get('file_types', ['unknown']))}
- Topics: {documents_info.get('topics', 'various')}

"""

        # Add chat context if available
        if chat_context and chat_context.get("context_used"):
            context_text = chat_context.get("context", "")
            prompt += f"""Previous conversation context:
{context_text}

"""

        language_instruction = self._get_language_instruction(language)

        prompt += f"""Question: {user_query}

{language_instruction}
"""

        return prompt
        
    def _extract_structured_response(self, response):
        """
        Extract questions from LLM response.
        
        Args:
            response: LLM response text
            
        Returns:
            tuple: (answer, questions)
        """
        # Pre-clean response
        cleaned = re.sub(r'(?i)json\s*:', '', response)  # Remove JSON: prefixes
        cleaned = cleaned.strip("` \n")  # Remove code block markers
        
        if cleaned.lower().startswith('json'):
            cleaned = cleaned[cleaned.index('{'):]

        # Attempt 1: Strict JSON parsing
        try:
            parsed = json.loads(cleaned)
            return self._validate_structure(parsed)
        except json.JSONDecodeError:
            pass
            
        # Attempt 2: Fix common syntax errors
        try:
            # Add quotes around unquoted keys
            repaired = re.sub(r'(?<!\\)(\w+)(\s*:)', r'"\1"\2', cleaned)
            # Fix trailing commas
            repaired = re.sub(r',(\s*[}\]])', r'\1', repaired)
            parsed = json.loads(repaired)
            return self._validate_structure(parsed)
        except json.JSONDecodeError:
            pass

        # Attempt 3: Fallback to text parsing
        return self._extract_data(cleaned)

    def _get_language_instruction(self, language: Optional[str]) -> str:
        """Return a fixed instruction asking the LLM to always respond in English.

        Translation to the user's preferred language is handled separately via
        the IndicTrans2 model after the LLM generates its English response.
        """
        return "**CRITICAL: Answer in English ONLY.**"

    def _translate_response(self, text: str, language: Optional[str]) -> str:
        """Translate *text* from English to *language* using IndicTrans2.

        If *language* is None, 'English', or unsupported, the original English
        text is returned unchanged.
        """
        if not language or language.strip().lower() == "english":
            return text
        return translate_to_indic(text, language)

    def _validate_structure(self, parsed):
        """
        Ensure required fields exist with proper types.
        
        Args:
            parsed: Parsed JSON structure
            
        Returns:
            tuple: (answer, questions)
        """
        return (
            parsed.get('answer', ''),
            parsed.get('relevant_questions', [])
        )

    def _extract_data(self, response):
        """
        Extract answer, and questions from structured text.
        
        Args:
            response: LLM response text
            
        Returns:
            tuple: (answer, questions)
        """
        # Initialize defaults
        result = {
            'answer': response,  # Default to full response if no sections found
            'questions': []
        }
        
        try:
            # Define flexible section headers with regex patterns
            section_patterns = {
                'questions': re.compile(r'^\s*\*\*(?:Relevant|Leading) Questions:\*\*', re.IGNORECASE | re.MULTILINE)
            }
            
            # Find all section positions
            sections = []
            for name, pattern in section_patterns.items():
                match = pattern.search(response)
                if match:
                    sections.append((name, match.start()))
            
            # Sort sections by their position in the text
            sections.sort(key=lambda x: x[1])
            
            if not sections:
                # No sections found, return full response as answer
                return result['answer'], []
            
            # Extract answer text (everything before first section)
            answer_start = 0
            if response[:sections[0][1]].strip().startswith('**Answer:**'):
                answer_start = response.find('**Answer:**') + len('**Answer:**')
            
            result['answer'] = response[answer_start:sections[0][1]].strip()
            
            # Process each section
            for i, (name, pos) in enumerate(sections):
                # Get section content (from current pos to next section start or end)
                end_pos = sections[i+1][1] if i+1 < len(sections) else len(response)
                section_content = response[pos:end_pos].strip()
                
                # Remove section header
                header_match = section_patterns[name].search(section_content)
                if header_match:
                    content = section_content[header_match.end():].strip()
                else:
                    content = section_content
                
                # Process based on section type
                if name == 'questions':
                    result['questions'] = self._extract_questions(content)
            
        except Exception as e:
            logger.error(f"Error extracting structured response: {e}")
        
        logger.info(f'Extracted fields - Answer: {result["answer"]}, Questions: {result["questions"]}')
        return result['answer'], result['questions']

    def _extract_questions(self, content):
        """
        Extract questions from formatted content.
        
        Args:
            content: Content containing question information
            
        Returns:
            list: List of question strings
        """
        questions = []
        # Split potential question blocks
        blocks = re.split(r'\n\s*\d+[\.\)]?|\n\s*[\-\*•]', content)
        
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            # Remove quotation marks
            block = re.sub(r'^[\'"]|[\'"]$', '', block)
            # Validate question structure
            if re.search(r'\?$|^(how|what|when|where|why|who|can|does|do|is|are)', block, re.I):
                questions.append(block)
        
        return questions[:3]  # Return max 3 questions

# Create a singleton instance
_response_generator_service = None

def get_response_generator_service() -> ResponseGeneratorService:
    """
    Get the response generator service singleton instance.
    
    Returns:
        ResponseGeneratorService: The response generator service instance
    """
    global _response_generator_service
    if _response_generator_service is None:
        _response_generator_service = ResponseGeneratorService()
    return _response_generator_service