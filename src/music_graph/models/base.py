"""Base enums and shared model utilities."""

import enum


class SourcePlatform(str, enum.Enum):
    """Music platform source."""

    SPOTIFY = "spotify"
    DEEZER = "deezer"
    SOUNDCLOUD = "soundcloud"
    LASTFM = "lastfm"


class ArtistRole(str, enum.Enum):
    """Role of an artist on a track."""

    PRIMARY = "primary"
    FEATURED = "featured"
    REMIXER = "remixer"
