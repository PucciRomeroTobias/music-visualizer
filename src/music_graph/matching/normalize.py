"""Deterministic name normalization for cross-platform matching."""

import re
import unicodedata


# Noise words to strip from artist names
_ARTIST_NOISE = re.compile(
    r"\b(official|music|vevo|records|label)\b", re.IGNORECASE
)
_AUDIO_TAG = re.compile(
    r"\(?\b(official\s+(audio|video|lyric\s*video|visualizer))\b\)?",
    re.IGNORECASE,
)
_MULTI_SPACE = re.compile(r"\s{2,}")

# Track title noise
_TRACK_MIX_TAGS = re.compile(
    r"\(\s*(original\s+mix|radio\s+edit|extended\s+mix|club\s+mix)\s*\)",
    re.IGNORECASE,
)
_TRACK_PROMO_TAGS = re.compile(
    r"[\[\(]\s*(free\s*(dl|download)|out\s+now|premiere|bonus)\s*[\]\)]",
    re.IGNORECASE,
)


def _strip_diacritics(text: str) -> str:
    """Remove diacritical marks (accents) from text."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_name(name: str) -> str:
    """Normalize an artist name for deterministic matching.

    Steps: lowercase, strip, remove diacritics, remove noise words,
    normalize "dj" prefix, collapse whitespace.
    """
    text = name.lower().strip()
    text = _strip_diacritics(text)
    text = _AUDIO_TAG.sub("", text)
    text = _ARTIST_NOISE.sub("", text)
    # Normalize "dj" prefix variants: "dj.", "dj ", "d.j." -> "dj "
    text = re.sub(r"\bd\.?j\.?\s*", "dj ", text)
    text = _MULTI_SPACE.sub(" ", text).strip()
    return text


def normalize_track_title(title: str) -> str:
    """Normalize a track title for matching.

    Steps: lowercase, strip, remove mix/edit tags, remove promo tags,
    collapse whitespace.
    """
    text = title.lower().strip()
    text = _strip_diacritics(text)
    text = _TRACK_MIX_TAGS.sub("", text)
    text = _TRACK_PROMO_TAGS.sub("", text)
    text = _MULTI_SPACE.sub(" ", text).strip()
    return text
