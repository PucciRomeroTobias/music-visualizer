"""Database to co-occurrence matrix projections by node type."""

from collections import defaultdict

from loguru import logger
from sqlmodel import Session, select

from music_graph.models.artist import ArtistGenre
from music_graph.models.playlist import PlaylistTrack
from music_graph.models.track import TrackArtist


def _pairs_from_group(items: list[str]) -> list[tuple[str, str]]:
    """Generate all unique pairs from a list, sorted to avoid duplicates."""
    pairs = []
    items_sorted = sorted(items)
    for i in range(len(items_sorted)):
        for j in range(i + 1, len(items_sorted)):
            pairs.append((items_sorted[i], items_sorted[j]))
    return pairs


def project_track_cooccurrence(session: Session) -> dict[tuple[str, str], int]:
    """Build track co-occurrence from shared playlists.

    Edge between tracks if they appear in the same playlist.
    """
    logger.info("Projecting track co-occurrence...")

    # Group tracks by playlist
    playlist_tracks = session.exec(select(PlaylistTrack)).all()
    playlists: dict[str, list[str]] = defaultdict(list)
    for pt in playlist_tracks:
        playlists[pt.playlist_id].append(pt.track_id)

    cooccurrence: dict[tuple[str, str], int] = defaultdict(int)
    for playlist_id, track_ids in playlists.items():
        for pair in _pairs_from_group(track_ids):
            cooccurrence[pair] += 1

    logger.info(
        "Track projection: {} pairs from {} playlists",
        len(cooccurrence),
        len(playlists),
    )
    return dict(cooccurrence)


def project_artist_cooccurrence(
    session: Session,
    playlist_ids: set[str] | None = None,
) -> dict[tuple[str, str], int]:
    """Build artist co-occurrence from shared playlists.

    Edge between artists if their tracks appear in the same playlist.

    Args:
        session: Database session.
        playlist_ids: If set, only consider these playlists. None = all.
    """
    logger.info("Projecting artist co-occurrence...")

    # Get track -> artists mapping
    track_artists_rows = session.exec(select(TrackArtist)).all()
    track_to_artists: dict[str, set[str]] = defaultdict(set)
    for ta in track_artists_rows:
        track_to_artists[ta.track_id].add(ta.artist_id)

    # Group tracks by playlist
    playlist_tracks = session.exec(select(PlaylistTrack)).all()
    playlists: dict[str, set[str]] = defaultdict(set)
    for pt in playlist_tracks:
        if playlist_ids is not None and pt.playlist_id not in playlist_ids:
            continue
        for artist_id in track_to_artists.get(pt.track_id, set()):
            playlists[pt.playlist_id].add(artist_id)

    cooccurrence: dict[tuple[str, str], int] = defaultdict(int)
    for playlist_id, artist_ids in playlists.items():
        for pair in _pairs_from_group(list(artist_ids)):
            cooccurrence[pair] += 1

    logger.info(
        "Artist projection: {} pairs from {} playlists",
        len(cooccurrence),
        len(playlists),
    )
    return dict(cooccurrence)


def project_genre_cooccurrence(session: Session) -> dict[tuple[int, int], int]:
    """Build genre co-occurrence from shared artists.

    Edge between genres if they are assigned to the same artist.
    """
    logger.info("Projecting genre co-occurrence...")

    # Group genres by artist
    artist_genres = session.exec(select(ArtistGenre)).all()
    artists: dict[str, list[int]] = defaultdict(list)
    for ag in artist_genres:
        artists[ag.artist_id].append(ag.genre_id)

    cooccurrence: dict[tuple[int, int], int] = defaultdict(int)
    for artist_id, genre_ids in artists.items():
        for pair in _pairs_from_group(genre_ids):
            cooccurrence[pair] += 1

    logger.info(
        "Genre projection: {} pairs from {} artists",
        len(cooccurrence),
        len(artists),
    )
    return dict(cooccurrence)


# Mapping for easy dispatch
PROJECTIONS = {
    "track": project_track_cooccurrence,
    "artist": project_artist_cooccurrence,
    "genre": project_genre_cooccurrence,
}
