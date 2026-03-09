"""Multi-provider LLM client with retry, backoff, and model fallback.

Supports Ollama (local), Gemini, and Groq. Ollama is preferred when
available — no rate limits, no API keys, runs on Apple Silicon.
"""

import os
import time

import requests
from loguru import logger

from music_graph.config import load_env

load_env()

OLLAMA_URL = "http://localhost:11434/api/chat"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Models ordered by preference.
# Ollama: no rate limits, local inference
# Gemini free tier: 2.5 Flash 10 RPM, 2.0 Flash 15 RPM
# Groq free tier: ~30 RPM
MODELS = [
    ("ollama", "gemma2:9b"),  # Local first — no rate limits
    ("gemini", "gemini-2.5-flash"),
    ("groq", "llama-3.3-70b-versatile"),
    ("gemini", "gemini-2.0-flash"),
    ("groq", "llama-3.1-8b-instant"),
    ("gemini", "gemini-2.0-flash-lite"),
]


def _ollama_available() -> bool:
    """Check if Ollama is running locally."""
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=2)
        return resp.status_code == 200
    except (requests.ConnectionError, requests.Timeout):
        return False


class LLMClient:
    """Multi-provider LLM client with round-robin fallback.

    Tries Ollama first (local, no rate limits), then falls back to
    Gemini and Groq APIs with exponential backoff between rounds.
    """

    def __init__(
        self,
        gemini_api_key: str | None = None,
        groq_api_key: str | None = None,
    ):
        self._gemini_key = gemini_api_key or os.environ.get("GOOGLE_API_KEY", "")
        self._groq_key = groq_api_key or os.environ.get("GROQ_API_KEY", "")
        self._session = requests.Session()

        # Check which providers are available
        ollama_ok = _ollama_available()

        self._models = [
            (provider, model)
            for provider, model in MODELS
            if (provider == "ollama" and ollama_ok)
            or (provider == "gemini" and self._gemini_key)
            or (provider == "groq" and self._groq_key)
        ]

        if not self._models:
            raise ValueError(
                "No LLM providers available. Start Ollama, or set "
                "GOOGLE_API_KEY / GROQ_API_KEY."
            )

        providers = {p for p, _ in self._models}
        logger.info(
            "LLM client initialized with {} models (providers: {})",
            len(self._models),
            ", ".join(sorted(providers)),
        )

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_rounds: int = 3,
        backoff: float = 10.0,
    ) -> str:
        """Send a prompt with round-robin model rotation and backoff.

        On rate limit, immediately tries the next model. Only backs off
        when ALL models have been rate-limited in a single round.
        Ollama never rate-limits, so if it's available it always works
        on the first try.

        Args:
            system_prompt: System instruction for the model.
            user_prompt: The user message to send.
            max_rounds: Max full rotations through all models.
            backoff: Backoff in seconds between rounds (doubles each round).

        Returns:
            The model's text response.

        Raises:
            RuntimeError: If all models and rounds are exhausted.
        """
        dead_models: set[int] = set()
        current_backoff = backoff

        for round_num in range(max_rounds):
            for i, (provider, model) in enumerate(self._models):
                if i in dead_models:
                    continue

                try:
                    return self._call(provider, model, system_prompt, user_prompt)
                except RateLimitError:
                    logger.warning(
                        "Rate limited on {} {}, trying next model",
                        provider, model,
                    )
                except APIError as e:
                    logger.error("API error on {} {}: {}", provider, model, e)
                    dead_models.add(i)

            if round_num < max_rounds - 1:
                logger.warning(
                    "All models rate-limited (round {}), backing off {}s",
                    round_num + 1, current_backoff,
                )
                time.sleep(current_backoff)
                current_backoff *= 2

        raise RuntimeError("All LLM models exhausted after retries")

    def _call(
        self, provider: str, model: str, system_prompt: str, user_prompt: str
    ) -> str:
        """Dispatch to the right provider."""
        if provider == "ollama":
            return self._call_ollama(model, system_prompt, user_prompt)
        elif provider == "gemini":
            return self._call_gemini(model, system_prompt, user_prompt)
        else:
            return self._call_groq(model, system_prompt, user_prompt)

    def _call_ollama(
        self, model: str, system_prompt: str, user_prompt: str
    ) -> str:
        """Make a single API call to Ollama (local)."""
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {"temperature": 0.1},
        }

        try:
            resp = self._session.post(OLLAMA_URL, json=payload, timeout=(5, 120))
        except (requests.ConnectionError, requests.Timeout):
            raise APIError("Ollama not reachable")

        if resp.status_code != 200:
            raise APIError(f"Ollama HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        content = data.get("message", {}).get("content", "")
        if not content:
            raise APIError(f"Empty response from Ollama: {data}")

        return content

    def _call_gemini(
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
            params={"key": self._gemini_key},
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

    def _call_groq(
        self, model: str, system_prompt: str, user_prompt: str
    ) -> str:
        """Make a single API call to Groq (OpenAI-compatible)."""
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 1024,
        }

        resp = self._session.post(
            GROQ_API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {self._groq_key}"},
            timeout=(10, 30),
        )

        if resp.status_code == 429:
            raise RateLimitError("Rate limited")
        if resp.status_code != 200:
            raise APIError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise APIError(f"No choices in response: {data}")

        return choices[0].get("message", {}).get("content", "")


# Backward-compatible alias
GeminiClient = LLMClient


class RateLimitError(Exception):
    """Raised when the API returns 429."""


class APIError(Exception):
    """Raised for non-retryable API errors."""
