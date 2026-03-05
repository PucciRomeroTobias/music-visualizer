"""MusicBrainz ID lookup for entity resolution."""

import musicbrainzngs
from loguru import logger

musicbrainzngs.set_useragent("music-graph", "0.1.0", "https://github.com/pucciromerotobias/music-visualizer")


def lookup_by_isrc(isrc: str) -> str | None:
    """Look up a MusicBrainz recording ID by ISRC.

    Returns the MusicBrainz recording ID or None if not found.
    """
    try:
        result = musicbrainzngs.get_recordings_by_isrc(isrc)
        recordings = result.get("isrc", {}).get("recording-list", [])
        if recordings:
            return recordings[0].get("id")
    except musicbrainzngs.WebServiceError as e:
        logger.debug("MusicBrainz ISRC lookup failed for {}: {}", isrc, e)
    return None


def lookup_artist(name: str) -> str | None:
    """Search MusicBrainz for an artist by name.

    Returns the MusicBrainz artist ID or None if not found.
    """
    try:
        result = musicbrainzngs.search_artists(artist=name, limit=1)
        artists = result.get("artist-list", [])
        if artists and int(artists[0].get("ext:score", 0)) >= 90:
            return artists[0].get("id")
    except musicbrainzngs.WebServiceError as e:
        logger.debug("MusicBrainz artist lookup failed for '{}': {}", name, e)
    return None
