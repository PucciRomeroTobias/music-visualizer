"""Expansion pipeline — discover more playlists via related artists.

Designed for incremental batch execution:
- Each phase persists progress to the database.
- Safe to interrupt and resume — skips already-processed items.
- Time-budgeted via max_minutes parameter.
"""

import time

from loguru import logger
from sqlmodel import Session, select, text

from music_graph.collectors.deezer import DeezerCollector
from music_graph.models.artist import Artist, ArtistSource
from music_graph.models.expand_candidate import CandidateStatus, ExpandCandidate
from music_graph.models.playlist import Playlist
from music_graph.pipeline.collect import Ingester


def _get_hub_artists(session: Session, min_playlists: int = 4) -> list[tuple[str, str, int]]:
    """Get artists that appear in many playlists (hub artists).

    Returns list of (artist_db_id, deezer_platform_id, playlist_count).
    """
    results = session.exec(text("""
        SELECT a.id, asrc.platform_id, COUNT(DISTINCT pt.playlist_id) as pl_count
        FROM artist a
        JOIN artist_source asrc ON asrc.artist_id = a.id
        JOIN track_artist ta ON ta.artist_id = a.id
        JOIN playlist_track pt ON pt.track_id = ta.track_id
        WHERE asrc.platform = 'DEEZER'
        GROUP BY a.id
        HAVING pl_count >= :min_pl
        ORDER BY pl_count DESC
    """).bindparams(min_pl=min_playlists)).all()

    return [(str(r[0]), str(r[1]), r[2]) for r in results]


def _time_left(start: float, max_seconds: float) -> float:
    """Return seconds remaining in the current batch window."""
    return max_seconds - (time.monotonic() - start)


def _phase1_discover_related(
    session: Session,
    collector: DeezerCollector,
    ingester: Ingester,
    min_playlists: int,
    batch_start: float,
    max_seconds: float,
) -> dict[str, str]:
    """Phase 1: Fetch related artists for hub artists. Already persists via ingest."""
    hubs = _get_hub_artists(session, min_playlists)
    logger.info("Found {} hub artists (>= {} playlists)", len(hubs), min_playlists)

    existing_artist_pids = set(
        session.exec(
            select(ArtistSource.platform_id).where(ArtistSource.platform == "DEEZER")
        ).all()
    )

    discovered: dict[str, str] = {}

    for db_id, deezer_pid, pl_count in hubs:
        if _time_left(batch_start, max_seconds) < 30:
            logger.info("Time budget reached during Phase 1")
            return discovered

        artist = session.get(Artist, db_id)
        logger.info("Fetching related for '{}' ({} playlists)", artist.canonical_name, pl_count)

        try:
            related = collector.get_related_artists(deezer_pid)
        except Exception:
            logger.exception("Failed to fetch related for {}", deezer_pid)
            continue

        for ra in related:
            if ra.platform_id not in existing_artist_pids:
                discovered[ra.platform_id] = ra.name
                ingester.ingest_artist(ra)
                existing_artist_pids.add(ra.platform_id)

        session.commit()

    logger.info("Phase 1 complete: {} new related artists from {} hubs", len(discovered), len(hubs))
    return discovered


def _phase2_search_candidates(
    session: Session,
    collector: DeezerCollector,
    discovered_artists: dict[str, str],
    playlists_per_artist: int,
    batch_start: float,
    max_seconds: float,
) -> int:
    """Phase 2: Search playlists for discovered artists, persist as ExpandCandidate rows.

    Returns count of new candidates stored.
    """
    existing_pids = set(
        session.exec(select(Playlist.platform_id)).all()
    )
    already_candidate_pids = set(
        session.exec(select(ExpandCandidate.playlist_platform_id)).all()
    )
    skip_pids = existing_pids | already_candidate_pids

    new_count = 0
    logger.info("Phase 2: Searching playlists for {} artists", len(discovered_artists))

    for i, (dpid, name) in enumerate(discovered_artists.items()):
        if _time_left(batch_start, max_seconds) < 60:
            logger.info("Time budget reached during Phase 2 at {}/{}", i, len(discovered_artists))
            return new_count

        if (i + 1) % 20 == 0:
            logger.info("Search progress: {}/{}, {} new candidates", i + 1, len(discovered_artists), new_count)

        try:
            playlists = collector.search_playlists(name, limit=playlists_per_artist)
        except Exception:
            continue

        for raw_pl in playlists:
            pid = raw_pl.platform_id
            if pid in skip_pids:
                continue
            skip_pids.add(pid)

            candidate = ExpandCandidate(
                playlist_platform_id=pid,
                playlist_name=raw_pl.name,
                status=CandidateStatus.PENDING,
                source_artist_pid=dpid,
                raw_playlist_json=raw_pl.raw_json,
            )
            session.add(candidate)
            new_count += 1

        # Commit every 50 artists to persist progress
        if (i + 1) % 50 == 0:
            session.commit()

    session.commit()
    logger.info("Phase 2 complete: {} new candidates stored", new_count)
    return new_count


