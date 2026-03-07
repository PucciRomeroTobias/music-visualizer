"""Graph building pipeline — projection + weights + export."""

from collections import defaultdict
from pathlib import Path

import networkx as nx
from loguru import logger
from sqlmodel import Session, select

from music_graph.graph.edge_weights import ALGORITHMS
from music_graph.graph.export import EXPORTERS
from music_graph.graph.projections import PROJECTIONS
from music_graph.models.artist import Artist
from music_graph.models.genre import Genre
from music_graph.models.playlist import PlaylistTrack
from music_graph.models.track import Track, TrackArtist


def _compute_node_counts(
    session: Session, node_type: str
) -> tuple[dict, int]:
    """Compute how many contexts each node appears in.

    Returns (node_counts, total_contexts).
    """
    if node_type == "track":
        rows = session.exec(select(PlaylistTrack)).all()
        contexts: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            contexts[row.track_id].add(row.playlist_id)
        total = len({row.playlist_id for row in rows})
        return {k: len(v) for k, v in contexts.items()}, total

    elif node_type == "artist":
        pt_rows = session.exec(select(PlaylistTrack)).all()
        ta_rows = session.exec(select(TrackArtist)).all()
        track_to_artists: dict[str, set[str]] = defaultdict(set)
        for ta in ta_rows:
            track_to_artists[ta.track_id].add(ta.artist_id)

        contexts: dict[str, set[str]] = defaultdict(set)
        playlist_ids = set()
        for pt in pt_rows:
            playlist_ids.add(pt.playlist_id)
            for artist_id in track_to_artists.get(pt.track_id, set()):
                contexts[artist_id].add(pt.playlist_id)
        return {k: len(v) for k, v in contexts.items()}, len(playlist_ids)

    elif node_type == "genre":
        from music_graph.models.artist import ArtistGenre

        rows = session.exec(select(ArtistGenre)).all()
        contexts: dict[int, set[str]] = defaultdict(set)
        for row in rows:
            contexts[row.genre_id].add(row.artist_id)
        total = len({row.artist_id for row in rows})
        return {k: len(v) for k, v in contexts.items()}, total

    raise ValueError(f"Unknown node_type: {node_type}")


def _get_node_attributes(session: Session, node_type: str) -> dict:
    """Get display attributes for graph nodes."""
    attrs = {}
    if node_type == "track":
        for track in session.exec(select(Track)).all():
            attrs[track.id] = {
                "label": f"{track.canonical_title} - {track.canonical_artist_name}",
                "title": track.canonical_title,
                "artist": track.canonical_artist_name,
            }
    elif node_type == "artist":
        for artist in session.exec(select(Artist)).all():
            attrs[artist.id] = {
                "label": artist.canonical_name,
            }
    elif node_type == "genre":
        for genre in session.exec(select(Genre)).all():
            attrs[genre.id] = {
                "label": genre.name,
            }
    return attrs


def build_graph(
    session: Session,
    node_type: str = "track",
    algorithm: str = "jaccard",
    min_weight: float = 0.01,
    min_cooccurrence: int = 1,
    output_path: Path | None = None,
    export_format: str = "gexf",
    playlist_ids: set[str] | None = None,
) -> nx.Graph:
    """Build a weighted graph from the database.

    Args:
        session: Database session.
        node_type: "track", "artist", or "genre".
        algorithm: Weight algorithm name from ALGORITHMS.
        min_weight: Minimum edge weight to include.
        min_cooccurrence: Minimum raw co-occurrence count to consider.
        output_path: Path to export the graph (optional).
        export_format: Export format (gexf, graphml, json).

    Returns:
        The constructed NetworkX graph.
    """
    # 1. Project co-occurrence
    project_fn = PROJECTIONS.get(node_type)
    if project_fn is None:
        raise ValueError(
            f"Unknown node_type '{node_type}'. Options: {list(PROJECTIONS.keys())}"
        )
    # Pass playlist_ids filter to projection if supported
    if playlist_ids is not None and node_type == "artist":
        cooccurrence_raw = project_fn(session, playlist_ids=playlist_ids)
    else:
        cooccurrence_raw = project_fn(session)

    # Filter by minimum co-occurrence count
    cooccurrence = {
        pair: count
        for pair, count in cooccurrence_raw.items()
        if count >= min_cooccurrence
    }

    if not cooccurrence:
        logger.warning("No co-occurrence data for node_type '{}'", node_type)
        return nx.Graph()

    # 2. Compute node counts for weight algorithms that need them
    node_counts, total_contexts = _compute_node_counts(session, node_type)

    # 3. Apply weight algorithm
    algo_cls = ALGORITHMS.get(algorithm)
    if algo_cls is None:
        raise ValueError(
            f"Unknown algorithm '{algorithm}'. Options: {list(ALGORITHMS.keys())}"
        )
    algo = algo_cls()
    weights = algo.compute(cooccurrence, node_counts, total_contexts)

    # 4. Build graph with threshold filter
    G = nx.Graph()
    node_attrs = _get_node_attributes(session, node_type)

    edges_added = 0
    for (a, b), weight in weights.items():
        if weight >= min_weight:
            G.add_edge(a, b, weight=weight)
            edges_added += 1

    # Add node attributes
    for node_id in G.nodes():
        if node_id in node_attrs:
            for key, value in node_attrs[node_id].items():
                G.nodes[node_id][key] = value

    logger.info(
        "Built graph: {} nodes, {} edges (min_weight={}, algorithm={})",
        G.number_of_nodes(),
        G.number_of_edges(),
        min_weight,
        algorithm,
    )

    # 5. Export if path provided
    if output_path:
        exporter = EXPORTERS.get(export_format)
        if exporter is None:
            raise ValueError(
                f"Unknown format '{export_format}'. Options: {list(EXPORTERS.keys())}"
            )
        exporter(G, output_path)

    return G
