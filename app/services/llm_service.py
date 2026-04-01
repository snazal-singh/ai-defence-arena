"""
Centralized LLM service for managing all LLM interactions across the application.

This module provides a factory pattern for creating and managing LLM instances,
making it easy to switch between different providers and configurations.
"""

import logging
from enum import Enum
from typing import Optional, List

from langchain_community.chat_models import ChatOllama
from langchain.base_language import BaseLanguageModel
from langchain.callbacks.base import BaseCallbackHandler
from config import Config

# Configure logging
logger = logging.getLogger(__name__)

OLLAMA_LLM_MODEL = Config.OLLAMA_LLM_MODEL

class LLMType(Enum):
    """Different LLM configurations for different use cases."""
    FAST = "fast"           # Quick responses, lower cost
    STANDARD = "standard"   # Balanced performance
    COMPREHENSIVE = "comprehensive"  # High quality, complex tasks
    CREATIVE = "creative"   # Creative and reasoning tasks
    CODE = "code"          # Code generation and analysis

# Convenience functions for common use cases
def get_fast_llm() -> BaseLanguageModel:
    """Get a fast LLM for quick responses."""
    return ChatOllama(model = OLLAMA_LLM_MODEL)

def get_standard_llm() -> BaseLanguageModel:
    """Get a standard LLM for general use."""
    return ChatOllama(model = OLLAMA_LLM_MODEL)

def get_comprehensive_llm() -> BaseLanguageModel:
    """Get a comprehensive LLM for complex tasks."""
    return ChatOllama(model = OLLAMA_LLM_MODEL)

def get_creative_llm() -> BaseLanguageModel:
    """Get a creative LLM for reasoning and creative tasks."""
    return ChatOllama(model = OLLAMA_LLM_MODEL)

def get_code_llm() -> BaseLanguageModel:
    """Get a code-focused LLM."""
    return ChatOllama(model = OLLAMA_LLM_MODEL)

def get_streaming_llm(llm_type: LLMType = LLMType.STANDARD, 
                     callbacks: Optional[List[BaseCallbackHandler]] = None) -> BaseLanguageModel:
    """Get a streaming LLM with callbacks."""
    return ChatOllama(model = OLLAMA_LLM_MODEL, callbacks=callbacks)

# import logging
# import requests
# from enum import Enum
# from typing import Any, Dict, Iterator, List, Optional
# import json

# from langchain_core.callbacks import CallbackManagerForLLMRun
# from langchain_core.language_models.chat_models import BaseChatModel
# from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
# from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
# from langchain.base_language import BaseLanguageModel
# from langchain.callbacks.base import BaseCallbackHandler

# from config import Config

# # Configure logging
# logger = logging.getLogger(__name__)


# # ---------------------------------------------------------------------------
# # GPU Server configuration (read once at import time)
# # ---------------------------------------------------------------------------

# GPU_SERVER_BASE_URL: str = getattr(Config, "GPU_SERVER_BASE_URL", "https://gpu.server.domain")
# GPU_SERVER_API_KEY: str = getattr(Config, "GPU_SERVER_API_KEY", "")
# GPU_SERVER_MODEL: str = getattr(Config, "GPU_SERVER_MODEL", "gpt-oss:20b")
# GPU_SERVER_DEFAULT_MAX_TOKENS: int = getattr(Config, "GPU_SERVER_DEFAULT_MAX_TOKENS", 1000)
# GPU_SERVER_VERIFY_SSL: bool = getattr(Config, "GPU_SERVER_VERIFY_SSL", False)   # set True in prod with valid cert

# CHAT_ENDPOINT = f"{GPU_SERVER_BASE_URL.rstrip('/')}/cdot/gptoss20b/api/chat"


# # ---------------------------------------------------------------------------
# # Custom LangChain-compatible chat model
# # ---------------------------------------------------------------------------