def _phase3_probe_and_ingest(
    session: Session,
    collector: DeezerCollector,
    ingester: Ingester,
    min_overlap: int,
    batch_start: float,
    max_seconds: float,
) -> tuple[int, int]:
    """Phase 3+4 merged: Probe pending candidates and ingest qualified ones immediately.

    Returns (probed_count, ingested_count).
    """
    known_names = {
        name.lower().strip()
        for name in session.exec(select(Artist.canonical_name)).all()
    }
    logger.info("Loaded {} known artist names for overlap scoring", len(known_names))

    pending = session.exec(
        select(ExpandCandidate).where(ExpandCandidate.status == CandidateStatus.PENDING)
    ).all()
    logger.info("Phase 3+4: {} pending candidates to probe and ingest", len(pending))

    probed = 0
    ingested = 0
    seen_artists: set[str] = set()

    for i, candidate in enumerate(pending):
        if _time_left(batch_start, max_seconds) < 30:
            logger.info("Time budget reached during Phase 3+4 at {}/{}", i, len(pending))
            return probed, ingested

        if (i + 1) % 20 == 0:
            logger.info("Probe progress: {}/{}, {} ingested", i + 1, len(pending), ingested)

        pid = candidate.playlist_platform_id

        try:
            raw_tracks = collector.get_playlist_tracks(pid)
        except Exception:
            logger.exception("Failed to probe playlist {}", pid)
            continue

        overlap = sum(
            1 for rt in raw_tracks
            if rt.artist_name.lower().strip() in known_names
        )
        probed += 1

        if overlap < min_overlap:
            candidate.status = CandidateStatus.REJECTED
            candidate.overlap_score = overlap
            session.add(candidate)
            session.commit()
            continue

        # Qualified — ingest immediately
        candidate.status = CandidateStatus.QUALIFIED
        candidate.overlap_score = overlap
        session.add(candidate)

        logger.info("QUALIFIED: '{}' — {}/{} known artists", candidate.playlist_name, overlap, len(raw_tracks))

        from music_graph.collectors.base import RawPlaylist
        from music_graph.models.base import SourcePlatform

        raw_pl = RawPlaylist(
            platform=SourcePlatform.DEEZER,
            platform_id=pid,
            name=candidate.playlist_name,
            owner_name=candidate.raw_playlist_json.get("user", {}).get("name") if candidate.raw_playlist_json else None,
            track_count=len(raw_tracks),
            raw_json=candidate.raw_playlist_json or {},
        )

        ingester.ingest_playlist(raw_pl, depth=1)

        playlist = session.exec(
            select(Playlist).where(
                Playlist.platform_id == pid,
                Playlist.platform == collector.platform,
            )
        ).first()
        if not playlist:
            candidate.status = CandidateStatus.REJECTED
            session.commit()
            continue

        for pos, raw_track in enumerate(raw_tracks):
            track = ingester.ingest_track(raw_track, playlist_id=playlist.id, position=pos)

            for artist_pid in raw_track.artist_ids:
                if artist_pid in seen_artists:
                    continue
                seen_artists.add(artist_pid)
                try:
                    raw_artist = collector.get_artist_details(artist_pid)
                    artist = ingester.ingest_artist(raw_artist)
                    ingester.link_track_artist(track, artist)
                except Exception:
                    logger.exception("Failed to fetch artist {}", artist_pid)

        candidate.status = CandidateStatus.INGESTED
        session.add(candidate)
        session.commit()
        ingested += 1

        # Update known names with newly ingested artists
        known_names.update(name.lower().strip() for name in seen_artists)

        logger.info(
            "[{} ingested] '{}' (score={}, {} tracks)",
            ingested, candidate.playlist_name, overlap, len(raw_tracks),
        )

    logger.info("Phase 3+4 complete: {} probed, {} ingested", probed, ingested)
    return probed, ingested


def expand_via_related(
    session: Session,
    min_playlists: int = 4,
    playlists_per_artist: int = 5,
    min_overlap: int = 2,
    max_minutes: float = 15.0,
) -> dict[str, int]:
    """Expand the graph by discovering related artists and their playlists.

    Fully resumable across batches — all intermediate state persists in DB.
    Time-budgeted: stops cleanly within max_minutes.
    """
    max_seconds = max_minutes * 60
    batch_start = time.monotonic()
    collector = DeezerCollector()
    ingester = Ingester(session)

    summary = {
        "related_artists_discovered": 0,
        "candidates_stored": 0,
        "probed": 0,
        "ingested": 0,
        "timed_out": False,
    }

    # Phase 1: Discover related artists (already persists via DB)
    discovered = _phase1_discover_related(
        session, collector, ingester, min_playlists, batch_start, max_seconds,
    )
    summary["related_artists_discovered"] = len(discovered)

    if _time_left(batch_start, max_seconds) < 60:
        summary["timed_out"] = True
        logger.info("Batch done after Phase 1: {}", summary)
        return summary

    # Phase 2: Search and store candidates (persists to expand_candidate table)
    new_candidates = _phase2_search_candidates(
        session, collector, discovered, playlists_per_artist, batch_start, max_seconds,
    )
    summary["candidates_stored"] = new_candidates

    if _time_left(batch_start, max_seconds) < 60:
        summary["timed_out"] = True
        logger.info("Batch done after Phase 2: {}", summary)
        return summary

    # Phase 3+4: Probe pending candidates and ingest qualified ones
    probed, ingested = _phase3_probe_and_ingest(
        session, collector, ingester, min_overlap, batch_start, max_seconds,
    )
    summary["probed"] = probed
    summary["ingested"] = ingested

    if _time_left(batch_start, max_seconds) < 60:
        summary["timed_out"] = True

    logger.info("Expand batch complete: {}", summary)
    return summary
