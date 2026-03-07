"""Input filters — select which playlists feed the graph projection.

Runs before projection/graph construction. Each filter returns a set
of playlist IDs to include. Filters are composable: the intersection
of all active filters determines the final set.
"""

from sqlmodel import Session, select

from loguru import logger

from music_graph.models.playlist import Playlist


def filter_by_tier(
    session: Session,
    max_tier: int,
) -> set[str]:
    """Return playlist IDs with relevance_tier <= max_tier.

    Playlists with tier IS NULL are excluded (not yet evaluated).
    """
    rows = session.exec(
        select(Playlist.id, Playlist.relevance_tier)
    ).all()

    included = {pid for pid, tier in rows if tier is not None and tier <= max_tier}
    excluded = len(rows) - len(included)
    logger.info(
        "Input filter: tier <= {} → {} playlists included, {} excluded",
        max_tier, len(included), excluded,
    )
    return included


def get_playlist_ids(
    session: Session,
    max_tier: int | None = None,
) -> set[str] | None:
    """Apply all configured input filters and return allowed playlist IDs.

    Returns None if no filters are active (= use all playlists).
    """
    filters: list[set[str]] = []

    if max_tier is not None:
        filters.append(filter_by_tier(session, max_tier))

    if not filters:
        return None

    # Intersect all filter results
    result = filters[0]
    for f in filters[1:]:
        result &= f

    return result