# class GPUServerChatModel(BaseChatModel):
#     """
#     LangChain-compatible wrapper around the internal GPU server's OpenAI-style
#     /api/chat endpoint.  Supports both standard invoke() and streaming callbacks
#     so it can be used as a drop-in replacement for ChatOllama / ChatOpenAI.

#     Usage
#     -----
#     llm = GPUServerChatModel()
#     response = llm.invoke("Explain time dilation")   # returns AIMessage
#     text = response.content
#     """

#     # ---- Pydantic fields (LangChain v0.1+ uses pydantic v1 model) ----------
#     model: str = GPU_SERVER_MODEL
#     api_key: str = GPU_SERVER_API_KEY
#     endpoint: str = CHAT_ENDPOINT
#     max_tokens: int = GPU_SERVER_DEFAULT_MAX_TOKENS
#     temperature: float = 0.7
#     verify_ssl: bool = GPU_SERVER_VERIFY_SSL
#     timeout: int = 120          # seconds

#     class Config:
#         # Allow extra fields coming from parent without raising errors
#         extra = "allow"

#     # ---- Required BaseChatModel properties ---------------------------------

#     @property
#     def _llm_type(self) -> str:
#         return "gpu_server_chat"

#     @property
#     def _identifying_params(self) -> Dict[str, Any]:
#         return {
#             "model": self.model,
#             "endpoint": self.endpoint,
#             "max_tokens": self.max_tokens,
#             "temperature": self.temperature,
#         }

#     # ---- Message conversion helpers ----------------------------------------

#     @staticmethod
#     def _to_api_messages(messages: List[BaseMessage]) -> List[Dict[str, str]]:
#         """Convert LangChain message objects → API payload messages list."""
#         role_map = {
#             HumanMessage: "user",
#             AIMessage: "assistant",
#             SystemMessage: "system",
#         }
#         result = []
#         for msg in messages:
#             role = role_map.get(type(msg), "user")
#             content = msg.content if isinstance(msg.content, str) else str(msg.content)
#             result.append({"role": role, "content": content})
#         return result

#     # ---- Core generation (non-streaming) -----------------------------------

#     def _generate(
#         self,
#         messages: List[BaseMessage],
#         stop: Optional[List[str]] = None,
#         run_manager: Optional[CallbackManagerForLLMRun] = None,
#         **kwargs: Any,
#     ) -> ChatResult:
#         payload = {
#             "model": self.model,
#             "messages": self._to_api_messages(messages),
#             "stream": False,
#             "options": {
#                 "num_predict": self.max_tokens,
#             },
#         }

#         headers = {
#             "Content-Type": "application/json",
#             "Authorization": f"Bearer {self.api_key}",
#         }

#         logger.info("GPUServerChatModel → POST %s | model=%s", self.endpoint, self.model)

#         logger.info("Payload being sent: %s", json.dumps(payload, indent=2))

#         try:
#             resp = requests.post(
#                 self.endpoint,
#                 json=payload,
#                 headers=headers,
#                 verify=self.verify_ssl,
#                 timeout=self.timeout,
#             )
#             resp.raise_for_status()
#         except requests.exceptions.RequestException as exc:
#             logger.error("GPU server request failed: %s", exc)
#             raise RuntimeError(f"GPU server request failed: {exc}") from exc

#         data = resp.json()

#         # Parse Ollama-compatible response format:
#         # {"message": {"role": "assistant", "content": "..."}, ...}
#         try:
#             content = data["message"]["content"]
#         except (KeyError, TypeError) as exc:
#             logger.error("Unexpected GPU server response format: %s", data)
#             raise ValueError(f"Unexpected response format from GPU server: {data}") from exc

#         message = AIMessage(content=content)
#         generation = ChatGeneration(message=message)

#         logger.debug("GPUServerChatModel ← %d chars", len(content))
#         return ChatResult(generations=[generation])

#     # ---- Streaming generation ----------------------------------------------

