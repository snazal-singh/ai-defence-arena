"""
Chat Context Detection Service.

This service determines when and how to use chat history in query processing,
optimizing for both relevance and token efficiency.
"""

import logging
import re
from typing import Dict, Any, List
from app.services.llm_service import get_fast_llm
import json

# Configure logging
logger = logging.getLogger(__name__)

class ChatContextService:
    """Service for intelligent chat context detection and extraction."""
    
    def __init__(self):
        """Initialize the chat context service."""
        self.llm = get_fast_llm()
        
        # Context detection patterns
        self.reference_patterns = self._init_reference_patterns()
        self.continuation_patterns = self._init_continuation_patterns()
        self.clarification_patterns = self._init_clarification_patterns()
        
        # Configuration
        self.min_query_length_for_context = 3  # words
        self.max_context_tokens = 1000
        self.context_relevance_threshold = 0.6
        
        logger.info("Chat context service initialized")
    
    def _init_reference_patterns(self) -> List[re.Pattern]:
        """Initialize patterns that indicate reference to previous context."""
        patterns = [
            # Pronouns without clear antecedents
            r'\b(this|that|it|they|them|these|those)\s+(is|are|was|were|means?|refers?)\b',
            r'\b(this|that|it)\s+(document|file|information|data|example|case)\b',
            
            # Direct references to previous conversation
            r'\b(as\s+(I|we|you)\s+(said|mentioned|discussed|talked|asked|explained))\b',
            r'\b(from\s+(our|the|my|your)\s+(conversation|discussion|chat|previous|earlier))\b',
            r'\b(what\s+(did|do)\s+(I|you|we)\s+(say|mean|ask|mention|discuss))\b',
            r'\b(you\s+(said|mentioned|told|explained|showed))\b',
            r'\b(I\s+(asked|mentioned|said)\s+(about|before|earlier))\b',
            
            # References to previous responses
            r'\b(the\s+(answer|response|explanation|information)\s+you\s+(gave|provided|shared))\b',
            r'\b(in\s+your\s+(response|answer|explanation|previous))\b',
            r'\b(according\s+to\s+(your|the)\s+(previous|earlier|last))\b'
        ]
        
        return [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    
    def _init_continuation_patterns(self) -> List[re.Pattern]:
        """Initialize patterns that indicate continuation of previous topic."""
        patterns = [
            # Continuation words
            r'\b(also|additionally|furthermore|moreover|besides)\b',
            r'\b(and\s+(what|how|why|when|where)\s+(about|if))\b',
            r'\b(what\s+(else|more|other))\b',
            r'\b(any\s+(other|additional|more))\b',
            
            # Follow-up questions
            r'\b(follow\s*up|continuing|more\s+(on|about))\b',
            r'\b(next|another|similar)\s+(question|example|case)\b',
            r'\b(related\s+to\s+(this|that))\b'
        ]
        
        return [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    
    def _init_clarification_patterns(self) -> List[re.Pattern]:
        """Initialize patterns that indicate request for clarification."""
        patterns = [
            # Clarification requests
            r'\b(clarify|explain\s+(more|better|further|again))\b',
            r'\b(what\s+(do\s+)?you\s+mean\s+(by)?)\b',
            r'\b(I\s+(don\'t|do\s+not)\s+(understand|get))\b',
            r'\b(can\s+you\s+(elaborate|expand|explain))\b',
            r'\b(more\s+(details?|information|explanation))\b',
            r'\b(could\s+you\s+(clarify|explain))\b',
            
            # Confusion indicators
            r'\b(confused|unclear|not\s+(clear|sure))\b',
            r'\b(I\'m\s+(lost|confused|not\s+following))\b'
        ]
        
        return [re.compile(pattern, re.IGNORECASE) for pattern in patterns]
    
    def detect_context_need(self, query: str, session_history_available: bool = True) -> Dict[str, Any]:
        """
        Detect if query needs chat context and determine the type of context needed.
        
        Args:
            query: User query to analyze
            session_history_available: Whether session has chat history
            
        Returns:
            Dictionary with context detection results
        """
        if not session_history_available:
            return {
                "needs_context": False,
                "context_type": "none",
                "confidence": 0.0,
                "reasoning": "No session history available"
            }
        
        # Quick pattern-based analysis
        pattern_result = self._pattern_based_detection(query)
        
        # If pattern detection is confident, use it
        if pattern_result["confidence"] >= 0.8:
            return pattern_result
        
        # For borderline cases, use LLM analysis
        if pattern_result["confidence"] >= 0.3:
            llm_result = self._llm_based_detection(query)
            # Combine pattern and LLM results
            return self._combine_detection_results(pattern_result, llm_result)
        
        return pattern_result
    
    def _pattern_based_detection(self, query: str) -> Dict[str, Any]:
        """Pattern-based context detection for fast processing."""
        query_lower = query.lower().strip()
        
        # Short queries often need context
        word_count = len(query.split())
        if word_count <= 3:
            return {
                "needs_context": True,
                "context_type": "recent",
                "confidence": 0.7,
                "reasoning": "Short query likely needs context"
            }
        
        # Check reference patterns
        reference_score = 0
        for pattern in self.reference_patterns:
            if pattern.search(query_lower):
                reference_score += 1
        
        if reference_score > 0:
            confidence = min(0.9, 0.6 + (reference_score * 0.15))
            return {
                "needs_context": True,
                "context_type": "reference",
                "confidence": confidence,
                "reasoning": f"Found {reference_score} reference patterns"
            }
        
        # Check continuation patterns
        continuation_score = 0
        for pattern in self.continuation_patterns:
            if pattern.search(query_lower):
                continuation_score += 1
        
        if continuation_score > 0:
            confidence = min(0.8, 0.5 + (continuation_score * 0.2))
            return {
                "needs_context": True,
                "context_type": "continuation",
                "confidence": confidence,
                "reasoning": f"Found {continuation_score} continuation patterns"
            }
        
        # Check clarification patterns
        clarification_score = 0
        for pattern in self.clarification_patterns:
            if pattern.search(query_lower):
                clarification_score += 1
        
        if clarification_score > 0:
            confidence = min(0.85, 0.6 + (clarification_score * 0.15))
            return {
                "needs_context": True,
                "context_type": "clarification",
                "confidence": confidence,
                "reasoning": f"Found {clarification_score} clarification patterns"
            }
        
        # No strong indicators found
        return {
            "needs_context": False,
            "context_type": "none",
            "confidence": 0.8,
            "reasoning": "No context indicators found"
        }
    
    def _llm_based_detection(self, query: str) -> Dict[str, Any]:
        """LLM-based context detection for complex cases."""
        prompt = f"""Analyze if this user query requires context from previous conversation.

Query: "{query}"

Consider these indicators:
1. Pronouns without clear referents (this, that, it, etc.)
2. References to previous discussion ("as you said", "from before")
3. Requests for clarification or elaboration
4. Follow-up questions that build on previous context
5. Short queries that lack complete information

Respond with JSON only:
{{
    "needs_context": true/false,
    "context_type": "none/recent/reference/clarification/continuation",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}}"""

        try:
            response = self.llm.invoke(prompt)
            result = json.loads(response.content.strip())
            
            # Validate response
            if not isinstance(result, dict):
                raise ValueError("Invalid JSON response")
            
            # Ensure required fields
            result.setdefault("needs_context", False)
            result.setdefault("context_type", "none")
            result.setdefault("confidence", 0.0)
            result.setdefault("reasoning", "LLM analysis")
            
            return result
            
        except Exception as e:
            logger.error(f"LLM context detection error: {e}")
            return {
                "needs_context": False,
                "context_type": "none",
                "confidence": 0.0,
                "reasoning": f"LLM error: {str(e)}"
            }
    
    def _combine_detection_results(self, pattern_result: Dict, llm_result: Dict) -> Dict[str, Any]:
        """Combine pattern-based and LLM-based detection results."""
        # Weight pattern detection more heavily for performance
        pattern_weight = 0.7
        llm_weight = 0.3
        
        # If both agree, use higher confidence
        if pattern_result["needs_context"] == llm_result["needs_context"]:
            combined_confidence = max(pattern_result["confidence"], llm_result["confidence"])
            context_type = pattern_result["context_type"] if pattern_result["confidence"] >= llm_result["confidence"] else llm_result["context_type"]
        else:
            # If they disagree, use weighted average
            combined_confidence = (pattern_result["confidence"] * pattern_weight + 
                                 llm_result["confidence"] * llm_weight)
            
            # Choose based on higher confidence
            if pattern_result["confidence"] >= llm_result["confidence"]:
                needs_context = pattern_result["needs_context"]
                context_type = pattern_result["context_type"]
            else:
                needs_context = llm_result["needs_context"]
                context_type = llm_result["context_type"]
        
        return {
            "needs_context": pattern_result["needs_context"] or llm_result["needs_context"],
            "context_type": context_type,
            "confidence": combined_confidence,
            "reasoning": f"Combined: {pattern_result['reasoning']} | {llm_result['reasoning']}"
        }
    
    def extract_relevant_context(self, chat_history: List[Dict], current_query: str, 
                                context_type: str = "recent") -> Dict[str, Any]:
        """
        Extract relevant context from chat history based on the detected context type.
        
        Args:
            chat_history: List of previous messages
            current_query: Current user query
            context_type: Type of context needed
            
        Returns:
            Extracted context information
        """
        if not chat_history:
            return {"context": "", "token_count": 0, "messages_used": 0}
        
        if context_type == "recent":
            return self._extract_recent_context(chat_history)
        elif context_type == "reference":
            return self._extract_reference_context(chat_history, current_query)
        elif context_type == "clarification":
            return self._extract_clarification_context(chat_history, current_query)
        elif context_type == "continuation":
            return self._extract_continuation_context(chat_history, current_query)
        else:
            return self._extract_adaptive_context(chat_history, current_query)
    
    def _extract_recent_context(self, chat_history: List[Dict]) -> Dict[str, Any]:
        """Extract recent conversation context."""
        # Get last 2-3 conversation pairs
        recent_messages = chat_history[-6:] if len(chat_history) >= 6 else chat_history
        
        context_parts = []
        token_count = 0
        
        for msg in recent_messages:
            role = "User" if msg.get("role") == "user" else "Assistant"
            content = msg.get("content", "")
            
            # Truncate long messages
            if len(content) > 150:
                content = content[:150] + "..."
            
            context_parts.append(f"{role}: {content}")
            token_count += len(content.split()) * 1.3  # Rough token estimate
        
        context = "\n".join(context_parts)
        
        return {
            "context": context,
            "token_count": int(token_count),
            "messages_used": len(recent_messages)
        }
    
    def _extract_reference_context(self, chat_history: List[Dict], query: str) -> Dict[str, Any]:
        """Extract context based on specific references in the query."""
        # Look for keywords in query that might match previous conversation
        query_keywords = set(query.lower().split())
        
        relevant_messages = []
        
        # Score messages based on keyword overlap
        for msg in reversed(chat_history[-20:]):  # Check recent 20 messages
            content = msg.get("content", "").lower()
            content_keywords = set(content.split())
            
            # Calculate relevance score
            overlap = len(query_keywords & content_keywords)
            if overlap >= 2:  # At least 2 matching keywords
                msg_score = overlap / len(query_keywords) if query_keywords else 0
                relevant_messages.append((msg, msg_score))
        
        # Sort by relevance and take top messages
        relevant_messages.sort(key=lambda x: x[1], reverse=True)
        top_messages = [msg for msg, score in relevant_messages[:4]]
        
        if not top_messages:
            return self._extract_recent_context(chat_history)
        
        # Format context
        context_parts = []
        token_count = 0
        
        for msg in top_messages:
            role = "User" if msg.get("role") == "user" else "Assistant"
            content = msg.get("content", "")
            
            if len(content) > 200:
                content = content[:200] + "..."
            
            context_parts.append(f"{role}: {content}")
            token_count += len(content.split()) * 1.3
        
        return {
            "context": "\n".join(context_parts),
            "token_count": int(token_count),
            "messages_used": len(top_messages)
        }
    
    def _extract_clarification_context(self, chat_history: List[Dict], query: str) -> Dict[str, Any]:
        """Extract context for clarification requests."""
        # For clarification, we need the immediate previous response
        if not chat_history:
            return {"context": "", "token_count": 0, "messages_used": 0}
        
        # Get the last assistant response and the user query before it
        last_messages = chat_history[-3:] if len(chat_history) >= 3 else chat_history
        
        context_parts = []
        token_count = 0
        
        for msg in last_messages:
            role = "User" if msg.get("role") == "user" else "Assistant"
            content = msg.get("content", "")
            
            # Don't truncate as much for clarification context
            if len(content) > 300:
                content = content[:300] + "..."
            
            context_parts.append(f"{role}: {content}")
            token_count += len(content.split()) * 1.3
        
        return {
            "context": "\n".join(context_parts),
            "token_count": int(token_count),
            "messages_used": len(last_messages)
        }
    
    def _extract_continuation_context(self, chat_history: List[Dict], query: str) -> Dict[str, Any]:
        """Extract context for continuation of previous topic."""
        # Similar to recent context but focus on the current topic thread
        return self._extract_recent_context(chat_history)
    
    def _extract_adaptive_context(self, chat_history: List[Dict], query: str) -> Dict[str, Any]:
        """Extract adaptive context using multiple strategies."""
        # Try reference-based first, fallback to recent
        reference_context = self._extract_reference_context(chat_history, query)
        
        if reference_context["messages_used"] >= 2:
            return reference_context
        else:
            return self._extract_recent_context(chat_history)


# Singleton instance
_chat_context_service = None

def get_chat_context_service() -> ChatContextService:
    """Get the chat context service singleton instance."""
    global _chat_context_service
    if _chat_context_service is None:
        _chat_context_service = ChatContextService()
    return _chat_context_service