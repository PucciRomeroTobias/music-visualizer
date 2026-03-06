"""Entity matcher orchestrator — resolves tracks/artists across platforms."""

from loguru import logger
from sqlmodel import Session, select

from music_graph.matching.fuzzy import is_fuzzy_match
from music_graph.matching.musicbrainz import lookup_by_isrc
from music_graph.models.matching import MatchCandidate, MatchMethod, MatchStatus
from music_graph.models.track import Track, TrackSource


class EntityMatcher:
    """Matches source records to canonical entities.

    .. deprecated::
        This class is O(N) over all tracks and does not scale. Use
        :class:`music_graph.matching.resolver.CrossPlatformResolver` instead,
        which uses indexed normalized-name lookups and batch processing with
        time budgets.

    Resolution order:
    1. Exact match by platform_id (same source)
    2. ISRC match across platforms
    3. MusicBrainz ID match
    4. Fuzzy title+artist match
    """

    def __init__(self, session: Session):
        self._session = session

    def find_or_create_track(self, source: TrackSource) -> Track:
        """Find an existing canonical track or create a new one.

        Tries matching in order: platform_id, ISRC, fuzzy.
        """
        # 1. Check if this exact source already exists
        existing = self._session.exec(
            select(TrackSource).where(
                TrackSource.platform == source.platform,
                TrackSource.platform_id == source.platform_id,
            )
        ).first()
        if existing:
            logger.debug(
                "Source already exists for {} {}", source.platform, source.platform_id
            )
            return existing.track

        # 2. Try ISRC match
        if source.track and source.track.isrc:
            isrc_match = self._session.exec(
                select(Track).where(Track.isrc == source.track.isrc)
            ).first()
            if isrc_match:
                logger.debug("ISRC match found for {}", source.track.isrc)
                source.track_id = isrc_match.id
                self._session.add(source)
                return isrc_match

        # 3. Try fuzzy match against existing tracks
        all_tracks = self._session.exec(select(Track)).all()
        for candidate in all_tracks:
            is_match, confidence = is_fuzzy_match(
                source.title,
                source.artist_name,
                candidate.canonical_title,
                candidate.canonical_artist_name,
            )
            if is_match:
                logger.debug(
                    "Fuzzy match ({:.2f}) for '{}' -> '{}'",
                    confidence,
                    source.title,
                    candidate.canonical_title,
                )
                # Record match candidate
                match = MatchCandidate(
                    entity_type="track",
                    source_a_id=source.id or 0,
                    source_b_id=0,
                    method=MatchMethod.FUZZY,
                    confidence=confidence,
                    status=MatchStatus.ACCEPTED,
                    resolved_entity_id=candidate.id,
                )
                self._session.add(match)
                source.track_id = candidate.id
                self._session.add(source)
                return candidate

        # 4. Create new canonical track
        track = Track(
            canonical_title=source.title,
            canonical_artist_name=source.artist_name,
            isrc=source.track.isrc if source.track else None,
        )
        self._session.add(track)
        self._session.flush()
        source.track_id = track.id
        self._session.add(source)
        logger.debug("Created new canonical track: '{}'", track.canonical_title)
        return track
