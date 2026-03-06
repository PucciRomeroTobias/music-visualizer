"""Bounce scene judge — evaluates playlists, artists, and matches."""

import json
from pathlib import Path

from loguru import logger

from music_graph.config import PROJECT_ROOT
from music_graph.judge.llm_client import GeminiClient


def _load_profile() -> str:
    """Load the bounce expert profile from config."""
    path = PROJECT_ROOT / "config" / "bounce_profile.md"
    if not path.exists():
        raise FileNotFoundError(f"Bounce profile not found: {path}")
    return path.read_text()


class BounceJudge:
    """LLM-based judge for bounce scene relevance.

    Uses the bounce_profile.md as system prompt and evaluates
    playlists, artists, and matches for genre relevance.
    """

    def __init__(self, client: GeminiClient | None = None):
        self._client = client or GeminiClient()
        self._profile = _load_profile()

    def evaluate_playlist(
        self,
        name: str,
        owner: str | None,
        tracks: list[dict],
    ) -> dict:
        """Evaluate if a playlist belongs to the bounce scene.

        Args:
            name: Playlist name.
            owner: Playlist owner/creator name.
            tracks: List of dicts with 'title' and 'artist' keys (sample).

        Returns:
            Dict with 'score' (0-10), 'dominated_by' (genre), 'dominated_by_tier'
            (1/2/3), and 'reason' (short explanation).
        """
        track_list = "\n".join(
            f"  - {t.get('artist', '?')} — {t.get('title', '?')}"
            for t in tracks[:15]
        )

        prompt = f"""Evaluate this playlist for relevance to the bounce/neo rave scene.

Playlist: "{name}"
Owner: {owner or "unknown"}
Track sample ({len(tracks)} shown):
{track_list}

Respond ONLY with a JSON object (no markdown, no explanation outside the JSON):
{{
  "score": <0-10, where 8-10 = tier 1 core bounce, 5-7 = tier 2 adjacent, 3-4 = tier 3 periphery, 0-2 = tier 4 reject>,
  "tier": <1-4>,
  "dominated_by": "<main genre you detect in this playlist>",
  "reason": "<one sentence explaining your score>"
}}"""

        raw = self._client.generate(self._profile, prompt)
        return self._parse_json(raw)

    def evaluate_artist(self, name: str, track_titles: list[str]) -> dict:
        """Evaluate if an artist belongs to the bounce scene.

        Args:
            name: Artist name.
            track_titles: Sample of track titles by this artist.

        Returns:
            Dict with 'tier' (1/2/3), 'genres' (list), and 'reason'.
        """
        tracks = "\n".join(f"  - {t}" for t in track_titles[:10])

        prompt = f"""Classify this artist's relevance to the bounce/neo rave scene.

Artist: "{name}"
Track titles:
{tracks}

Respond ONLY with a JSON object:
{{
  "tier": <1 = core bounce, 2 = adjacent, 3 = periphery, 4 = out of scope>,
  "genres": ["<detected genres for this artist>"],
  "reason": "<one sentence>"
}}"""

        raw = self._client.generate(self._profile, prompt)
        return self._parse_json(raw)

    def evaluate_match(
        self,
        name_a: str,
        platform_a: str,
        name_b: str,
        platform_b: str,
        context: str | None = None,
    ) -> dict:
        """Evaluate if two names refer to the same artist.

        Args:
            name_a: First artist name.
            platform_a: Platform of first artist.
            name_b: Second artist name.
            platform_b: Platform of second artist.
            context: Optional extra context (track titles, etc).

        Returns:
            Dict with 'same_artist' (bool), 'confidence' (0-1), and 'reason'.
        """
        prompt = f"""Are these the same artist?

Name A: "{name_a}" (from {platform_a})
Name B: "{name_b}" (from {platform_b})
{f"Context: {context}" if context else ""}

Respond ONLY with a JSON object:
{{
  "same_artist": <true or false>,
  "confidence": <0.0 to 1.0>,
  "reason": "<one sentence>"
}}"""

        raw = self._client.generate(self._profile, prompt)
        return self._parse_json(raw)

    def _parse_json(self, raw: str) -> dict:
        """Parse JSON from LLM response, handling markdown fences."""
        text = raw.strip()
        if text.startswith("```"):
            # Strip markdown code fences
            lines = text.split("\n")
            text = "\n".join(
                line for line in lines
                if not line.strip().startswith("```")
            )
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("Failed to parse judge response: {}", raw[:200])
            return {"error": "parse_failed", "raw": raw[:200]}
