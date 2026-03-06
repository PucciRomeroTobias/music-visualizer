"""SoundCloud collection pipeline — fetch and ingest with title parsing.

Designed for incremental batch execution:
- Commits after each playlist (resumable).
- Skips already-ingested playlists.
- Time-budgeted via max_minutes parameter.
"""

import time

import requests

from loguru import logger
from sqlmodel import Session, select

from music_graph.collectors.base import RawArtist, RawPlaylist, RawTrack
from music_graph.collectors.soundcloud import SoundCloudCollector
from music_graph.matching.normalize import normalize_name
from music_graph.matching.title_parser import parse_soundcloud_title
from music_graph.models.artist import Artist, ArtistSource
from music_graph.models.base import SourcePlatform
from music_graph.models.playlist import Playlist
from music_graph.models.track import Track, TrackSource
from music_graph.pipeline.collect import Ingester


def _time_remaining(start: float, max_seconds: float) -> float:
    """Return seconds remaining in the current batch window."""
    return max_seconds - (time.monotonic() - start)


def _ingest_sc_playlist(
    session: Session,
    ingester: Ingester,
    collector: SoundCloudCollector,
    raw_pl: RawPlaylist,
    seen_artist_keys: set[str],
    summary: dict[str, int],
) -> None:
    """Ingest a single SoundCloud playlist with title-parsed artists."""
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

        parsed = parse_soundcloud_title(
            raw_track.title, uploader_name=raw_track.artist_name
        )

        for artist_name in parsed.artists:
            if not artist_name:
                continue
            normalized = normalize_name(artist_name)
            artist_key = f"parsed:{normalized}"

            if artist_key in seen_artist_keys:
                existing_source = session.exec(
                    select(ArtistSource).where(
                        ArtistSource.platform == SourcePlatform.SOUNDCLOUD,
                        ArtistSource.platform_id == artist_key,
                    )
                ).first()
                if existing_source:
                    artist = session.get(Artist, existing_source.artist_id)
                    if artist:
                        ingester.link_track_artist(track, artist)
                continue

            seen_artist_keys.add(artist_key)

            raw_artist = RawArtist(
                platform=SourcePlatform.SOUNDCLOUD,
                platform_id=artist_key,
                name=artist_name,
            )
            artist = ingester.ingest_artist(raw_artist)
            ingester.link_track_artist(track, artist)
            summary["artists_parsed"] += 1

    session.commit()
    summary["playlists_ingested"] += 1
    logger.info("Committed '{}' ({} tracks)", raw_pl.name, len(raw_tracks))


def collect_soundcloud(
    session: Session,
    user_id: str,
    max_minutes: float = 15.0,
) -> dict[str, int]:
    """Collect playlists and tracks from a SoundCloud user.

    Args:
        session: SQLModel database session.
        user_id: SoundCloud user ID to collect from.
        max_minutes: Maximum batch duration in minutes.

    Returns:
        Summary dict with collection stats.
    """
    max_seconds = max_minutes * 60
    batch_start = time.monotonic()
    collector = SoundCloudCollector()
    ingester = Ingester(session)

    summary: dict[str, int] = {
        "playlists_found": 0,
        "playlists_ingested": 0,
        "tracks_ingested": 0,
        "artists_parsed": 0,
        "timed_out": 0,
    }

    existing_pids = set(
        session.exec(
            select(Playlist.platform_id).where(
                Playlist.platform == SourcePlatform.SOUNDCLOUD
            )
        ).all()
    )
    logger.info("Existing SoundCloud playlists to skip: {}", len(existing_pids))

    try:
        raw_playlists = collector.get_user_playlists(user_id)
    except Exception:
        logger.exception("Failed to fetch playlists for user {}", user_id)
        return summary

    summary["playlists_found"] = len(raw_playlists)
    logger.info("Found {} playlists for user {}", len(raw_playlists), user_id)

    seen_artist_keys: set[str] = set()

    for raw_pl in raw_playlists:
        if _time_remaining(batch_start, max_seconds) < 30:
            logger.info("Time budget reached, stopping collection")
            summary["timed_out"] = 1
            break

        if raw_pl.platform_id in existing_pids:
            logger.debug("Skipping already-ingested playlist: {}", raw_pl.name)
            continue

        _ingest_sc_playlist(
            session, ingester, collector, raw_pl, seen_artist_keys, summary
        )

    logger.info(
        "SoundCloud collection done: {} playlists ingested, {} tracks, {} artists, timed_out={}",
        summary["playlists_ingested"],
        summary["tracks_ingested"],
        summary["artists_parsed"],
        bool(summary["timed_out"]),
    )
    return summary