#     def _stream(
#         self,
#         messages: List[BaseMessage],
#         stop: Optional[List[str]] = None,
#         run_manager: Optional[CallbackManagerForLLMRun] = None,
#         **kwargs: Any,
#     ) -> Iterator[ChatGenerationChunk]:
#         """
#         Streams tokens from the GPU server using Ollama's NDJSON streaming
#         format (stream: true).  Each line is a JSON object with a 'message'
#         key containing the delta content.
#         """
#         payload = {
#             "model": self.model,
#             "messages": self._to_api_messages(messages),
#             "stream": True,
#             "options": {
#                 "num_predict": self.max_tokens,
#                 "temperature": self.temperature,
#                 **({"stop": stop} if stop else {}),
#             },
#         }

#         headers = {
#             "Content-Type": "application/json",
#             "Authorization": f"Bearer {self.api_key}",
#         }

#         try:
#             with requests.post(
#                 self.endpoint,
#                 json=payload,
#                 headers=headers,
#                 verify=self.verify_ssl,
#                 timeout=self.timeout,
#                 stream=True,
#             ) as resp:
#                 resp.raise_for_status()
#                 for raw_line in resp.iter_lines():
#                     if not raw_line:
#                         continue
#                     import json
#                     try:
#                         chunk_data = json.loads(raw_line)
#                     except json.JSONDecodeError:
#                         continue

#                     delta = chunk_data.get("message", {}).get("content", "")
#                     if delta:
#                         chunk = ChatGenerationChunk(
#                             message=AIMessage(content=delta)
#                         )
#                         if run_manager:
#                             run_manager.on_llm_new_token(delta)
#                         yield chunk

#                     if chunk_data.get("done"):
#                         break

#         except requests.exceptions.RequestException as exc:
#             logger.error("GPU server streaming request failed: %s", exc)
#             raise RuntimeError(f"GPU server streaming failed: {exc}") from exc


# # ---------------------------------------------------------------------------
# # LLM type enum (kept for backwards compatibility)
# # ---------------------------------------------------------------------------

# class LLMType(Enum):
#     """Different LLM configurations for different use cases."""
#     FAST = "fast"
#     STANDARD = "standard"
#     COMPREHENSIVE = "comprehensive"
#     CREATIVE = "creative"
#     CODE = "code"


# # ---------------------------------------------------------------------------
# # Factory helpers — same public API as before, now backed by GPUServerChatModel
# # ---------------------------------------------------------------------------

# def _make_llm(**kwargs) -> GPUServerChatModel:
#     """Internal factory. Pass any GPUServerChatModel field overrides via kwargs."""
#     return GPUServerChatModel(**kwargs)


# def get_fast_llm() -> GPUServerChatModel:
#     """Get a fast LLM for quick responses (lower max_tokens)."""
#     return _make_llm(max_tokens=512, temperature=0.3)


# def get_standard_llm() -> GPUServerChatModel:
#     """Get a standard LLM for general use."""
#     return _make_llm()


# def get_comprehensive_llm() -> GPUServerChatModel:
#     """Get a comprehensive LLM for complex tasks (higher max_tokens)."""
#     return _make_llm(max_tokens=2048, temperature=0.5)


# def get_creative_llm() -> GPUServerChatModel:
#     """Get a creative LLM for reasoning and creative tasks."""
#     return _make_llm(max_tokens=1500, temperature=0.9)


# def get_code_llm() -> GPUServerChatModel:
#     """Get a code-focused LLM (low temperature for determinism)."""
#     return _make_llm(max_tokens=2048, temperature=0.1)


# def get_streaming_llm(
#     llm_type: LLMType = LLMType.STANDARD,
#     callbacks: Optional[List[BaseCallbackHandler]] = None,
# ) -> GPUServerChatModel:
#     """Get a streaming LLM with optional LangChain callbacks."""
#     llm = _make_llm()
#     if callbacks:
#         # Attach callbacks via the standard LangChain mechanism
#         llm = llm.configurable_fields()  # ensures fresh instance
#         return llm.with_config({"callbacks": callbacks})
#     return llm