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
    max_nodes and max_edges are performance budgets: if exceeded after
    initial filtering, min_degree is auto-increased until the graph fits.
    """

    # ── Edge construction (passed to build_graph) ─────────────
    min_cooccurrence: int = 2
    min_weight: float = 0.01

    # ── Performance budgets (auto-tighten filters to fit) ─────
    max_nodes: int | None = 4_000
    max_edges: int | None = 150_000

    # ── Post-construction node filters ────────────────────────
    min_degree: int = 3
    min_tracks: int = 0

    # ── Blocklist: non-artist entities (labels, magazines, junk) ──
    blocklist_names: list[str] = field(default_factory=lambda: [
        "djmag",
        "VERKNIPT",
        "BassTon",
        "CDj (Conor mulvihill)",
    ])


# ── Preset configurations ────────────────────────────────────────

PRESET_DEFAULT = VizFilterConfig()

PRESET_STRICT = VizFilterConfig(
    min_cooccurrence=3,
    min_tracks=2,
    max_nodes=3_000,
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


def _prune_low_degree(G: nx.Graph, min_degree: int) -> int:
    """Remove nodes with degree < min_degree iteratively until stable."""
    total_removed = 0
    while True:
        low_degree = [n for n, d in G.degree() if d < min_degree]
        if not low_degree:
            break
        G.remove_nodes_from(low_degree)
        total_removed += len(low_degree)
    return total_removed


def filter_graph(
    G: nx.Graph,
    config: VizFilterConfig,
    session: Session | None = None,
) -> nx.Graph:
    """Apply visualization filters to a built graph.

    If after initial filters the graph exceeds max_nodes or max_edges,
    min_degree is auto-increased until the graph fits within budget.

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

    # 0. Remove blocklisted entities (labels, magazines, junk accounts)
    if config.blocklist_names:
        blocklist_lower = {name.lower() for name in config.blocklist_names}
        blocked = [
            n for n in G.nodes()
            if G.nodes[n].get("label", "").lower() in blocklist_lower
        ]
        if blocked:
            G.remove_nodes_from(blocked)
            logger.info("Removed {} blocklisted entities", len(blocked))

    # 1. Remove artists with too few tracks
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

    # 2. Remove low-degree nodes (initial pass)
    effective_min_degree = config.min_degree
    if effective_min_degree > 0:
        removed = _prune_low_degree(G, effective_min_degree)
        if removed:
            logger.info(
                "Removed {} nodes with degree < {}",
                removed,
                effective_min_degree,
            )

    # 3. Auto-tighten: increase min_degree until within node budget
    if config.max_nodes and G.number_of_nodes() > config.max_nodes:
        logger.info(
            "Graph has {} nodes (budget {}), auto-tightening min_degree...",
            G.number_of_nodes(),
            config.max_nodes,
        )
        while G.number_of_nodes() > config.max_nodes:
            effective_min_degree += 1
            removed = _prune_low_degree(G, effective_min_degree)
            if removed == 0:
                break
        logger.info(
            "Auto-tightened min_degree to {} → {} nodes",
            effective_min_degree,
            G.number_of_nodes(),
        )

    # 4. Trim to top N edges by weight (after node pruning)
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

    logger.info(
        "Filters applied: {} → {} nodes, {} → {} edges",
        initial_nodes,
        G.number_of_nodes(),
        initial_edges,
        G.number_of_edges(),
    )

    return G
