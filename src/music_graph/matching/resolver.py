"""Cross-platform entity resolver — merges artists and tracks across platforms."""

import time
from collections import defaultdict

from loguru import logger
from rapidfuzz import fuzz
from sqlmodel import Session, delete, func, select

from music_graph.matching.normalize import normalize_name, normalize_track_title
from music_graph.models.artist import Artist, ArtistGenre, ArtistSource
from music_graph.models.matching import MatchCandidate, MatchMethod, MatchStatus
from music_graph.models.playlist import PlaylistTrack
from music_graph.models.track import Track, TrackArtist, TrackSource


class CrossPlatformResolver:
    """Resolves and merges entities that exist on multiple platforms.

    Uses normalized name matching (exact + fuzzy) to find duplicate artists
    and tracks across Deezer, SoundCloud, etc., then merges them into a
    single canonical entity.
    """

    def __init__(self, session: Session):
        self._session = session

    def resolve_artists(self, max_minutes: float = 15.0) -> dict[str, int]:
        """Resolve artist duplicates across platforms.

        Strategy:
            1. Index: normalized_name -> list[ArtistSource] grouped by platform
            2. Exact match: same normalized name across platforms -> auto-merge
            3. Fuzzy: token_sort_ratio for non-matched
               >= 90 -> auto-accept, 75-89 -> PENDING in match_candidate

        Args:
            max_minutes: Maximum time budget for this batch.

        Returns:
            Dict with counts: exact_merged, fuzzy_accepted, fuzzy_pending, skipped.
        """
        deadline = time.monotonic() + max_minutes * 60
        counts: dict[str, int] = {
            "exact_merged": 0,
            "fuzzy_accepted": 0,
            "fuzzy_pending": 0,
            "skipped": 0,
        }

        # Step 1: Build index of normalized_name -> {platform -> [ArtistSource]}
        all_sources = self._session.exec(select(ArtistSource)).all()
        name_index: dict[str, dict[str, list[ArtistSource]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for src in all_sources:
            norm = normalize_name(src.name)
            name_index[norm][src.platform.value].append(src)

        # Step 2: Exact matches — same normalized name, different platforms
        matched_artist_ids: set[str] = set()
        for norm_name, by_platform in name_index.items():
            if time.monotonic() > deadline:
                logger.info("Time budget exhausted during exact matching")
                break

            if len(by_platform) < 2:
                continue

            # Collect all unique artist_ids across platforms
            platform_artists: dict[str, list[str]] = {}
            for platform, sources in by_platform.items():
                platform_artists[platform] = list(
                    {s.artist_id for s in sources}
                )

            # Get all unique artist IDs
            all_ids: list[str] = []
            for ids in platform_artists.values():
                all_ids.extend(ids)
            unique_ids = list(dict.fromkeys(all_ids))

            if len(unique_ids) < 2:
                continue

            # Merge all into winner
            winner_id = self._pick_winner("artist", unique_ids)
            for loser_id in unique_ids:
                if loser_id == winner_id:
                    continue
                if loser_id in matched_artist_ids:
                    continue
                self._merge_artists(winner_id, loser_id)
                matched_artist_ids.add(loser_id)

                # Record accepted match
                self._session.add(
                    MatchCandidate(
                        entity_type="artist",
                        source_a_id=0,
                        source_b_id=0,
                        method=MatchMethod.EXACT,
                        confidence=1.0,
                        status=MatchStatus.ACCEPTED,
                        resolved_entity_id=winner_id,
                    )
                )
                counts["exact_merged"] += 1

            self._session.flush()

        self._session.commit()
        logger.info("Exact artist matches: {}", counts["exact_merged"])

        # Step 3: Fuzzy matching for remaining unmatched
        # Rebuild index after merges
        all_sources = self._session.exec(select(ArtistSource)).all()
        name_index_fresh: dict[str, dict[str, list[ArtistSource]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for src in all_sources:
            norm = normalize_name(src.name)
            name_index_fresh[norm][src.platform.value].append(src)

        # Collect single-platform entries for fuzzy comparison
        single_entries: list[tuple[str, str, str]] = []  # (norm_name, platform, artist_id)
        for norm_name, by_platform in name_index_fresh.items():
            for platform, sources in by_platform.items():
                artist_ids = list({s.artist_id for s in sources})
                for aid in artist_ids:
                    if aid not in matched_artist_ids:
                        single_entries.append((norm_name, platform, aid))

        # Group by platform for cross-platform comparison
        by_platform_entries: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for norm_name, platform, artist_id in single_entries:
            by_platform_entries[platform].append((norm_name, artist_id))

        platforms = list(by_platform_entries.keys())
        if len(platforms) >= 2:
            # Compare entries across different platforms
            for i in range(len(platforms)):
                for j in range(i + 1, len(platforms)):
                    if time.monotonic() > deadline:
                        logger.info("Time budget exhausted during fuzzy matching")
                        break

                    entries_a = by_platform_entries[platforms[i]]
                    entries_b = by_platform_entries[platforms[j]]

                    for norm_a, aid_a in entries_a:
                        if time.monotonic() > deadline:
                            break
                        if aid_a in matched_artist_ids:
                            continue

                        for norm_b, aid_b in entries_b:
                            if aid_b in matched_artist_ids:
                                continue
                            if aid_a == aid_b:
                                continue

                            score = fuzz.token_sort_ratio(norm_a, norm_b)

                            if score >= 90:
                                winner_id = self._pick_winner(
                                    "artist", [aid_a, aid_b]
                                )
                                loser_id = aid_b if winner_id == aid_a else aid_a
                                self._merge_artists(winner_id, loser_id)
                                matched_artist_ids.add(loser_id)
                                self._session.add(
                                    MatchCandidate(
                                        entity_type="artist",
                                        source_a_id=0,
                                        source_b_id=0,
                                        method=MatchMethod.FUZZY,
                                        confidence=score / 100.0,
                                        status=MatchStatus.ACCEPTED,
                                        resolved_entity_id=winner_id,
                                    )
                                )
                                counts["fuzzy_accepted"] += 1
                            elif score >= 75:
                                self._session.add(
                                    MatchCandidate(
                                        entity_type="artist",
                                        source_a_id=0,
                                        source_b_id=0,
                                        method=MatchMethod.FUZZY,
                                        confidence=score / 100.0,
                                        status=MatchStatus.PENDING,
                                        resolved_entity_id=None,
                                    )
                                )
                                counts["fuzzy_pending"] += 1

                    self._session.flush()

        self._session.commit()
        logger.info(
            "Artist resolution complete: {}",
            counts,
        )
        return counts

    def resolve_tracks(self, max_minutes: float = 15.0) -> dict[str, int]:
        """Resolve track duplicates for artists that are already matched.

        Only processes tracks whose artist has sources on multiple platforms.

        Args:
            max_minutes: Maximum time budget for this batch.

        Returns:
            Dict with counts: merged, pending, skipped.
        """
        deadline = time.monotonic() + max_minutes * 60
        counts: dict[str, int] = {"merged": 0, "pending": 0, "skipped": 0}

        # Find artists with sources on multiple platforms (already matched)
        cross_platform_artists = self._session.exec(
            select(ArtistSource.artist_id)
            .group_by(ArtistSource.artist_id)
            .having(func.count(func.distinct(ArtistSource.platform)) > 1)
        ).all()

        logger.info(
            "Found {} cross-platform artists for track resolution",
            len(cross_platform_artists),
        )

        merged_track_ids: set[str] = set()

        for artist_id in cross_platform_artists:
            if time.monotonic() > deadline:
                logger.info("Time budget exhausted during track resolution")
                break

            # Get all track sources for this artist's tracks
            track_artists = self._session.exec(
                select(TrackArtist).where(TrackArtist.artist_id == artist_id)
            ).all()

            track_ids = [ta.track_id for ta in track_artists]
            if not track_ids:
                continue

            # Get track sources grouped by platform
            sources_by_platform: dict[str, list[TrackSource]] = defaultdict(list)
            for tid in track_ids:
                if tid in merged_track_ids:
                    continue
                sources = self._session.exec(
                    select(TrackSource).where(TrackSource.track_id == tid)
                ).all()
                for s in sources:
                    sources_by_platform[s.platform.value].append(s)

            platforms = list(sources_by_platform.keys())
            if len(platforms) < 2:
                continue

            # Compare tracks across platforms
            for i in range(len(platforms)):
                for j in range(i + 1, len(platforms)):
                    srcs_a = sources_by_platform[platforms[i]]
                    srcs_b = sources_by_platform[platforms[j]]

                    for sa in srcs_a:
                        if sa.track_id in merged_track_ids:
                            continue
                        norm_a = normalize_track_title(sa.title)
                        track_a = self._session.get(Track, sa.track_id)

                        for sb in srcs_b:
                            if sb.track_id in merged_track_ids:
                                continue
                            if sa.track_id == sb.track_id:
                                continue

                            norm_b = normalize_track_title(sb.title)
                            title_score = fuzz.token_sort_ratio(norm_a, norm_b)
                            track_b = self._session.get(Track, sb.track_id)

                            dur_a = track_a.duration_ms if track_a else None
                            dur_b = track_b.duration_ms if track_b else None
                            dur_diff = (
                                abs(dur_a - dur_b)
                                if dur_a is not None and dur_b is not None
                                else None
                            )

                            auto_accept = False
                            if title_score >= 85 and dur_diff is not None and dur_diff < 5000:
                                auto_accept = True
                            elif title_score >= 75 and dur_diff is not None and dur_diff < 3000:
                                auto_accept = True

                            if auto_accept:
                                winner_id = self._pick_winner(
                                    "track", [sa.track_id, sb.track_id]
                                )
                                loser_id = (
                                    sb.track_id
                                    if winner_id == sa.track_id
                                    else sa.track_id
                                )
                                self._merge_tracks(winner_id, loser_id)
                                merged_track_ids.add(loser_id)
                                self._session.add(
                                    MatchCandidate(
                                        entity_type="track",
                                        source_a_id=sa.id or 0,
                                        source_b_id=sb.id or 0,
                                        method=MatchMethod.FUZZY,
                                        confidence=title_score / 100.0,
                                        status=MatchStatus.ACCEPTED,
                                        resolved_entity_id=winner_id,
                                    )
                                )
                                counts["merged"] += 1
                            elif title_score >= 85 and dur_diff is None:
                                self._session.add(
                                    MatchCandidate(
                                        entity_type="track",
                                        source_a_id=sa.id or 0,
                                        source_b_id=sb.id or 0,
                                        method=MatchMethod.FUZZY,
                                        confidence=title_score / 100.0,
                                        status=MatchStatus.PENDING,
                                        resolved_entity_id=None,
                                    )
                                )
                                counts["pending"] += 1

            self._session.flush()

        self._session.commit()
        logger.info("Track resolution complete: {}", counts)
        return counts

    def _merge_artists(self, winner_id: str, loser_id: str) -> None:
        """Merge loser artist into winner, re-linking all references.

        Handles composite PK conflicts by deleting conflicts first.
        """
        logger.debug("Merging artist {} -> {}", loser_id, winner_id)

        # 1. ArtistSource: re-link to winner
        self._session.exec(
            select(ArtistSource).where(ArtistSource.artist_id == loser_id)
        )
        for src in self._session.exec(
            select(ArtistSource).where(ArtistSource.artist_id == loser_id)
        ).all():
            src.artist_id = winner_id
            self._session.add(src)

        # 2. TrackArtist: handle PK conflicts (track_id, artist_id)
        loser_links = self._session.exec(
            select(TrackArtist).where(TrackArtist.artist_id == loser_id)
        ).all()
        winner_track_ids = set(
            row.track_id
            for row in self._session.exec(
                select(TrackArtist).where(TrackArtist.artist_id == winner_id)
            ).all()
        )
        for link in loser_links:
            if link.track_id in winner_track_ids:
                # Conflict: delete loser's link
                self._session.delete(link)
            else:
                link.artist_id = winner_id
                self._session.add(link)

        # 3. ArtistGenre: handle PK conflicts (artist_id, genre_id, platform)
        loser_genres = self._session.exec(
            select(ArtistGenre).where(ArtistGenre.artist_id == loser_id)
        ).all()
        winner_genre_keys = set(
            (row.genre_id, row.platform)
            for row in self._session.exec(
                select(ArtistGenre).where(ArtistGenre.artist_id == winner_id)
            ).all()
        )
        for ag in loser_genres:
            if (ag.genre_id, ag.platform) in winner_genre_keys:
                self._session.delete(ag)
            else:
                ag.artist_id = winner_id
                self._session.add(ag)

        self._session.flush()

        # 4. Delete loser artist
        loser = self._session.get(Artist, loser_id)
        if loser:
            self._session.delete(loser)

        self._session.flush()

    def _merge_tracks(self, winner_id: str, loser_id: str) -> None:
        """Merge loser track into winner, re-linking all references.

        Handles composite PK conflicts by deleting conflicts first.
        """
        logger.debug("Merging track {} -> {}", loser_id, winner_id)

        # 1. TrackSource: re-link to winner
        for src in self._session.exec(
            select(TrackSource).where(TrackSource.track_id == loser_id)
        ).all():
            src.track_id = winner_id
            self._session.add(src)

        # 2. PlaylistTrack: handle PK conflicts (playlist_id, track_id)
        loser_links = self._session.exec(
            select(PlaylistTrack).where(PlaylistTrack.track_id == loser_id)
        ).all()
        winner_playlist_ids = set(
            row.playlist_id
            for row in self._session.exec(
                select(PlaylistTrack).where(PlaylistTrack.track_id == winner_id)
            ).all()
        )
        for link in loser_links:
            if link.playlist_id in winner_playlist_ids:
                self._session.delete(link)
            else:
                link.track_id = winner_id
                self._session.add(link)

        # 3. TrackArtist: handle PK conflicts (track_id, artist_id)
        loser_tas = self._session.exec(
            select(TrackArtist).where(TrackArtist.track_id == loser_id)
        ).all()
        winner_artist_ids = set(
            row.artist_id
            for row in self._session.exec(
                select(TrackArtist).where(TrackArtist.track_id == winner_id)
            ).all()
        )
        for ta in loser_tas:
            if ta.artist_id in winner_artist_ids:
                self._session.delete(ta)
            else:
                ta.track_id = winner_id
                self._session.add(ta)

        # 4. Copy ISRC from loser to winner if winner lacks it
        winner_track = self._session.get(Track, winner_id)
        loser_track = self._session.get(Track, loser_id)
        if winner_track and loser_track:
            if not winner_track.isrc and loser_track.isrc:
                winner_track.isrc = loser_track.isrc
                self._session.add(winner_track)

        self._session.flush()

        # 5. Delete loser track
        if loser_track:
            self._session.delete(loser_track)

        self._session.flush()

    def _pick_winner(self, entity_type: str, ids: list[str]) -> str:
        """Pick the winner entity based on most references.

        For artists: most TrackArtist links.
        For tracks: most PlaylistTrack links.

        Args:
            entity_type: "artist" or "track".
            ids: List of entity IDs to compare.

        Returns:
            The ID of the winner.
        """
        best_id = ids[0]
        best_count = -1

        for eid in ids:
            if entity_type == "artist":
                count = self._session.exec(
                    select(func.count()).select_from(TrackArtist).where(
                        TrackArtist.artist_id == eid
                    )
                ).one()
            else:
                count = self._session.exec(
                    select(func.count()).select_from(PlaylistTrack).where(
                        PlaylistTrack.track_id == eid
                    )
                ).one()

            if count > best_count:
                best_count = count
                best_id = eid

        return best_id
