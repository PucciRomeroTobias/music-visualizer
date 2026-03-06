"""Parse SoundCloud track titles into structured artist + title components."""

import re
from dataclasses import dataclass, field


# Prefix patterns to strip before parsing
_PREFIX_PATTERNS = [
    re.compile(r"^premiere\s*:\s*", re.IGNORECASE),
    re.compile(r"^free\s+d(?:l|ownload)\s*[|:]\s*", re.IGNORECASE),
    re.compile(r"^\[[^\]]*\]\s*"),  # [Label Name]
]

# Suffix bracket patterns to strip
_SUFFIX_PATTERNS = [
    re.compile(
        r"\s*[\[\(]\s*(free\s*(dl|download)|out\s+now|premiere|bonus|"
        r"official\s+(audio|video))\s*[\]\)]\s*$",
        re.IGNORECASE,
    ),
]

# Collaboration separators (order matters: longer patterns first)
_COLLAB_SPLIT = re.compile(
    r"\s+(?:x|&|feat\.?|ft\.?|b2b|vs\.?)\s+", re.IGNORECASE
)

# Main title separators (artist - title)
_TITLE_SEPARATORS = [" - ", " – ", " — "]


@dataclass
class ParsedTitle:
    """Result of parsing a SoundCloud track title."""

    artists: list[str] = field(default_factory=list)
    title: str = ""
    is_parsed: bool = False


def parse_soundcloud_title(
    raw_title: str, uploader_name: str | None = None
) -> ParsedTitle:
    """Extract artist(s) and title from a SoundCloud track title.

    SoundCloud titles often follow the pattern "Artist - Track Title" or
    "Artist1 x Artist2 - Track Title (feat. Artist3)".

    Args:
        raw_title: The raw track title from SoundCloud.
        uploader_name: The uploader's display name as fallback artist.

    Returns:
        ParsedTitle with extracted artists and clean title.
    """
    text = raw_title.strip()

    # Strip prefixes
    for pattern in _PREFIX_PATTERNS:
        text = pattern.sub("", text)

    # Strip bracket suffixes
    for pattern in _SUFFIX_PATTERNS:
        text = pattern.sub("", text)

    text = text.strip()

    # Try splitting on title separators
    artist_part = None
    title_part = None
    for sep in _TITLE_SEPARATORS:
        if sep in text:
            idx = text.index(sep)
            artist_part = text[:idx].strip()
            title_part = text[idx + len(sep) :].strip()
            break

    if artist_part and title_part:
        # Extract featured artists from title part
        feat_artists: list[str] = []
        feat_match = re.search(
            r"\s*[\(\[]\s*(?:feat\.?|ft\.?)\s+(.+?)\s*[\)\]]",
            title_part,
            re.IGNORECASE,
        )
        if feat_match:
            feat_raw = feat_match.group(1)
            feat_artists = _split_artists(feat_raw)
            title_part = title_part[: feat_match.start()].strip()

        # Also check for inline feat in title (without brackets)
        inline_feat = re.search(
            r"\s+(?:feat\.?|ft\.?)\s+(.+)$", title_part, re.IGNORECASE
        )
        if inline_feat:
            feat_artists.extend(_split_artists(inline_feat.group(1)))
            title_part = title_part[: inline_feat.start()].strip()

        # Parse main artists (collaborations)
        main_artists = _split_artists(artist_part)

        all_artists = main_artists + feat_artists
        return ParsedTitle(
            artists=[a for a in all_artists if a],
            title=title_part,
            is_parsed=True,
        )

    # Fallback: uploader as artist, full text as title
    fallback_artist = uploader_name.strip() if uploader_name else ""
    return ParsedTitle(
        artists=[fallback_artist] if fallback_artist else [],
        title=text,
        is_parsed=False,
    )


def _split_artists(text: str) -> list[str]:
    """Split a string of collaborating artists into individual names."""
    parts = _COLLAB_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]
