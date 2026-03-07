"""Export graph data as JSON for visualization."""

import json
import math
from collections import defaultdict
from pathlib import Path

import networkx as nx
from loguru import logger
from sqlmodel import Session, select

from music_graph.models.artist import ArtistSource
from music_graph.models.playlist import PlaylistTrack
from music_graph.models.track import Track, TrackArtist, TrackSource
from music_graph.pipeline.build_graph import build_graph
from music_graph.pipeline.viz_filters import VizFilterConfig, filter_graph


def _get_artist_platforms(session: Session) -> dict[str, list[str]]:
    """Get platform list for each artist."""
    rows = session.exec(select(ArtistSource.artist_id, ArtistSource.platform)).all()
    platforms: dict[str, set[str]] = defaultdict(set)
    for artist_id, platform in rows:
        platforms[artist_id].add(platform.value)
    return {k: sorted(v) for k, v in platforms.items()}


def _get_artist_playlist_counts(session: Session) -> dict[str, int]:
    """Get number of distinct playlists each artist appears in."""
    pt_rows = session.exec(select(PlaylistTrack.track_id, PlaylistTrack.playlist_id)).all()
    ta_rows = session.exec(select(TrackArtist.track_id, TrackArtist.artist_id)).all()

    track_to_artists: dict[str, set[str]] = defaultdict(set)
    for ta in ta_rows:
        track_to_artists[ta.track_id].add(ta.artist_id)

    artist_playlists: dict[str, set[str]] = defaultdict(set)
    for pt in pt_rows:
        for artist_id in track_to_artists.get(pt.track_id, set()):
            artist_playlists[artist_id].add(pt.playlist_id)

    return {k: len(v) for k, v in artist_playlists.items()}


def _get_artist_track_counts(session: Session) -> dict[str, int]:
    """Get number of tracks per artist."""
    rows = session.exec(select(TrackArtist)).all()
    counts: dict[str, int] = defaultdict(int)
    for ta in rows:
        counts[ta.artist_id] += 1
    return counts


def _batched_in(
    session: Session, stmt_fn, ids: set[str], batch_size: int = 500
) -> list:
    """Execute a SELECT ... WHERE id IN (...) in batches to avoid SQLite variable limit."""
    results = []
    id_list = list(ids)
    for i in range(0, len(id_list), batch_size):
        batch = id_list[i : i + batch_size]
        results.extend(session.exec(stmt_fn(batch)).all())
    return results


def _get_artist_tracks(
    session: Session, max_tracks_per_artist: int = 10
) -> dict[str, list[dict]]:
    """Get top tracks for each artist."""
    ta_rows = session.exec(select(TrackArtist.track_id, TrackArtist.artist_id)).all()
    artist_track_ids: dict[str, list[str]] = defaultdict(list)
    for track_id, artist_id in ta_rows:
        artist_track_ids[artist_id].append(track_id)

    all_track_ids = {tid for tids in artist_track_ids.values() for tid in tids}
    tracks_by_id: dict[str, Track] = {}
    for track in _batched_in(
        session, lambda ids: select(Track).where(Track.id.in_(ids)), all_track_ids
    ):
        tracks_by_id[track.id] = track

    track_platform_info: dict[str, tuple[str, str]] = {}  # track_id -> (platform, platform_id)
    for track_id, platform, platform_id in _batched_in(
        session,
        lambda ids: select(
            TrackSource.track_id, TrackSource.platform, TrackSource.platform_id
        ).where(TrackSource.track_id.in_(ids)),
        all_track_ids,
    ):
        track_platform_info[track_id] = (platform.value, platform_id)

    result: dict[str, list[dict]] = {}
    for artist_id, track_ids in artist_track_ids.items():
        tracks = []
        for tid in track_ids[:max_tracks_per_artist]:
            track = tracks_by_id.get(tid)
            if track:
                platform, platform_id = track_platform_info.get(tid, ("unknown", ""))
                tracks.append({
                    "title": track.canonical_title,
                    "platform": platform,
                    "platformId": platform_id,
                })
        result[artist_id] = tracks
    return result


