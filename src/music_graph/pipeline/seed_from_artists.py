"""Seed collection pipeline — genre keyword search filtered by SoundCloud artist overlap."""

import json
import time
from pathlib import Path

from loguru import logger
from sqlmodel import Session, select

from music_graph.collectors.deezer import DeezerCollector
from music_graph.models.playlist import Playlist
from music_graph.pipeline.collect import Ingester


def load_soundcloud_artists(path: Path) -> list[str]:
    """Load artist names from the SoundCloud extraction JSON."""
    with open(path) as f:
        data = json.load(f)
    return data.get("artists", [])


def _normalize_name(name: str) -> str:
    """Normalize artist name for fuzzy matching."""
    return name.lower().strip()


# Genre keywords to search on Deezer — these match the user's SoundCloud playlists
GENRE_KEYWORDS = [
    "bouncy techno",
    "bouncy trance",
    "bouncy house",
    "hard bounce",
    "uk bounce",
    "donk",
    "bouncy",
    "euro trance",
    "hard house",
    "acid techno bounce",
    "funky techno",
    "bouncy psy",
    "nrg bounce",
    "latin core",
    "trancecore",
    "hardstyle bounce",
    "neo trance",
]


def _time_remaining(start: float, max_seconds: float) -> float:
    """Return seconds remaining in the current batch window."""
    return max_seconds - (time.monotonic() - start)


def seed_from_artists(
    session: Session,
    artist_names: list[str],
    playlists_per_keyword: int = 25,
    min_overlap: int = 2,
    max_minutes: float = 15.0,
) -> dict[str, int]:
    """Search Deezer playlists by genre keywords, keep those with known artist overlap.

    Runs within a time budget (max_minutes). Returns a summary dict.

    Strategy:
    1. Search Deezer for playlists by genre keywords.
    2. Fetch tracks from each playlist.
    3. Score playlist by how many tracks are by known artists (from SoundCloud).
    4. Only ingest playlists with score >= min_overlap.
    """
    max_seconds = max_minutes * 60
    batch_start = time.monotonic()
    collector = DeezerCollector()
    ingester = Ingester(session)

    known_artists = {_normalize_name(n) for n in artist_names}
    logger.info("Loaded {} known artist names for matching", len(known_artists))

    # Get existing playlist IDs to skip (resumability)
    existing_pids = {pl for pl in session.exec(select(Playlist.platform_id)).all()}
    logger.info("Existing playlists to skip: {}", len(existing_pids))

    summary = {
        "candidates_found": 0,
        "playlists_qualified": 0,
        "playlists_ingested": 0,
        "timed_out": False,
    }

    # Phase 1: Search playlists by genre keywords
    candidate_playlists: dict[str, dict] = {}  # pid -> {raw_pl, keyword}

    logger.info(
        "Phase 1: Searching {} genre keywords on Deezer", len(GENRE_KEYWORDS)
    )

    for keyword in GENRE_KEYWORDS:
        if _time_remaining(batch_start, max_seconds) < 60:
            logger.info("Time budget reached during Phase 1")
            summary["timed_out"] = True
            break

        logger.info("Searching Deezer for '{}'", keyword)
        try:
            playlists = collector.search_playlists(
                keyword, limit=playlists_per_keyword
            )
        except Exception:
            logger.exception("Failed to search for '{}'", keyword)
            continue

        for raw_pl in playlists:
            pid = raw_pl.platform_id
            if pid in existing_pids:
                continue
            if pid not in candidate_playlists:
                candidate_playlists[pid] = {
                    "raw_pl": raw_pl,
                    "keywords": [keyword],
                }
            else:
                candidate_playlists[pid]["keywords"].append(keyword)

    summary["candidates_found"] = len(candidate_playlists)
    logger.info(
        "Phase 1 complete: {} unique candidate playlists", len(candidate_playlists)
    )

    if summary["timed_out"]:
        return summary

    # Phase 2: Probe each playlist for artist overlap
    logger.info("Phase 2: Probing playlists for artist overlap")

    qualified: list[tuple[str, int, list, dict]] = []  # (pid, score, tracks, info)

    for i, (pid, info) in enumerate(candidate_playlists.items()):
        raw_pl = info["raw_pl"]

        if _time_remaining(batch_start, max_seconds) < 60:
            logger.info("Time budget reached during Phase 2 at {}/{}", i, len(candidate_playlists))
            summary["timed_out"] = True
            break

        if (i + 1) % 20 == 0:
            logger.info(
                "Probing progress: {}/{}, {} qualified so far",
                i + 1,
                len(candidate_playlists),
                len(qualified),
            )

        try:
            raw_tracks = collector.get_playlist_tracks(pid)
        except Exception:
            logger.exception("Failed to probe playlist {}", pid)
            continue

        # Score: count tracks by known artists
        overlap = sum(
            1 for rt in raw_tracks
            if _normalize_name(rt.artist_name) in known_artists
        )

        if overlap >= min_overlap:
            qualified.append((pid, overlap, raw_tracks, info))
            logger.info(
                "QUALIFIED: '{}' — {}/{} known artists (keywords: {})",
                raw_pl.name,
                overlap,
                len(raw_tracks),
                ", ".join(info["keywords"]),
            )

    qualified.sort(key=lambda x: x[1], reverse=True)
    summary["playlists_qualified"] = len(qualified)

    logger.info(
        "Phase 2 complete: {}/{} playlists qualified (min_overlap={})",
        len(qualified),
        len(candidate_playlists),
        min_overlap,
    )

    if summary["timed_out"]:
        return summary

    # Phase 3: Ingest qualified playlists
    logger.info("Phase 3: Ingesting {} qualified playlists", len(qualified))

    seen_artists_ids: set[str] = set()

    for rank, (pid, score, raw_tracks, info) in enumerate(qualified):
        raw_pl = info["raw_pl"]

        if _time_remaining(batch_start, max_seconds) < 30:
            logger.info("Time budget reached during Phase 3 at {}/{}", rank, len(qualified))
            summary["timed_out"] = True
            break

        ingester.ingest_playlist(raw_pl, depth=0)

        logger.info(
            "[{}/{}] Ingesting '{}' (score={}, {} tracks)",
            rank + 1,
            len(qualified),
            raw_pl.name,
            score,
            len(raw_tracks),
        )

        playlist = session.exec(
            select(Playlist).where(
                Playlist.platform_id == pid,
                Playlist.platform == collector.platform,
            )
        ).first()
        if not playlist:
            continue

        for i, raw_track in enumerate(raw_tracks):
            track = ingester.ingest_track(
                raw_track, playlist_id=playlist.id, position=i
            )

            for artist_pid in raw_track.artist_ids:
                if artist_pid in seen_artists_ids:
                    continue
                seen_artists_ids.add(artist_pid)

                try:
                    raw_artist = collector.get_artist_details(artist_pid)
                    artist = ingester.ingest_artist(raw_artist)
                    ingester.link_track_artist(track, artist)
                except Exception:
                    logger.exception("Failed to fetch artist {}", artist_pid)

        session.commit()
        summary["playlists_ingested"] += 1
        logger.info("Committed '{}' ({} tracks)", raw_pl.name, len(raw_tracks))

    logger.info(
        "Done: {} playlists ingested, {} artists, timed_out={}",
        summary["playlists_ingested"],
        len(seen_artists_ids),
        summary["timed_out"],
    )

    return summary
