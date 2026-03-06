"""Deezer collection pipeline — keyword search and ingest with artist details.

Designed for incremental batch execution:
- Commits after each playlist (resumable).
- Skips already-ingested playlists.
- Time-budgeted via max_minutes parameter.
- Fetches artist details for each track's artist_ids.
"""

import time

from loguru import logger
from sqlmodel import Session, select

from music_graph.collectors.base import RawPlaylist
from music_graph.collectors.deezer import DeezerCollector
from music_graph.models.base import SourcePlatform
from music_graph.models.playlist import Playlist
from music_graph.pipeline.collect import Ingester


def _time_remaining(start: float, max_seconds: float) -> float:
    """Return seconds remaining in the current batch window."""
    return max_seconds - (time.monotonic() - start)


def _ingest_dz_playlist(
    session: Session,
    ingester: Ingester,
    collector: DeezerCollector,
    raw_pl: RawPlaylist,
    seen_artist_ids: set[str],
    summary: dict[str, int],
) -> None:
    """Ingest a single Deezer playlist with artist details lookup."""
    logger.info(
        "Ingesting playlist '{}' ({} tracks)",
        raw_pl.name,
        raw_pl.track_count,
    )

    try:
        raw_tracks = collector.get_playlist_tracks(raw_pl.platform_id)
    except Exception:
        logger.exception(
            "Failed to fetch tracks for playlist {}", raw_pl.platform_id
        )
        return

    playlist = ingester.ingest_playlist(raw_pl, depth=0)

    for pos, raw_track in enumerate(raw_tracks):
        track = ingester.ingest_track(
            raw_track, playlist_id=playlist.id, position=pos
        )
        summary["tracks_ingested"] += 1

        for artist_pid in raw_track.artist_ids:
            if artist_pid in seen_artist_ids:
                # Link existing artist to this track
                from music_graph.models.artist import ArtistSource

                existing_source = session.exec(
                    select(ArtistSource).where(
                        ArtistSource.platform == SourcePlatform.DEEZER,
                        ArtistSource.platform_id == artist_pid,
                    )
                ).first()
                if existing_source:
                    from music_graph.models.artist import Artist

                    artist = session.get(Artist, existing_source.artist_id)
                    if artist:
                        ingester.link_track_artist(track, artist)
                continue

            seen_artist_ids.add(artist_pid)

            try:
                raw_artist = collector.get_artist_details(artist_pid)
                artist = ingester.ingest_artist(raw_artist)
                ingester.link_track_artist(track, artist)
                summary["artists_ingested"] += 1
            except Exception:
                logger.exception("Failed to fetch artist {}", artist_pid)

    session.commit()
    summary["playlists_ingested"] += 1
    logger.info("Committed '{}' ({} tracks)", raw_pl.name, len(raw_tracks))


def search_and_collect_deezer(
    session: Session,
    keywords: list[str] | None = None,
    playlists_per_keyword: int = 25,
    max_minutes: float = 15.0,
) -> dict[str, int]:
    """Search Deezer playlists by keywords and ingest tracks with artist details.

    Uses seed keywords from config/seeds.toml if none provided.

    Args:
        session: SQLModel database session.
        keywords: Search terms. Falls back to seeds.toml keywords.
        playlists_per_keyword: Max playlists per keyword search.
        max_minutes: Maximum batch duration in minutes.

    Returns:
        Summary dict with collection stats.
    """
    max_seconds = max_minutes * 60
    batch_start = time.monotonic()
    collector = DeezerCollector()
    ingester = Ingester(session)

    if keywords is None:
        from music_graph.config import load_seeds

        seeds = load_seeds()
        keywords = seeds.get("keywords", {}).get("search_terms", [])

    summary: dict[str, int] = {
        "keywords_searched": 0,
        "playlists_found": 0,
        "playlists_ingested": 0,
        "tracks_ingested": 0,
        "artists_ingested": 0,
        "timed_out": 0,
    }

    existing_pids = set(
        session.exec(
            select(Playlist.platform_id).where(
                Playlist.platform == SourcePlatform.DEEZER
            )
        ).all()
    )
    logger.info("Existing Deezer playlists to skip: {}", len(existing_pids))

    seen_artist_ids: set[str] = set()

    for keyword in keywords:
        if _time_remaining(batch_start, max_seconds) < 30:
            logger.info("Time budget reached, stopping search")
            summary["timed_out"] = 1
            break

        logger.info("Searching Deezer for '{}'", keyword)
        summary["keywords_searched"] += 1

        try:
            raw_playlists = collector.search_playlists(
                keyword, limit=playlists_per_keyword
            )
        except Exception:
            logger.exception("Failed to search for '{}'", keyword)
            continue

        summary["playlists_found"] += len(raw_playlists)

        for raw_pl in raw_playlists:
            if _time_remaining(batch_start, max_seconds) < 30:
                logger.info("Time budget reached, stopping ingestion")
                summary["timed_out"] = 1
                break

            if raw_pl.platform_id in existing_pids:
                logger.debug("Skipping already-ingested playlist: {}", raw_pl.name)
                continue

            existing_pids.add(raw_pl.platform_id)
            _ingest_dz_playlist(
                session, ingester, collector, raw_pl, seen_artist_ids, summary
            )

    logger.info(
        "Deezer search collection done: {} keywords, {} playlists found, "
        "{} ingested, {} tracks, {} artists, timed_out={}",
        summary["keywords_searched"],
        summary["playlists_found"],
        summary["playlists_ingested"],
        summary["tracks_ingested"],
        summary["artists_ingested"],
        bool(summary["timed_out"]),
    )
    return summary