def _compute_community_layout(
    G: nx.Graph,
    communities: list[set[str]],
    node_community: dict[str, int],
) -> dict[str, tuple[float, float, float]]:
    """Compute community-aware 3D layout.

    Two-level approach:
    1. Layout community centers via a meta-graph in 3D (unweighted, high repulsion).
    2. Layout nodes within each community using weighted spring_layout in 3D.
    3. Combine and normalize to [0, 1000] in all three axes.
    """
    logger.info("Computing community-aware 3D layout...")

    # Step 1: Build meta-graph (one node per community)
    meta_graph = nx.Graph()
    community_nodes_in_g: list[list[str]] = []
    for idx, community in enumerate(communities):
        nodes_in_g = [n for n in community if n in G]
        community_nodes_in_g.append(nodes_in_g)
        if nodes_in_g:
            meta_graph.add_node(idx, size=len(nodes_in_g))

    for u, v, d in G.edges(data=True):
        cu, cv = node_community[u], node_community[v]
        if cu != cv:
            if meta_graph.has_edge(cu, cv):
                meta_graph[cu][cv]["weight"] += d.get("weight", 1)
            else:
                meta_graph.add_edge(cu, cv, weight=d.get("weight", 1))

    # Step 2: Layout meta-graph in 3D
    meta_pos = nx.spring_layout(
        meta_graph, weight=None, iterations=200, seed=42, k=3.0, dim=3
    )

    # Spread centers wide so communities don't overlap
    community_radii: dict[int, float] = {}
    for idx, nodes_in_g in enumerate(community_nodes_in_g):
        if nodes_in_g:
            community_radii[idx] = math.sqrt(len(nodes_in_g)) * 0.04

    for idx in meta_pos:
        mx, my, mz = meta_pos[idx]
        meta_pos[idx] = (mx * 4.0, my * 4.0, mz * 4.0)

    # Step 3: Layout nodes within each community locally in 3D
    positions: dict[str, tuple[float, float, float]] = {}
    for idx, nodes_in_g in enumerate(community_nodes_in_g):
        if not nodes_in_g:
            continue
        center = meta_pos.get(idx, (0.0, 0.0, 0.0))
        if len(nodes_in_g) == 1:
            positions[nodes_in_g[0]] = center
            continue

        sub = G.subgraph(nodes_in_g)
        local_pos = nx.spring_layout(
            sub, weight="weight", iterations=80, seed=42, dim=3
        )

        radius = community_radii.get(idx, 0.1)
        cx, cy, cz = center
        for node in local_pos:
            lx, ly, lz = local_pos[node]
            positions[node] = (
                cx + lx * radius,
                cy + ly * radius,
                cz + lz * radius,
            )

    logger.info("Community layout computed ({} communities)", len(communities))

    # Normalize to [0, 1000] in all three axes
    xs = [p[0] for p in positions.values()]
    ys = [p[1] for p in positions.values()]
    zs = [p[2] for p in positions.values()]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    z_min, z_max = min(zs), max(zs)
    x_range = x_max - x_min or 1
    y_range = y_max - y_min or 1
    z_range = z_max - z_min or 1
    for uid in positions:
        positions[uid] = (
            (positions[uid][0] - x_min) / x_range * 1000,
            (positions[uid][1] - y_min) / y_range * 1000,
            (positions[uid][2] - z_min) / z_range * 1000,
        )

    return positions


