"""
Centralized LLM service for managing all LLM interactions across the application.

This module provides a factory pattern for creating and managing LLM instances,
making it easy to switch between different providers and configurations.
"""

# import logging
# from enum import Enum
# from typing import Optional, List

# from langchain_community.chat_models import ChatOllama
# from langchain.base_language import BaseLanguageModel
# from langchain.callbacks.base import BaseCallbackHandler
# from app.config import Config

# # Configure logging
# logger = logging.getLogger(__name__)

# OLLAMA_LLM_MODEL = Config.OLLAMA_LLM_MODEL

# class LLMType(Enum):
#     """Different LLM configurations for different use cases."""
#     FAST = "fast"           # Quick responses, lower cost
#     STANDARD = "standard"   # Balanced performance
#     COMPREHENSIVE = "comprehensive"  # High quality, complex tasks
#     CREATIVE = "creative"   # Creative and reasoning tasks
#     CODE = "code"          # Code generation and analysis

# # Convenience functions for common use cases
# def get_fast_llm() -> BaseLanguageModel:
#     """Get a fast LLM for quick responses."""
#     return ChatOllama(model = OLLAMA_LLM_MODEL)

# def get_standard_llm() -> BaseLanguageModel:
#     """Get a standard LLM for general use."""
#     return ChatOllama(model = OLLAMA_LLM_MODEL)

# def get_comprehensive_llm() -> BaseLanguageModel:
#     """Get a comprehensive LLM for complex tasks."""
#     return ChatOllama(model = OLLAMA_LLM_MODEL)

# def get_creative_llm() -> BaseLanguageModel:
#     """Get a creative LLM for reasoning and creative tasks."""
#     return ChatOllama(model = OLLAMA_LLM_MODEL)

# def get_code_llm() -> BaseLanguageModel:
#     """Get a code-focused LLM."""
#     return ChatOllama(model = OLLAMA_LLM_MODEL)

# def get_streaming_llm(llm_type: LLMType = LLMType.STANDARD, 
#                      callbacks: Optional[List[BaseCallbackHandler]] = None) -> BaseLanguageModel:
#     """Get a streaming LLM with callbacks."""
#     return ChatOllama(model = OLLAMA_LLM_MODEL, callbacks=callbacks)

import logging
import requests
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional
import json

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain.base_language import BaseLanguageModel
from langchain.callbacks.base import BaseCallbackHandler
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from app.core.config import settings

# Configure logging
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# GPU Server configuration (read once at import time)
# ---------------------------------------------------------------------------

GPU_SERVER_BASE_URL: str = settings.GPU_SERVER_BASE_URL
GPU_SERVER_API_KEY: str = settings.GPU_SERVER_API_KEY
GPU_SERVER_MODEL: str = settings.GPU_SERVER_MODEL
GPU_SERVER_DEFAULT_MAX_TOKENS: int = settings.GPU_SERVER_DEFAULT_MAX_TOKENS
GPU_SERVER_VERIFY_SSL: bool = settings.GPU_SERVER_VERIFY_SSL
GPU_SERVER_API_FORMAT: str = settings.GPU_SERVER_API_FORMAT  # "ollama" or "openai"

if settings.USE_LOCAL_LLM:
    CHAT_ENDPOINT = f"{settings.LOCAL_LLM_BASE_URL.rstrip('/')}/api/chat"
    _ACTIVE_MODEL = settings.LOCAL_LLM_MODEL
    _ACTIVE_API_KEY = ""
    _ACTIVE_VERIFY_SSL = True
    logger.warning(
        f"USE_LOCAL_LLM=true — routing LLM calls to local model "
        f"'{_ACTIVE_MODEL}' at {CHAT_ENDPOINT} instead of the GPU server"
    )
else:
    CHAT_ENDPOINT = settings.GPU_SERVER_CHAT_ENDPOINT or f"{GPU_SERVER_BASE_URL.rstrip('/')}/cdot/ollama2/api/chat"
    _ACTIVE_MODEL = GPU_SERVER_MODEL
    _ACTIVE_API_KEY = GPU_SERVER_API_KEY
    _ACTIVE_VERIFY_SSL = GPU_SERVER_VERIFY_SSL


# ---------------------------------------------------------------------------
# Custom LangChain-compatible chat model
# ---------------------------------------------------------------------------

