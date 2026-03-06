"""Pluggable graph filters for visualization export.

Defines a filter config and applies it to a NetworkX graph.
New filters (genre, platform, etc.) can be added to VizFilterConfig
without touching the rest of the pipeline.
"""

from collections import defaultdict
from dataclasses import dataclass, field

import networkx as nx
from loguru import logger
from sqlmodel import Session, select

from music_graph.models.track import TrackArtist


@dataclass
class VizFilterConfig:
    """Configuration for graph visualization filters.

    All filters are optional — defaults produce a reasonable visualization.
    """

    # ── Edge construction (passed to build_graph) ─────────────
    min_cooccurrence: int = 2
    min_weight: float = 0.01

    # ── Post-construction edge filters ────────────────────────
    max_edges: int | None = 50_000

    # ── Post-construction node filters ────────────────────────
    min_degree: int = 3
    min_tracks: int = 0


# ── Preset configurations ────────────────────────────────────────

PRESET_DEFAULT = VizFilterConfig()

PRESET_STRICT = VizFilterConfig(
    min_cooccurrence=3,
    min_tracks=2,
    max_edges=50_000,
    min_degree=3,
)


def get_artist_track_counts(session: Session) -> dict[str, int]:
    """Get number of tracks per artist from the DB."""
    rows = session.exec(select(TrackArtist)).all()
    counts: dict[str, int] = defaultdict(int)
    for ta in rows:
        counts[ta.artist_id] += 1
    return counts


def filter_graph(
    G: nx.Graph,
    config: VizFilterConfig,
    session: Session | None = None,
) -> nx.Graph:
    """Apply visualization filters to a built graph.

    Args:
        G: NetworkX graph (modified in-place for node removal,
           new graph returned for edge trimming).
        config: Filter configuration.
        session: DB session, required if config uses DB-dependent
                 filters (e.g. min_tracks).

    Returns:
        Filtered graph.
    """
    initial_nodes = G.number_of_nodes()
    initial_edges = G.number_of_edges()

    # 1. Trim to top N edges by weight
    if config.max_edges and G.number_of_edges() > config.max_edges:
        edges_sorted = sorted(
            G.edges(data=True),
            key=lambda e: e[2].get("weight", 0),
            reverse=True,
        )
        G_trimmed = nx.Graph()
        for u, v, d in edges_sorted[: config.max_edges]:
            G_trimmed.add_edge(u, v, **d)
        for node in G_trimmed.nodes():
            if node in G.nodes:
                G_trimmed.nodes[node].update(G.nodes[node])
        G = G_trimmed
        logger.info("Trimmed to top {} edges", config.max_edges)

    # 2. Remove artists with too few tracks
    if config.min_tracks > 0:
        if session is None:
            logger.warning(
                "min_tracks={} requires a DB session, skipping",
                config.min_tracks,
            )
        else:
            track_counts = get_artist_track_counts(session)
            low_tracks = [
                n for n in G.nodes() if track_counts.get(n, 0) < config.min_tracks
            ]
            G.remove_nodes_from(low_tracks)
            if low_tracks:
                logger.info(
                    "Removed {} nodes with < {} tracks",
                    len(low_tracks),
                    config.min_tracks,
                )

    # 3. Remove low-degree nodes (iterate until stable — removing nodes
    #    can reduce neighbors' degree below the threshold)
    if config.min_degree > 0:
        total_removed = 0
        while True:
            low_degree = [n for n, d in G.degree() if d < config.min_degree]
            if not low_degree:
                break
            G.remove_nodes_from(low_degree)
            total_removed += len(low_degree)
        if total_removed:
            logger.info(
                "Removed {} nodes with degree < {}",
                total_removed,
                config.min_degree,
            )

    logger.info(
        "Filters applied: {} → {} nodes, {} → {} edges",
        initial_nodes,
        G.number_of_nodes(),
        initial_edges,
        G.number_of_edges(),
    )

    return G
