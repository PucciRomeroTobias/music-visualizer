"""Judged collection pipelines — LLM-filtered playlist ingestion.

Uses BounceJudge to evaluate playlists before ingesting.
Only playlists scoring tier 1-2 (score >= 5) get ingested.
Designed to run in parallel with other collection pipelines.
"""

import time

import requests
from loguru import logger
from sqlmodel import Session, select

from music_graph.collectors.base import RawPlaylist
from music_graph.collectors.deezer import DeezerCollector
from music_graph.collectors.soundcloud import SoundCloudCollector
from music_graph.judge.bounce_judge import BounceJudge
from music_graph.models.base import SourcePlatform
from music_graph.models.playlist import Playlist
from music_graph.pipeline.collect import Ingester
from music_graph.pipeline.collect_deezer import _ingest_dz_playlist
from music_graph.pipeline.collect_soundcloud import _ingest_sc_playlist


def _time_remaining(start: float, max_seconds: float) -> float:
    return max_seconds - (time.monotonic() - start)


# Expanded keywords covering the full bounce/neo rave spectrum
JUDGED_KEYWORDS = [
    # Core (tier 1)
    "bouncy techno",
    "bouncy trance",
    "hard bounce",
    "neo rave",
    "neo trance",
    "acid bounce",
    "bouncy psy",
    "hyper techno",
    # Adjacent (tier 2)
    "hardgroove",
    "hard house",
    "eurotrance",
    "latin core",
    "funky hard techno",
    "acid techno",
    "schranz",
    "hard trance",
    "makina",
    "trancecore",
    "pumping house",
    "hard dance",
    # Broader net (judge will filter)
    "rave techno 150bpm",
    "underground rave",
    "fast techno",
    "techno rave 2024",
    "techno rave 2025",
]

# Labels from bounce_profile.md
SC_LABELS = [
    "Ambra",
    "Polyamor Records",
    "Elemental Records",
    "MASS",
    "Molekül",
    "SPEED",
    "Reboot Records",
    "H33 Records",
    "ELOTRANCE",
    "Sachsentrance",
    "NEOTRANCE",
    "Nektar Records",
    "Bipolar Disorder Rec",
    "Groove Street Berlin",
    "GRS TECHNO",
    "OBSCUUR",
    "SYNTHX RECORDS",
    "POWERTRANCE",
    "Yeodel Rave",
    "EXILE TRAX",
    "Neon Dreams Cologne",
    "DEAD END",
    "Crimsonc9",
    "SONICFLUX",
    "GOTD",
]

# Wave 2: more labels/collectives from the scene + discovered in DB
SC_LABELS_WAVE2 = [
    # Labels/collectives from the bounce & neo rave scene
    "Throne Room Records",
    "Sopranos Bounce",
    "COUP",
    "Ramba Zamba Music",
    "VERKNIPT",
    "Beatroot Records",
    "TripleXL",
    "RAVE ALERT",
    "INITIALIZE",
    "unregular",
    "Deadly Alive",
    "NOTMYTYPE",
    "Need More Speed",
    "Selicato",
    "Taapion",
    "Sound Transitions",
    # Known bounce/neo rave labels not yet searched
    "Ritmo Fatale",
    "TNBN Records",
    "Exhausted Modern",
    "Kneaded Pains",
    "Rave Instinct",
    "Warehouse Rave",
    "Bounce Inc",
    "FCKNG SERIOUS",
    "Filth on Acid",
    "Hardgroove Records",
    "Toolroom Trax",
    "ÄVEM Records",
    "Voltage Records",
    "Bounce Heaven",
    "This Is Bounce UK",
    "Donk Records",
    "Sick Slaughterhouse",
    "Kuudos Records",
    "Possession",
    "DSNT",
    "Perc Trax",
]

