"""Gemini LLM client with retry, backoff, and model fallback."""

import os
import time

import requests
from loguru import logger

# Models ordered by preference — Gemini free tier limits:
# 2.5 Flash: 10 RPM, 250K TPM, 500 req/day
# 2.0 Flash: 15 RPM, 1M TPM, 1500 req/day
# 1.5 Flash: 15 RPM, 1M TPM, 1500 req/day
MODELS = [
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiClient:
    """Gemini API client with exponential backoff and model fallback.

    Uses the REST API directly to avoid heavy SDK dependencies.
    Falls back through available models when rate limited.
    """

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("GOOGLE_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "GOOGLE_API_KEY not set. Get one at "
                "https://aistudio.google.com/apikey"
            )
        self._session = requests.Session()

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_retries: int = 3,
        initial_backoff: float = 2.0,
    ) -> str:
        """Send a prompt to Gemini with retry and model fallback.

        Args:
            system_prompt: System instruction for the model.
            user_prompt: The user message to send.
            max_retries: Max retries per model before falling back.
            initial_backoff: Initial backoff in seconds (doubles each retry).

        Returns:
            The model's text response.

        Raises:
            RuntimeError: If all models and retries are exhausted.
        """
        for model in MODELS:
            backoff = initial_backoff
            for attempt in range(max_retries):
                try:
                    return self._call(model, system_prompt, user_prompt)
                except RateLimitError:
                    if attempt < max_retries - 1:
                        logger.warning(
                            "Rate limited on {} (attempt {}), "
                            "backing off {}s",
                            model, attempt + 1, backoff,
                        )
                        time.sleep(backoff)
                        backoff *= 2
                    else:
                        logger.warning(
                            "Rate limited on {}, falling back to next model",
                            model,
                        )
                except APIError as e:
                    logger.error("API error on {}: {}", model, e)
                    break  # Non-retryable, try next model

        raise RuntimeError("All Gemini models exhausted after retries")

    def _call(
        self, model: str, system_prompt: str, user_prompt: str
    ) -> str:
        """Make a single API call to Gemini."""
        url = f"{GEMINI_API_URL}/{model}:generateContent"
        payload: dict = {
            "system_instruction": {
                "parts": [{"text": system_prompt}],
            },
            "contents": [
                {"role": "user", "parts": [{"text": user_prompt}]},
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 1024,
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }

        resp = self._session.post(
            url,
            json=payload,
            params={"key": self._api_key},
            timeout=(10, 30),
        )

        if resp.status_code == 429:
            raise RateLimitError("Rate limited")
        if resp.status_code != 200:
            raise APIError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise APIError(f"No candidates in response: {data}")

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            raise APIError(f"No parts in candidate: {candidates[0]}")

        return parts[0].get("text", "")


class RateLimitError(Exception):
    """Raised when the API returns 429."""


class APIError(Exception):
    """Raised for non-retryable API errors."""