def export_visualization_json(
    session: Session,
    output_path: Path,
    config: VizFilterConfig | None = None,
) -> dict:
    """Export graph data as optimized JSON for visualization.

    Args:
        session: Database session.
        output_path: Path for the output JSON file.
        config: Filter configuration (uses defaults if None).

    Returns:
        Summary dict with node/edge/community counts.
    """
    if config is None:
        config = VizFilterConfig()

    G = build_graph(
        session,
        node_type="artist",
        algorithm="jaccard",
        min_weight=config.min_weight,
        min_cooccurrence=config.min_cooccurrence,
    )

    if G.number_of_nodes() == 0:
        logger.warning("Empty graph, nothing to export")
        return {"nodes": 0, "edges": 0, "communities": 0}

    # Apply pluggable filters
    G = filter_graph(G, config, session=session)

    if G.number_of_nodes() == 0:
        logger.warning("All nodes filtered out, nothing to export")
        return {"nodes": 0, "edges": 0, "communities": 0}

    # Community detection (Louvain)
    communities = nx.community.louvain_communities(G, weight="weight", seed=42)
    node_community: dict[str, int] = {}
    for idx, community in enumerate(communities):
        for node_id in community:
            node_community[node_id] = idx

    logger.info("Detected {} communities via Louvain", len(communities))

    # Layout
    positions = _compute_community_layout(G, communities, node_community)

    # Enrich nodes with metadata
    artist_platforms = _get_artist_platforms(session)
    artist_tracks = _get_artist_tracks(session)
    artist_playlist_counts = _get_artist_playlist_counts(session)
    artist_track_counts = _get_artist_track_counts(session)

    # Map UUIDs to integers for smaller JSON
    node_ids = list(G.nodes())
    uuid_to_int: dict[str, int] = {uid: i for i, uid in enumerate(node_ids)}

    # Build nodes array
    nodes = []
    tracks_sidecar: dict[int, list[dict]] = {}
    for uid in node_ids:
        node_data = G.nodes[uid]
        connections = G.degree(uid)
        playlist_count = artist_playlist_counts.get(uid, 0)
        track_count = artist_track_counts.get(uid, 0)
        pos = positions.get(uid, (500, 500, 500))
        int_id = uuid_to_int[uid]
        nodes.append({
            "id": int_id,
            "name": node_data.get("label", "Unknown"),
            "x": round(pos[0], 1),
            "y": round(pos[1], 1),
            "z": round(pos[2], 1),
            "community": node_community.get(uid, 0),
            "connections": connections,
            "playlists": playlist_count,
            "trackCount": track_count,
            "platforms": artist_platforms.get(uid, []),
        })
        node_tracks = artist_tracks.get(uid, [])
        if node_tracks:
            tracks_sidecar[int_id] = node_tracks

    # Build links array
    links = []
    for u, v, d in G.edges(data=True):
        links.append({
            "source": uuid_to_int[u],
            "target": uuid_to_int[v],
            "weight": round(d.get("weight", 0), 4),
        })

    # Build communities summary
    communities_summary = []
    for idx, community in enumerate(communities):
        community_in_graph = [n for n in community if n in G]
        community_with_degree = [
            (G.degree(n, weight="weight"), G.nodes[n].get("label", ""))
            for n in community_in_graph
        ]
        community_with_degree.sort(reverse=True)
        top_artists = [name for _, name in community_with_degree[:5]]
        communities_summary.append({
            "id": idx,
            "size": len(community_in_graph),
            "top_artists": top_artists,
        })

    data = {
        "nodes": nodes,
        "links": links,
        "communities": communities_summary,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    # Write tracks sidecar (lazy-loaded by viz)
    tracks_path = output_path.parent / "graph_tracks.json"
    with open(tracks_path, "w", encoding="utf-8") as f:
        json.dump(tracks_sidecar, f, ensure_ascii=False)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    tracks_size_mb = tracks_path.stat().st_size / (1024 * 1024)
    logger.info(
        "Exported viz JSON: {} nodes, {} edges, {} communities ({:.1f} MB + {:.1f} MB tracks)",
        len(nodes),
        len(links),
        len(communities_summary),
        size_mb,
        tracks_size_mb,
    )

    return {
        "nodes": len(nodes),
        "edges": len(links),
        "communities": len(communities_summary),
    }