class GPUServerChatModel(BaseChatModel):
    """
    LangChain-compatible wrapper around the internal GPU server's OpenAI-style
    /api/chat endpoint.  Supports both standard invoke() and streaming callbacks
    so it can be used as a drop-in replacement for ChatOllama / ChatOpenAI.

    Usage
    -----
    llm = GPUServerChatModel()
    response = llm.invoke("Explain time dilation")   # returns AIMessage
    text = response.content
    """

    # ---- Pydantic fields (LangChain v0.1+ uses pydantic v1 model) ----------
    model: str = _ACTIVE_MODEL
    api_key: str = _ACTIVE_API_KEY
    endpoint: str = CHAT_ENDPOINT
    max_tokens: int = GPU_SERVER_DEFAULT_MAX_TOKENS
    temperature: float = 0.7
    verify_ssl: bool = _ACTIVE_VERIFY_SSL
    timeout: int = 120          # seconds
    api_format: str = GPU_SERVER_API_FORMAT  # "ollama" or "openai"

    class Config:
        # Allow extra fields coming from parent without raising errors
        extra = "allow"

    # ---- Required BaseChatModel properties ---------------------------------

    @property
    def _llm_type(self) -> str:
        return "gpu_server_chat"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "endpoint": self.endpoint,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

    # ---- Message conversion helpers ----------------------------------------

    @staticmethod
    def _to_api_messages(messages: List[BaseMessage]) -> List[Dict[str, str]]:
        """Convert LangChain message objects → API payload messages list."""
        role_map = {
            HumanMessage: "user",
            AIMessage: "assistant",
            SystemMessage: "system",
        }
        result = []
        for msg in messages:
            role = role_map.get(type(msg), "user")
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            result.append({"role": role, "content": content})
        return result

    # ---- Core generation (non-streaming) -----------------------------------

    def _build_payload(self, messages: List[BaseMessage], stream: bool, stop: Optional[List[str]] = None) -> Dict[str, Any]:
        """Build request payload in either Ollama or OpenAI format."""
        base_messages = self._to_api_messages(messages)
        if self.api_format == "openai":
            payload: Dict[str, Any] = {
                "model": self.model,
                "messages": base_messages,
                "stream": stream,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
            }
            if stop:
                payload["stop"] = stop
        else:
            payload = {
                "model": self.model,
                "messages": base_messages,
                "stream": stream,
                "options": {
                    "num_predict": self.max_tokens,
                    "temperature": self.temperature,
                    **({"stop": stop} if stop else {}),
                },
            }
        return payload

    def _parse_content(self, data: Dict[str, Any]) -> str:
        """Extract assistant content from either Ollama or OpenAI response."""
        if self.api_format == "openai":
            try:
                return data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise ValueError(f"Unexpected OpenAI-format response: {data}") from exc
        else:
            try:
                return data["message"]["content"]
            except (KeyError, TypeError) as exc:
                raise ValueError(f"Unexpected Ollama-format response: {data}") from exc

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        payload = self._build_payload(messages, stream=False, stop=stop)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        logger.info("GPUServerChatModel → POST %s | model=%s | format=%s", self.endpoint, self.model, self.api_format)
        logger.info("Payload being sent: %s", json.dumps(payload, indent=2))

        try:
            resp = requests.post(
                self.endpoint,
                json=payload,
                headers=headers,
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            logger.error("GPU server request failed: %s", exc)
            raise RuntimeError(f"GPU server request failed: {exc}") from exc

        data = resp.json()
        try:
            content = self._parse_content(data)
        except ValueError:
            logger.error("Unexpected GPU server response format: %s", data)
            raise

        message = AIMessage(content=content)
        generation = ChatGeneration(message=message)
        logger.debug("GPUServerChatModel ← %d chars", len(content))
        return ChatResult(generations=[generation])

    # ---- Streaming generation ----------------------------------------------

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """
        Streams tokens from the GPU/inference server.
        Supports both Ollama NDJSON format and OpenAI SSE format (Cerebras, etc.).
        """
        payload = self._build_payload(messages, stream=True, stop=stop)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        try:
            with requests.post(
                self.endpoint,
                json=payload,
                headers=headers,
                verify=self.verify_ssl,
                timeout=self.timeout,
                stream=True,
            ) as resp:
                resp.raise_for_status()
                for raw_line in resp.iter_lines():
                    if not raw_line:
                        continue
                    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line

                    if self.api_format == "openai":
                        # OpenAI SSE format: "data: {...}" or "data: [DONE]"
                        if not line.startswith("data:"):
                            continue
                        payload_str = line[len("data:"):].strip()
                        if payload_str == "[DONE]":
                            break
                        try:
                            chunk_data = json.loads(payload_str)
                        except json.JSONDecodeError:
                            continue
                        delta = chunk_data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    else:
                        # Ollama NDJSON format: each line is a complete JSON object
                        try:
                            chunk_data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        delta = chunk_data.get("message", {}).get("content", "")
                        if chunk_data.get("done"):
                            break

                    if delta:
                        chunk = ChatGenerationChunk(message=AIMessage(content=delta))
                        if run_manager:
                            run_manager.on_llm_new_token(delta)
                        yield chunk

        except requests.exceptions.RequestException as exc:
            logger.error("GPU server streaming request failed: %s", exc)
            raise RuntimeError(f"GPU server streaming failed: {exc}") from exc



class IcarKnoChatModel(BaseChatModel):
    """
    LangChain-compatible wrapper around the live icarKno Internet API endpoint.
    Routes LLM invocations through the live icarKno backend service.
    """
    live_url: str = ""
    auth_token: str = ""
    session_id: str = ""
    timeout: int = 45

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        if not self.live_url:
            self.live_url = settings.ICARKNO_LIVE_URL or "https://qdocbackend.carnotresearch.com/api/v1/queries/ask"
        if not self.auth_token:
            self.auth_token = settings.ICARKNO_AUTH_TOKEN
        if not self.session_id:
            self.session_id = settings.ICARKNO_SESSION_ID or "20261002T032358"

    class Config:
        extra = "allow"

    @property
    def _llm_type(self) -> str:
        return "icarkno_chat"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {
            "live_url": self.live_url,
            "session_id": self.session_id,
        }

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        prompt_text = "\n".join([m.content if isinstance(m.content, str) else str(m.content) for m in messages])
        
        payload = {
            "session_id": self.session_id,
            "message": prompt_text,
            "context": "files",
            "mode": "contextual",
            "has_csv_or_xlsx": False
        }
        headers = {
            "Content-Type": "application/json"
        }
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        logger.info("IcarKnoChatModel → POST %s | session=%s", self.live_url, self.session_id)
        
        content = ""
        try:
            resp = requests.post(self.live_url, json=payload, headers=headers, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("answer") or data.get("response") or data.get("message") or ""
                if "upgrade your account" in content.lower():
                    logger.warning("icarKno live ask returned quota limit, falling back to live trial-ask endpoint")
                    content = ""
            if not content:
                trial_url = self.live_url.replace('/queries/ask', '/queries/trial-ask')
                trial_payload = {
                    "fingerprint": self.session_id,
                    "message": prompt_text,
                    "filenames": []
                }
                trial_resp = requests.post(trial_url, json=trial_payload, timeout=self.timeout)
                if trial_resp.status_code == 200:
                    data = trial_resp.json()
                    content = data.get("answer") or data.get("response") or data.get("message") or ""
                else:
                    raise RuntimeError(f"icarKno trial-ask returned status {trial_resp.status_code}")
        except Exception as exc:
            logger.error("icarKno request failed: %s", exc)
            raise RuntimeError(f"icarKno API request failed: {exc}") from exc

        message = AIMessage(content=content)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        result = self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
        content = result.generations[0].message.content
        if run_manager and content:
            run_manager.on_llm_new_token(content)
        yield ChatGenerationChunk(message=AIMessage(content=content))


# ---------------------------------------------------------------------------
# LLM type enum (kept for backwards compatibility)
# ---------------------------------------------------------------------------

class LLMType(Enum):
    """Different LLM configurations for different use cases."""
    FAST = "fast"
    STANDARD = "standard"
    COMPREHENSIVE = "comprehensive"
    CREATIVE = "creative"
    CODE = "code"


# ---------------------------------------------------------------------------
# Factory helpers — same public API as before, now backed by GPUServerChatModel
# ---------------------------------------------------------------------------

def _make_llm(**kwargs) -> BaseChatModel:
    """
    Universal internal factory supporting ANY LLM provider.
    
    Supported providers via settings.LLM_PROVIDER or environment flags:
    - 'groq': Groq hosted models (via ChatGroq)
    - 'nvidia': NVIDIA NIM hosted models (via ChatOpenAI)
    - 'openai': Official OpenAI models or custom OpenAI endpoints (via ChatOpenAI)
    - 'gemini' / 'google': Google Gemini models
    - 'anthropic' / 'claude': Anthropic Claude models
    - 'mistral': Mistral AI models
    - 'ollama': Local Ollama models (via ChatOllama)
    - 'custom': Generic OpenAI-compatible endpoints (vLLM, LM Studio, OpenRouter, etc.)
    - 'icarkno' / 'icarnko': Live icarKno Internet API (via IcarKnoChatModel)
    - 'gpu_server': Internal GPU server (via GPUServerChatModel)
    """
    common_kwargs = {}
    if "max_tokens" in kwargs:
        common_kwargs["max_tokens"] = kwargs["max_tokens"]
    if "temperature" in kwargs:
        common_kwargs["temperature"] = kwargs["temperature"]

    provider = (settings.LLM_PROVIDER or "").lower().strip()

    if provider in ("icarkno", "icarnko"):
        logger.info("Initializing icarKno live integration provider")
        return IcarKnoChatModel(**kwargs)

    # Explicit provider selection or auto-detection
    if provider == "nvidia" or (not provider and settings.USE_NVIDIA):
        logger.info("Initializing NVIDIA LLM provider: %s", settings.NVIDIA_MODEL)
        return ChatOpenAI(
            model=settings.NVIDIA_MODEL,
            api_key=settings.NVIDIA_API_KEY,
            base_url=settings.NVIDIA_BASE_URL,
            **common_kwargs,
        )

    if provider == "groq" or (not provider and settings.USE_GROQ):
        logger.info("Initializing Groq LLM provider: %s", settings.GROQ_MODEL)
        return ChatGroq(
            model=settings.GROQ_MODEL,
            api_key=settings.GROQ_API_KEY,
            **common_kwargs,
        )

    if provider in ("openai", "custom") or (not provider and settings.OPENAI_API_KEY and not settings.USE_LOCAL_LLM):
        logger.info("Initializing OpenAI/Custom LLM provider: %s", settings.OPENAI_MODEL)
        openai_kwargs = {
            "model": settings.OPENAI_MODEL,
            "api_key": settings.OPENAI_API_KEY or "custom_key",
            **common_kwargs,
        }
        if settings.OPENAI_BASE_URL:
            openai_kwargs["base_url"] = settings.OPENAI_BASE_URL
        return ChatOpenAI(**openai_kwargs)

    if provider in ("anthropic", "claude"):
        logger.info("Initializing Anthropic/Claude LLM provider: %s", settings.ANTHROPIC_MODEL)
        try:
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=settings.ANTHROPIC_MODEL,
                api_key=settings.ANTHROPIC_API_KEY,
                **common_kwargs,
            )
        except ImportError:
            return ChatOpenAI(
                model=settings.ANTHROPIC_MODEL,
                api_key=settings.ANTHROPIC_API_KEY or "custom",
                base_url=settings.OPENAI_BASE_URL or "https://api.anthropic.com/v1",
                **common_kwargs,
            )

    if provider in ("gemini", "google"):
        logger.info("Initializing Gemini/Google LLM provider: %s", settings.GEMINI_MODEL)
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
            return ChatGoogleGenerativeAI(
                model=settings.GEMINI_MODEL,
                google_api_key=settings.GEMINI_API_KEY,
                **common_kwargs,
            )
        except ImportError:
            return ChatOpenAI(
                model=settings.GEMINI_MODEL,
                api_key=settings.GEMINI_API_KEY or "custom",
                base_url=settings.OPENAI_BASE_URL or "https://generativelanguage.googleapis.com/v1beta/openai",
                **common_kwargs,
            )

    if provider == "mistral":
        logger.info("Initializing Mistral LLM provider: %s", settings.MISTRAL_MODEL)
        return ChatOpenAI(
            model=settings.MISTRAL_MODEL,
            api_key=settings.MISTRAL_API_KEY or os.getenv("MISTRAL_API_KEY", ""),
            base_url="https://api.mistral.ai/v1",
            **common_kwargs,
        )

    if provider == "ollama" or (not provider and settings.USE_LOCAL_LLM):
        logger.info("Initializing Ollama LLM provider: %s", settings.OLLAMA_LLM_MODEL)
        try:
            from langchain_ollama import ChatOllama
            return ChatOllama(
                model=settings.OLLAMA_LLM_MODEL,
                base_url=settings.OLLAMA_BASE_URL,
                **common_kwargs,
            )
        except ImportError:
            from langchain_community.chat_models import ChatOllama
            return ChatOllama(
                model=settings.OLLAMA_LLM_MODEL,
                base_url=settings.OLLAMA_BASE_URL,
                **common_kwargs,
            )

    logger.info("Initializing GPUServerChatModel default provider")
    return GPUServerChatModel(**kwargs)


def get_fast_llm() -> BaseChatModel:
    """Get a fast LLM for quick responses (lower max_tokens)."""
    return _make_llm(max_tokens=512, temperature=0.3)


def get_standard_llm() -> BaseChatModel:
    """Get a standard LLM for general use."""
    return _make_llm()


def get_comprehensive_llm() -> BaseChatModel:
    """Get a comprehensive LLM for complex tasks (higher max_tokens)."""
    return _make_llm(max_tokens=2048, temperature=0.5)


def get_creative_llm() -> BaseChatModel:
    """Get a creative LLM for reasoning and creative tasks."""
    return _make_llm(max_tokens=1500, temperature=0.9)


def get_code_llm() -> BaseChatModel:
    """Get a code-focused LLM (low temperature for determinism)."""
    return _make_llm(max_tokens=2048, temperature=0.1)


def get_streaming_llm(
    llm_type: LLMType = LLMType.STANDARD,
    callbacks: Optional[List[BaseCallbackHandler]] = None,
) -> BaseChatModel:
    """Get a streaming LLM with optional LangChain callbacks."""
    llm = _make_llm()
    if callbacks:
        # Attach callbacks via the standard LangChain mechanism
        llm = llm.configurable_fields()  # ensures fresh instance
        return llm.with_config({"callbacks": callbacks})
    return llm