def search_and_collect_soundcloud(
    session: Session,
    keywords: list[str] | None = None,
    playlists_per_keyword: int = 25,
    max_minutes: float = 15.0,
) -> dict[str, int]:
    """Search SoundCloud playlists by keywords and ingest tracks.

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
    collector = SoundCloudCollector()
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
        "artists_parsed": 0,
        "timed_out": 0,
    }

    existing_pids = set(
        session.exec(
            select(Playlist.platform_id).where(
                Playlist.platform == SourcePlatform.SOUNDCLOUD
            )
        ).all()
    )
    logger.info("Existing SoundCloud playlists to skip: {}", len(existing_pids))

    seen_artist_keys: set[str] = set()

    for keyword in keywords:
        if _time_remaining(batch_start, max_seconds) < 30:
            logger.info("Time budget reached, stopping search")
            summary["timed_out"] = 1
            break

        logger.info("Searching SoundCloud for '{}'", keyword)
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
            _ingest_sc_playlist(
                session, ingester, collector, raw_pl, seen_artist_keys, summary
            )

    logger.info(
        "SoundCloud search collection done: {} keywords, {} playlists found, "
        "{} ingested, {} tracks, {} artists, timed_out={}",
        summary["keywords_searched"],
        summary["playlists_found"],
        summary["playlists_ingested"],
        summary["tracks_ingested"],
        summary["artists_parsed"],
        bool(summary["timed_out"]),
    )
    return summary


# User ID to skip (the user's own account, already collected separately)
_OWN_USER_ID = 296527166


def mine_artist_playlists_soundcloud(
    session: Session,
    max_minutes: float = 15.0,
) -> dict[str, int]:
    """Mine playlists from SoundCloud uploaders found in existing tracks.

    Extracts unique uploader user IDs from TrackSource raw_json, then
    fetches each uploader's playlists and ingests them.

    Args:
        session: SQLModel database session.
        max_minutes: Maximum batch duration in minutes.

    Returns:
        Summary dict with mining stats.
    """
    max_seconds = max_minutes * 60
    batch_start = time.monotonic()
    collector = SoundCloudCollector()
    ingester = Ingester(session)

    summary: dict[str, int] = {
        "uploaders_found": 0,
        "uploaders_processed": 0,
        "playlists_found": 0,
        "playlists_ingested": 0,
        "tracks_ingested": 0,
        "artists_parsed": 0,
        "uploaders_errored": 0,
        "timed_out": 0,
    }

    # Gather unique uploader user IDs from existing SC tracks
    sc_sources = session.exec(
        select(TrackSource.raw_json).where(
            TrackSource.platform == SourcePlatform.SOUNDCLOUD,
            TrackSource.raw_json.isnot(None),
        )
    ).all()

    uploader_ids: set[int] = set()
    for raw in sc_sources:
        if raw and isinstance(raw, dict):
            user_id = raw.get("user", {}).get("id")
            if user_id and user_id != _OWN_USER_ID:
                uploader_ids.add(int(user_id))

    summary["uploaders_found"] = len(uploader_ids)
    logger.info("Found {} unique SC uploaders to mine", len(uploader_ids))

    # Load existing playlist IDs to skip
    existing_pids = set(
        session.exec(
            select(Playlist.platform_id).where(
                Playlist.platform == SourcePlatform.SOUNDCLOUD
            )
        ).all()
    )
    logger.info("Existing SoundCloud playlists to skip: {}", len(existing_pids))

    seen_artist_keys: set[str] = set()

    for user_id in sorted(uploader_ids):
        if _time_remaining(batch_start, max_seconds) < 30:
            logger.info("Time budget reached, stopping mining")
            summary["timed_out"] = 1
            break

        logger.info("Mining playlists from uploader {}", user_id)

        try:
            raw_playlists = collector.get_user_playlists(str(user_id))
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in (403, 404):
                logger.warning(
                    "HTTP {} for uploader {}, skipping",
                    exc.response.status_code,
                    user_id,
                )
                summary["uploaders_errored"] += 1
                continue
            raise
        except Exception:
            logger.exception("Failed to fetch playlists for uploader {}", user_id)
            summary["uploaders_errored"] += 1
            continue

        summary["uploaders_processed"] += 1
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
            try:
                _ingest_sc_playlist(
                    session, ingester, collector, raw_pl, seen_artist_keys, summary
                )
            except Exception:
                logger.exception(
                    "Error ingesting playlist '{}', rolling back and continuing",
                    raw_pl.name,
                )
                session.rollback()

    logger.info(
        "SC artist mining done: {} uploaders ({} processed, {} errored), "
        "{} playlists found, {} ingested, {} tracks, timed_out={}",
        summary["uploaders_found"],
        summary["uploaders_processed"],
        summary["uploaders_errored"],
        summary["playlists_found"],
        summary["playlists_ingested"],
        summary["tracks_ingested"],
        bool(summary["timed_out"]),
    )
    return summary
