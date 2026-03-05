"""Fuzzy string matching for track and artist names."""

from rapidfuzz import fuzz

from music_graph.config import load_settings


def match_score(title_a: str, artist_a: str, title_b: str, artist_b: str) -> float:
    """Compute a combined fuzzy match score for two track records.

    Returns a score between 0.0 and 1.0.
    """
    title_sim = fuzz.token_sort_ratio(title_a.lower(), title_b.lower()) / 100.0
    artist_sim = fuzz.token_sort_ratio(artist_a.lower(), artist_b.lower()) / 100.0
    # Weight title more than artist (60/40)
    return 0.6 * title_sim + 0.4 * artist_sim


def is_fuzzy_match(
    title_a: str,
    artist_a: str,
    title_b: str,
    artist_b: str,
    threshold: float | None = None,
) -> tuple[bool, float]:
    """Check if two tracks are a fuzzy match.

    Returns (is_match, confidence).
    """
    if threshold is None:
        settings = load_settings()
        threshold = settings.get("matching", {}).get("fuzzy_threshold", 85) / 100.0

    score = match_score(title_a, artist_a, title_b, artist_b)
    return score >= threshold, score