# Wave 3: Artists from tobasso's "Bouncy Techno 2" playlist — mine their SC profiles
SC_ARTISTS_BOUNCY_TECHNO = [
    "ANDREASZ",
    "AREA ØNE",
    "Antonym",
    "Argot",
    "Bad Boombox",
    "Boys Noize",
    "Brutalismus 3000",
    "Caspii",
    "DJ GUESTLIST",
    "DJ Tallboy",
    "DXPE",
    "Doruksen",
    "ELON BASS",
    "Eskha",
    "Fenrick",
    "Funk Tribu",
    "Gonzi",
    "IOSIO",
    "JOKESONYOU",
    "Kichta",
    "L.zwo",
    "Linds",
    "Madpace",
    "Marlon Hoffstadt",
    "Mosmoz",
    "Noise Mafia",
    "Odymel",
    "Paraçek",
    "Part Time Killer",
    "Pegassi",
    "REVEX",
    "Tell Moore",
    "Vizionn",
    "davyboi",
    "t e s t p r e s s",
    "240 KM/H",
    "2HOT2PLAY",
    "Anwarr",
    "BIIANCO",
    "Cara Elizabeth",
    "Krl Mx",
    "LE B",
    "N00M1",
    "Nyco",
    "Saul High",
    "Shvdz",
    "Staffy",
    "THISO",
    "The Rocketman",
    "Uberjak'd",
    "Ueberrest",
    "Vespera",
]

MIN_SCORE = 5  # Tier 1-2 only


def _judge_playlist(
    judge: BounceJudge,
    raw_pl: RawPlaylist,
    tracks_sample: list[dict],
) -> dict:
    """Evaluate a playlist with BounceJudge. Returns judge result dict."""
    try:
        result = judge.evaluate_playlist(
            name=raw_pl.name,
            owner=raw_pl.owner_name,
            tracks=tracks_sample,
        )
        return result
    except Exception:
        logger.exception("Judge failed for '{}', skipping", raw_pl.name)
        return {"score": 0, "tier": 4, "reason": "judge_error"}


def _set_playlist_tier(session: Session, platform_id: str, platform: SourcePlatform, tier: int, genre: str | None) -> None:
    """Update relevance_tier on an existing playlist."""
    playlist = session.exec(
        select(Playlist).where(
            Playlist.platform_id == platform_id,
            Playlist.platform == platform,
        )
    ).first()
    if playlist:
        playlist.relevance_tier = tier
        playlist.relevance_genre = genre
        session.commit()


