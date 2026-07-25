"""
LLM Router & Failover Guard — Multi-provider LLM client with automatic failover.

Routes requests to primary provider (Gemini) and falls back to secondary (Groq)
on HTTP 429 (rate limit) or timeout errors. Logs all requests to llm_metrics.
"""

import os
import asyncio
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime

import httpx
from dotenv import load_dotenv

from core import database as db

load_dotenv()
logger = logging.getLogger(__name__)

# ── Provider Configurations ─────────────────────────────────────────

PROVIDER_ENDPOINTS = {
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "api_key_env": "GEMINI_API_KEY",
        "auth_type": "bearer",
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "api_key_env": "GROQ_API_KEY",
        "auth_type": "bearer",
    },
}

# Retry / timeout settings
REQUEST_TIMEOUT = 30.0
MAX_RETRIES = 2
RETRY_DELAY = 1.0


class LlmRouter:
    """
    Async LLM client with automatic failover between providers.

    Usage:
        router = LlmRouter(primary="gemini", primary_model="gemini-2.0-flash",
                            fallback="groq", fallback_model="llama3-70b-8192")
        response = await router.generate_response(messages)
    """

    def __init__(
        self,
        primary: str = "gemini",
        primary_model: str = "gemini-3.5-flash-lite",
        fallback: str = "groq",
        fallback_model: str = "llama3-70b-8192",
    ):
        self.primary = primary
        self.primary_model = primary_model
        self.fallback = fallback
        self.fallback_model = fallback_model
        self._client: Optional[httpx.AsyncClient] = None
        self._consecutive_failures = {primary: 0, fallback: 0}

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the shared HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    def _get_api_key(self, provider: str) -> Optional[str]:
        """Retrieve the API key for a provider from environment variables."""
        config = PROVIDER_ENDPOINTS.get(provider)
        if not config:
            return None
        return os.getenv(config["api_key_env"])

    def _build_headers(self, provider: str) -> Dict[str, str]:
        """Build request headers with authentication."""
        api_key = self._get_api_key(provider)
        if not api_key:
            raise ValueError(f"API key not found for provider: {provider} "
                             f"(set {PROVIDER_ENDPOINTS[provider]['api_key_env']})")
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    async def _call_provider(
        self, provider: str, model: str, messages: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Make a single API call to a provider.
        Returns the parsed response dict or raises on failure.
        """
        config = PROVIDER_ENDPOINTS.get(provider)
        if not config:
            raise ValueError(f"Unknown LLM provider: {provider}")

        headers = self._build_headers(provider)
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.8,
            "max_tokens": 512,
        }

        client = await self._get_client()

        try:
            response = await client.post(
                config["url"],
                headers=headers,
                json=payload,
            )

            # Log the metric
            tokens_used = None
            is_rate_limited = response.status_code == 429

            if response.status_code == 200:
                result = response.json()
                # Extract token usage if available
                usage = result.get("usage", {})
                tokens_used = usage.get("total_tokens")
                self._consecutive_failures[provider] = 0
            else:
                self._consecutive_failures[provider] += 1

            await db.log_llm_metric(
                provider=provider,
                status_code=response.status_code,
                tokens_used=tokens_used,
                is_rate_limited=is_rate_limited,
            )

            if is_rate_limited:
                raise RateLimitError(f"{provider} rate limited (429)")

            response.raise_for_status()
            return response.json()

        except httpx.TimeoutException:
            self._consecutive_failures[provider] += 1
            await db.log_llm_metric(
                provider=provider,
                status_code=408,
                is_rate_limited=False,
            )
            raise TimeoutError(f"{provider} request timed out")

    async def generate_response(
        self, messages: List[Dict[str, str]]
    ) -> str:
        """
        Generate a response from the LLM, with automatic failover.

        Args:
            messages: OpenAI-format messages array
                      [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, ...]

        Returns:
            The generated text response.
        """
        # Try primary provider first
        providers = [
            (self.primary, self.primary_model),
            (self.fallback, self.fallback_model),
        ]

        last_error = None
        for provider, model in providers:
            for attempt in range(MAX_RETRIES):
                try:
                    logger.info(f"LLM request to {provider}/{model} (attempt {attempt + 1})")
                    result = await self._call_provider(provider, model, messages)

                    # Extract the response text
                    choices = result.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "")
                        if content:
                            logger.info(
                                f"LLM response from {provider}: {len(content)} chars"
                            )
                            return content.strip()

                    raise ValueError("Empty response from LLM")

                except RateLimitError as e:
                    logger.warning(f"Rate limited by {provider}: {e}")
                    last_error = e
                    break  # Don't retry, go to fallback

                except (TimeoutError, httpx.HTTPStatusError) as e:
                    logger.warning(
                        f"Error from {provider} (attempt {attempt + 1}): {e}"
                    )
                    last_error = e
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY * (attempt + 1))

                except Exception as e:
                    logger.error(f"Unexpected error from {provider}: {e}")
                    last_error = e
                    break

        # All providers failed
        logger.error(f"All LLM providers failed. Last error: {last_error}")
        raise LlmRouterError(f"All LLM providers failed: {last_error}")

    def get_status(self) -> Dict[str, Any]:
        """Get the current status of the router for monitoring."""
        return {
            "primary": {
                "provider": self.primary,
                "model": self.primary_model,
                "consecutive_failures": self._consecutive_failures.get(self.primary, 0),
                "has_api_key": bool(self._get_api_key(self.primary)),
            },
            "fallback": {
                "provider": self.fallback,
                "model": self.fallback_model,
                "consecutive_failures": self._consecutive_failures.get(self.fallback, 0),
                "has_api_key": bool(self._get_api_key(self.fallback)),
            },
        }


# ── Custom Exceptions ───────────────────────────────────────────────

class RateLimitError(Exception):
    """Raised when an LLM provider returns HTTP 429."""
    pass


class LlmRouterError(Exception):
    """Raised when all LLM providers fail."""
    pass
