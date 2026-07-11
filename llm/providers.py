from __future__ import annotations

import logging
import time
from typing import List, Optional

import requests

from config.settings import get_settings

logger = logging.getLogger(__name__)
_LLM = get_settings().llm


class LLMProvider:
    def chat(self, messages: List[dict], timeout: Optional[int] = None) -> str:
        raise NotImplementedError

    def is_available(self) -> bool:
        raise NotImplementedError


class OpenRouterProvider(LLMProvider):
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        chat_timeout_seconds: Optional[int] = None,
        availability_timeout_seconds: Optional[int] = None,
    ):
        self.api_key = api_key or _LLM.openrouter_api_key
        self.model = model or _LLM.openrouter_model
        self.chat_timeout = chat_timeout_seconds or _LLM.request_timeout_seconds
        self.avail_timeout = availability_timeout_seconds or _LLM.openrouter_availability_timeout_seconds
        self.base_url = "https://openrouter.ai/api/v1"

        if not self.api_key:
            logger.warning(
                "[LLM] No API key configured. "
                "Set ROBOT_OPENROUTER_API_KEY env variable. "
                "Running in offline mode."
            )

    def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            r = requests.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.avail_timeout,
            )
            return r.status_code == 200
        except Exception as e:
            logger.error(f"[LLM] OpenRouter not reachable: {e}")
            return False

    def chat(self, messages: List[dict], timeout: Optional[int] = None) -> str:
        from llm.module import LLMModuleError

        if not self.api_key:
            raise LLMModuleError("[llm] OpenRouter API key not configured.")

        timeout = timeout or self.chat_timeout
        retries = 3
        last_exc = None

        for attempt in range(retries):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    json={"model": self.model, "messages": messages},
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=timeout,
                )

                if response.status_code == 429 or response.status_code >= 500:
                    wait = 2 ** attempt
                    logger.warning("[LLM] HTTP %d, retry %d/%d after %ds",
                                   response.status_code, attempt + 1, retries, wait)
                    time.sleep(wait)
                    continue

                if response.status_code != 200:
                    raise LLMModuleError(
                        f"[llm] OpenRouter returned {response.status_code}: {response.text[:200]}"
                    )

                content = (
                    response.json()
                    .get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )

                if not content:
                    raise LLMModuleError("[llm] Empty response from OpenRouter")

                return content

            except (requests.Timeout, requests.ConnectionError) as e:
                last_exc = e
                wait = 2 ** attempt
                logger.warning("[LLM] Attempt %d/%d failed: %s, retry in %ds",
                               attempt + 1, retries, type(e).__name__, wait)
                if attempt < retries - 1:
                    time.sleep(wait)
                continue
            except LLMModuleError:
                raise
            except Exception as e:
                raise LLMModuleError(f"[llm] Unexpected error: {e}") from e

        raise LLMModuleError(
            "[llm] OpenRouter unavailable after %d retries. "
            "Switching to offline mode." % retries
        )


class GeminiProvider(LLMProvider):
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self._api_key = api_key or _LLM.gemini_api_key
        self._model = model or _LLM.gemini_model

        if self._api_key:
            from google import genai
            self._client = genai.Client(api_key=self._api_key)
        else:
            self._client = None
            logger.warning(
                "[LLM] No Gemini API key configured. "
                "Set ROBOT_GEMINI_API_KEY env variable. "
                "Running in offline mode."
            )

    def is_available(self) -> bool:
        if not self._client:
            return False
        try:
            next(iter(self._client.models.list()))
            return True
        except Exception as e:
            logger.error(f"[LLM] Gemini not reachable: {e}")
            return False

    def chat(self, messages: List[dict], timeout: Optional[int] = None) -> str:
        from llm.module import LLMModuleError
        from google.genai import types

        if not self._client:
            raise LLMModuleError("[llm] Gemini API key not configured.")

        system_parts = []
        contents = []

        for msg in messages:
            if msg["role"] == "system":
                system_parts.append(msg["content"])
            elif msg["role"] == "user":
                contents.append({"role": "user", "parts": [{"text": msg["content"]}]})
            elif msg["role"] == "assistant":
                contents.append({"role": "model", "parts": [{"text": msg["content"]}]})

        config_kwargs = {}
        if system_parts:
            config_kwargs["system_instruction"] = "\n\n".join(system_parts)

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except Exception as e:
            raise LLMModuleError(f"[llm] Gemini API error: {e}") from e

        if not response.text:
            raise LLMModuleError("[llm] Empty response from Gemini")

        return response.text.strip()


def create_provider() -> LLMProvider:
    provider_name = _LLM.provider or "openrouter"
    if provider_name == "gemini":
        logger.info("[LLM] Provider: Gemini")
        logger.info("[LLM] Model: %s", _LLM.gemini_model)
        return GeminiProvider()
    logger.info("[LLM] Provider: OpenRouter")
    logger.info("[LLM] Model: %s", _LLM.openrouter_model)
    return OpenRouterProvider()