def judged_search_deezer(
    session: Session,
    keywords: list[str] | None = None,
    playlists_per_keyword: int = 25,
    max_minutes: float = 15.0,
) -> dict[str, int]:
    """Search Deezer with expanded keywords, filter via BounceJudge.

    Only ingests playlists scoring >= MIN_SCORE (tier 1-2).
    """
    max_seconds = max_minutes * 60
    batch_start = time.monotonic()
    collector = DeezerCollector()
    ingester = Ingester(session)
    judge = BounceJudge()

    if keywords is None:
        keywords = JUDGED_KEYWORDS

    summary: dict[str, int] = {
        "keywords_searched": 0,
        "playlists_found": 0,
        "playlists_judged": 0,
        "playlists_accepted": 0,
        "playlists_rejected": 0,
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

    seen_artist_ids: set[str] = set()

    for keyword in keywords:
        if _time_remaining(batch_start, max_seconds) < 60:
            summary["timed_out"] = 1
            break

        logger.info("Searching Deezer for '{}'", keyword)
        summary["keywords_searched"] += 1

        try:
            raw_playlists = collector.search_playlists(keyword, limit=playlists_per_keyword)
        except Exception:
            logger.exception("Search failed for '{}'", keyword)
            continue

        summary["playlists_found"] += len(raw_playlists)

        for raw_pl in raw_playlists:
            if _time_remaining(batch_start, max_seconds) < 60:
                summary["timed_out"] = 1
                break

            if raw_pl.platform_id in existing_pids:
                continue

            # Fetch tracks for judging
            try:
                raw_tracks = collector.get_playlist_tracks(raw_pl.platform_id)
            except Exception:
                logger.exception("Failed to fetch tracks for '{}'", raw_pl.name)
                continue

            # Build sample for judge
            tracks_sample = [
                {"artist": t.artist_name, "title": t.title}
                for t in raw_tracks[:15]
            ]

            # Judge
            result = _judge_playlist(judge, raw_pl, tracks_sample)
            summary["playlists_judged"] += 1
            score = result.get("score", 0)
            tier = result.get("tier", 4)
            genre = result.get("dominated_by")

            if score < MIN_SCORE:
                logger.info(
                    "REJECTED '{}' — score={}, tier={}, genre={}, reason={}",
                    raw_pl.name, score, tier, genre, result.get("reason", ""),
                )
                summary["playlists_rejected"] += 1
                continue

            logger.info(
                "ACCEPTED '{}' — score={}, tier={}, genre={}",
                raw_pl.name, score, tier, genre,
            )
            summary["playlists_accepted"] += 1

            existing_pids.add(raw_pl.platform_id)
            _ingest_dz_playlist(
                session, ingester, collector, raw_pl, seen_artist_ids, summary,
            )

            # Tag the playlist with tier
            _set_playlist_tier(session, raw_pl.platform_id, SourcePlatform.DEEZER, tier, genre)

    logger.info(
        "Judged Deezer search: {} keywords, {} found, {} judged, "
        "{} accepted, {} rejected, {} ingested, timed_out={}",
        summary["keywords_searched"],
        summary["playlists_found"],
        summary["playlists_judged"],
        summary["playlists_accepted"],
        summary["playlists_rejected"],
        summary["playlists_ingested"],
        bool(summary["timed_out"]),
    )
    return summary


def judged_search_sc_labels(
    session: Session,
    labels: list[str] | None = None,
    max_minutes: float = 15.0,
) -> dict[str, int]:
    """Search SoundCloud for known labels, download their playlists.

    Labels are high-signal — most will be relevant, but we still judge.
    """
    max_seconds = max_minutes * 60
    batch_start = time.monotonic()
    collector = SoundCloudCollector()
    ingester = Ingester(session)
    judge = BounceJudge()

    if labels is None:
        labels = SC_LABELS

    summary: dict[str, int] = {
        "labels_searched": 0,
        "users_found": 0,
        "playlists_found": 0,
        "playlists_judged": 0,
        "playlists_accepted": 0,
        "playlists_rejected": 0,
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

    seen_artist_keys: set[str] = set()

    for label_name in labels:
        if _time_remaining(batch_start, max_seconds) < 60:
            summary["timed_out"] = 1
            break

        logger.info("Searching SoundCloud for label '{}'", label_name)
        summary["labels_searched"] += 1

        try:
            users = collector.search_users(label_name, limit=5)
        except Exception:
            logger.exception("User search failed for '{}'", label_name)
            continue

        if not users:
            logger.info("No users found for '{}'", label_name)
            continue

        summary["users_found"] += len(users)

        for user in users:
            if _time_remaining(batch_start, max_seconds) < 60:
                summary["timed_out"] = 1
                break

            user_id = user["id"]
            username = user["username"]
            logger.info("Fetching playlists from '{}' ({})", username, user_id)

            try:
                raw_playlists = collector.get_user_playlists(str(user_id))
            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code in (403, 404):
                    logger.warning("HTTP {} for user {}", exc.response.status_code, user_id)
                    continue
                raise
            except Exception:
                logger.exception("Failed to fetch playlists for {}", user_id)
                continue

            summary["playlists_found"] += len(raw_playlists)

            for raw_pl in raw_playlists:
                if _time_remaining(batch_start, max_seconds) < 60:
                    summary["timed_out"] = 1
                    break

                if raw_pl.platform_id in existing_pids:
                    continue

                # Quick judge based on playlist name + owner (no track fetch yet)
                tracks_sample = []
                if raw_pl.raw_json:
                    for t in (raw_pl.raw_json.get("tracks") or [])[:15]:
                        title = t.get("title", "")
                        artist = t.get("user", {}).get("username", "")
                        if title:
                            tracks_sample.append({"artist": artist, "title": title})

                result = _judge_playlist(judge, raw_pl, tracks_sample)
                summary["playlists_judged"] += 1
                score = result.get("score", 0)
                tier = result.get("tier", 4)
                genre = result.get("dominated_by")

                if score < MIN_SCORE:
                    logger.info(
                        "REJECTED '{}' by '{}' — score={}, reason={}",
                        raw_pl.name, username, score, result.get("reason", ""),
                    )
                    summary["playlists_rejected"] += 1
                    continue

                logger.info(
                    "ACCEPTED '{}' by '{}' — score={}, tier={}",
                    raw_pl.name, username, score, tier,
                )
                summary["playlists_accepted"] += 1
                existing_pids.add(raw_pl.platform_id)

                try:
                    _ingest_sc_playlist(
                        session, ingester, collector, raw_pl, seen_artist_keys, summary,
                    )
                except Exception:
                    logger.exception("Error ingesting '{}', continuing", raw_pl.name)
                    session.rollback()

                _set_playlist_tier(session, raw_pl.platform_id, SourcePlatform.SOUNDCLOUD, tier, genre)

    logger.info(
        "SC label mining: {} labels, {} users, {} playlists found, "
        "{} judged, {} accepted, {} rejected, {} ingested, timed_out={}",
        summary["labels_searched"],
        summary["users_found"],
        summary["playlists_found"],
        summary["playlists_judged"],
        summary["playlists_accepted"],
        summary["playlists_rejected"],
        summary["playlists_ingested"],
        bool(summary["timed_out"]),
    )
    return summary


def _commit_with_retry(session: Session, max_retries: int = 5) -> None:
    """Commit with retry on SQLite busy/locked errors.

    Uses exponential backoff to avoid fighting with concurrent writers.
    """
    from sqlalchemy.exc import OperationalError

    for attempt in range(max_retries):
        try:
            session.commit()
            return
        except OperationalError as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                wait = 0.5 * (2 ** attempt)
                logger.warning(
                    "DB locked on commit (attempt {}), retrying in {:.1f}s",
                    attempt + 1, wait,
                )
                session.rollback()
                time.sleep(wait)
            else:
                raise


def judge_existing_playlists(
    session: Session,
    max_minutes: float = 15.0,
) -> dict[str, int]:
    """Judge existing playlists that don't have a relevance_tier yet.

    Does NOT delete anything — only sets relevance_tier and relevance_genre.
    Designed for concurrent use: uses short transactions and retries on lock.
    """
    max_seconds = max_minutes * 60
    batch_start = time.monotonic()
    judge = BounceJudge()

    summary: dict[str, int] = {
        "playlists_judged": 0,
        "tier_1": 0,
        "tier_2": 0,
        "tier_3": 0,
        "tier_4": 0,
        "timed_out": 0,
    }

    from music_graph.models.track import Track
    from music_graph.models.playlist import PlaylistTrack

    # Snapshot: grab IDs + metadata of unjudged playlists (short read)
    unjudged = session.exec(
        select(
            Playlist.id,
            Playlist.platform,
            Playlist.platform_id,
            Playlist.name,
            Playlist.owner_name,
            Playlist.track_count,
        )
        .where(Playlist.relevance_tier.is_(None))
        .order_by(Playlist.track_count.desc())
    ).all()

    logger.info("Found {} playlists to judge", len(unjudged))

    for pl_id, platform, platform_id, name, owner_name, track_count in unjudged:
        if _time_remaining(batch_start, max_seconds) < 10:
            summary["timed_out"] = 1
            break

        # Short read transaction: fetch track sample
        track_rows = session.exec(
            select(Track.canonical_title, Track.canonical_artist_name)
            .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
            .where(PlaylistTrack.playlist_id == pl_id)
            .limit(15)
        ).all()

        tracks_sample = [
            {"artist": artist or "?", "title": title or "?"}
            for title, artist in track_rows
        ]

        # LLM call (slow part — no DB lock held)
        result = _judge_playlist(
            judge,
            RawPlaylist(
                platform=platform,
                platform_id=platform_id,
                name=name,
                owner_name=owner_name,
                track_count=track_count,
            ),
            tracks_sample,
        )

        tier = result.get("tier", 4)
        genre = result.get("dominated_by")
        score = result.get("score", 0)

        # Short write transaction: update tier
        playlist = session.get(Playlist, pl_id)
        if playlist and playlist.relevance_tier is None:
            playlist.relevance_tier = tier
            playlist.relevance_genre = genre
            _commit_with_retry(session)

        summary["playlists_judged"] += 1
        summary[f"tier_{tier}"] = summary.get(f"tier_{tier}", 0) + 1

        logger.info(
            "[{}/{}] '{}' → tier {} (score={}, genre={})",
            summary["playlists_judged"],
            len(unjudged),
            name,
            tier,
            score,
            genre,
        )

    logger.info(
        "Judging done: {} judged — tier1={}, tier2={}, tier3={}, tier4={}, timed_out={}",
        summary["playlists_judged"],
        summary["tier_1"],
        summary["tier_2"],
        summary["tier_3"],
        summary["tier_4"],
        bool(summary["timed_out"]),
    )
    return summary
