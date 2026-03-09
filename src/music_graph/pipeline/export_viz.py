"""Export graph data as JSON for visualization."""

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx
from loguru import logger
from sqlmodel import Session, select

from music_graph.models.artist import ArtistSource
from music_graph.models.base import SourcePlatform
from music_graph.models.playlist import Playlist, PlaylistTrack
from music_graph.models.track import Track, TrackArtist, TrackSource
from music_graph.pipeline.build_graph import build_graph
from music_graph.pipeline.input_filters import get_playlist_ids
from music_graph.pipeline.viz_filters import (
    VizFilterConfig,
    filter_graph,
    get_artist_track_counts,
)


def _detect_communities_leiden(
    G: nx.Graph, resolution: float = 1.0
) -> list[set[str]]:
    """Detect communities using the Leiden algorithm.

    Converts NetworkX graph to igraph, runs Leiden, and returns
    communities as a list of sets (same format as nx.community functions).
    """
    import igraph as ig
    import leidenalg

    # Map NetworkX node IDs to igraph integer indices
    node_list = list(G.nodes())
    node_to_idx = {n: i for i, n in enumerate(node_list)}

    ig_graph = ig.Graph(n=len(node_list), directed=False)
    edges = [(node_to_idx[u], node_to_idx[v]) for u, v in G.edges()]
    ig_graph.add_edges(edges)
    ig_graph.es["weight"] = [G[u][v].get("weight", 1.0) for u, v in G.edges()]

    partition = leidenalg.find_partition(
        ig_graph,
        leidenalg.RBConfigurationVertexPartition,
        weights="weight",
        resolution_parameter=resolution,
        seed=42,
    )

    communities: list[set[str]] = []
    for members in partition:
        communities.append({node_list[i] for i in members})

    # Sort by size descending (largest community first)
    communities.sort(key=len, reverse=True)
    return communities


def _merge_small_communities(
    G: nx.Graph,
    communities: list[set[str]],
    min_size: int = 10,
) -> list[set[str]]:
    """Merge communities smaller than min_size into their most-connected neighbor.

    No artists are lost — small communities are absorbed into the large
    community they share the most edge weight with.
    """
    if min_size <= 1:
        return communities

    # Build node -> community index
    node_to_comm: dict[str, int] = {}
    for idx, comm in enumerate(communities):
        for n in comm:
            node_to_comm[n] = idx

    # Build inter-community weight matrix
    inter_weight: dict[tuple[int, int], float] = defaultdict(float)
    for u, v, d in G.edges(data=True):
        cu, cv = node_to_comm.get(u, -1), node_to_comm.get(v, -1)
        if cu != cv and cu >= 0 and cv >= 0:
            pair = (min(cu, cv), max(cu, cv))
            inter_weight[pair] += d.get("weight", 1.0)

    # Iteratively merge smallest communities
    merged = list(communities)
    changed = True
    while changed:
        changed = False
        for i in range(len(merged)):
            if len(merged[i]) == 0 or len(merged[i]) >= min_size:
                continue
            # Find most-connected large neighbor
            best_target = -1
            best_weight = 0.0
            for j in range(len(merged)):
                if i == j or len(merged[j]) == 0:
                    continue
                pair = (min(i, j), max(i, j))
                w = inter_weight.get(pair, 0.0)
                if w > best_weight:
                    best_weight = w
                    best_target = j
            # If no edges to any neighbor, absorb into the largest community
            if best_target < 0:
                largest_idx = max(
                    (j for j in range(len(merged)) if j != i and len(merged[j]) > 0),
                    key=lambda j: len(merged[j]),
                    default=-1,
                )
                best_target = largest_idx

            if best_target >= 0:
                # Absorb community i into best_target
                merged[best_target] = merged[best_target] | merged[i]
                # Update inter-community weights
                for j in range(len(merged)):
                    if j == i or j == best_target:
                        continue
                    old_pair = (min(i, j), max(i, j))
                    new_pair = (min(best_target, j), max(best_target, j))
                    if old_pair in inter_weight:
                        inter_weight[new_pair] += inter_weight.pop(old_pair)
                merged[i] = set()
                changed = True

    # Remove empty sets and re-sort by size
    result = [c for c in merged if len(c) > 0]
    result.sort(key=len, reverse=True)

    small_count = len(communities) - len(result)
    if small_count > 0:
        logger.info("Merged {} small communities (<{} nodes) → {} communities",
                     small_count, min_size, len(result))
    return result


def _get_artist_platforms(session: Session) -> dict[str, list[str]]:
    """Get platform list for each artist."""
    rows = session.exec(select(ArtistSource.artist_id, ArtistSource.platform)).all()
    platforms: dict[str, set[str]] = defaultdict(set)
    for artist_id, platform in rows:
        platforms[artist_id].add(platform.value)
    return {k: sorted(v) for k, v in platforms.items()}


def _get_artist_playlist_counts(session: Session) -> dict[str, int]:
    """Get number of distinct playlists each artist appears in."""
    return {k: len(v) for k, v in _get_artist_playlist_ids(session).items()}


_get_artist_track_counts = get_artist_track_counts


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

    track_sources: dict[str, TrackSource] = {}
    for ts in _batched_in(
        session,
        lambda ids: select(TrackSource).where(TrackSource.track_id.in_(ids)),
        all_track_ids,
    ):
        track_sources[ts.track_id] = ts

    result: dict[str, list[dict]] = {}
    for artist_id, track_ids in artist_track_ids.items():
        tracks = []
        for tid in track_ids[:max_tracks_per_artist]:
            track = tracks_by_id.get(tid)
            ts = track_sources.get(tid)
            if track and ts:
                t = {
                    "title": track.canonical_title,
                    "platform": ts.platform.value,
                    "url": _track_url(ts),
                }
                if ts.platform == SourcePlatform.DEEZER:
                    t["deezerId"] = ts.platform_id
                tracks.append(t)
        result[artist_id] = tracks
    return result


def _track_url(ts: TrackSource) -> str:
    """Build a user-facing URL for a track source."""
    if ts.platform == SourcePlatform.DEEZER:
        return f"https://www.deezer.com/track/{ts.platform_id}"
    if ts.platform == SourcePlatform.SPOTIFY:
        return f"https://open.spotify.com/track/{ts.platform_id}"
    if ts.platform == SourcePlatform.SOUNDCLOUD:
        raw = ts.raw_json or {}
        return raw.get("permalink_url", "")
    return ""


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

    # Spread centers proportionally to community sizes
    community_radii: dict[int, float] = {}
    for idx, nodes_in_g in enumerate(community_nodes_in_g):
        if nodes_in_g:
            community_radii[idx] = math.sqrt(len(nodes_in_g)) * 0.04

    # Scale meta-layout: proportional to avg community radius
    # so communities don't overlap but aren't too far apart
    avg_radius = sum(community_radii.values()) / max(len(community_radii), 1)
    n_communities = len(community_radii)
    spread_factor = avg_radius * n_communities * 0.5
    spread_factor = max(1.5, min(spread_factor, 6.0))
    for idx in meta_pos:
        mx, my, mz = meta_pos[idx]
        meta_pos[idx] = (mx * spread_factor, my * spread_factor, mz * spread_factor)

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


def _get_track_platforms(session: Session) -> dict[str, list[str]]:
    """Get platform list for each track."""
    rows = session.exec(select(TrackSource.track_id, TrackSource.platform)).all()
    platforms: dict[str, set[str]] = defaultdict(set)
    for track_id, platform in rows:
        platforms[track_id].add(platform.value)
    return {k: sorted(v) for k, v in platforms.items()}


def _get_track_metadata(
    session: Session, track_ids: set[str]
) -> dict[str, dict]:
    """Get metadata for tracks: artist name, duration, deezer ID, URL."""
    tracks_by_id: dict[str, Track] = {}
    for track in _batched_in(
        session, lambda ids: select(Track).where(Track.id.in_(ids)), track_ids
    ):
        tracks_by_id[track.id] = track

    # Get primary artist name per track via TrackArtist
    from music_graph.models.artist import Artist

    ta_rows = _batched_in(
        session,
        lambda ids: select(TrackArtist).where(TrackArtist.track_id.in_(ids)),
        track_ids,
    )
    track_artist_ids: dict[str, str] = {}
    for ta in ta_rows:
        if ta.track_id not in track_artist_ids:
            track_artist_ids[ta.track_id] = ta.artist_id

    artist_ids = set(track_artist_ids.values())
    artists_by_id: dict[str, str] = {}
    for artist in _batched_in(
        session, lambda ids: select(Artist).where(Artist.id.in_(ids)), artist_ids
    ):
        artists_by_id[artist.id] = artist.canonical_name

    # Get track sources for URL + deezerId
    track_sources: dict[str, TrackSource] = {}
    for ts in _batched_in(
        session,
        lambda ids: select(TrackSource).where(TrackSource.track_id.in_(ids)),
        track_ids,
    ):
        # Prefer Deezer source for URL/preview
        if ts.track_id not in track_sources or ts.platform == SourcePlatform.DEEZER:
            track_sources[ts.track_id] = ts

    result: dict[str, dict] = {}
    for tid in track_ids:
        track = tracks_by_id.get(tid)
        if not track:
            continue
        ts = track_sources.get(tid)
        artist_id = track_artist_ids.get(tid)
        meta: dict = {
            "artistName": artists_by_id.get(artist_id, track.canonical_artist_name) if artist_id else track.canonical_artist_name,
            "duration": (track.duration_ms // 1000) if track.duration_ms else None,
        }
        if ts:
            meta["url"] = _track_url(ts)
            if ts.platform == SourcePlatform.DEEZER:
                meta["deezerId"] = ts.platform_id
        result[tid] = meta

    return result


def _get_track_playlist_counts(session: Session) -> dict[str, int]:
    """Get number of distinct playlists each track appears in."""
    rows = session.exec(select(PlaylistTrack.track_id, PlaylistTrack.playlist_id)).all()
    counts: dict[str, set[str]] = defaultdict(set)
    for track_id, playlist_id in rows:
        counts[track_id].add(playlist_id)
    return {k: len(v) for k, v in counts.items()}


def _get_artist_playlist_ids(session: Session) -> dict[str, set[str]]:
    """Map each artist to the set of playlist IDs they appear in."""
    pt_rows = session.exec(select(PlaylistTrack.track_id, PlaylistTrack.playlist_id)).all()
    ta_rows = session.exec(select(TrackArtist.track_id, TrackArtist.artist_id)).all()

    track_to_artists: dict[str, set[str]] = defaultdict(set)
    for ta in ta_rows:
        track_to_artists[ta.track_id].add(ta.artist_id)

    artist_playlists: dict[str, set[str]] = defaultdict(set)
    for pt in pt_rows:
        for artist_id in track_to_artists.get(pt.track_id, set()):
            artist_playlists[artist_id].add(pt.playlist_id)

    return artist_playlists


def _get_community_playlist_keywords(
    session: Session,
    communities: list[set[str]],
    graph_nodes: set[str],
    top_k: int = 15,
) -> list[list[str]]:
    """Get top playlist names per community for naming context."""
    artist_playlists = _get_artist_playlist_ids(session)

    # Load all playlist names
    playlists = session.exec(select(Playlist.id, Playlist.name)).all()
    playlist_names: dict[str, str] = {pid: name for pid, name in playlists}

    result = []
    for community in communities:
        community_in_graph = [n for n in community if n in graph_nodes]
        playlist_counter: Counter[str] = Counter()
        for artist_id in community_in_graph:
            for pid in artist_playlists.get(artist_id, set()):
                name = playlist_names.get(pid, "")
                if name:
                    playlist_counter[name] += 1
        top_playlists = [name for name, _ in playlist_counter.most_common(top_k)]
        result.append(top_playlists)

    return result


def _name_communities_llm(
    communities_data: list[dict],
) -> dict[int, str]:
    """Use LLM to generate short names for communities.

    Args:
        communities_data: List of dicts with 'id', 'top_artists', 'top_playlists'.

    Returns:
        Dict mapping community id to generated name.
    """
    from music_graph.judge.llm_client import LLMClient

    system_prompt = (
        "You are an electronic music expert specializing in underground scenes: "
        "bouncy techno, hard bounce, eurotrance, neo rave, hardgroove, neo trance, "
        "acid techno, hard techno, psytrance, and adjacent sub-genres.\n\n"
        "You will receive community data from an artist co-occurrence graph built "
        "from playlist data across Deezer and SoundCloud. Each community is a cluster "
        "of artists that frequently appear together in playlists. Your job is to assign "
        "a short, descriptive genre/scene name to each community based on the artists "
        "and playlist names provided."
    )

    community_lines = []
    for c in communities_data:
        artists = ", ".join(c["top_artists"][:15])
        playlists = ", ".join(c["top_playlists"][:15])
        community_lines.append(
            f"Community {c['id']} ({c['size']} artists):\n"
            f"  Top artists: {artists}\n"
            f"  Playlists they appear in: {playlists}"
        )

    user_prompt = (
        "Name each community with a short genre/scene label (2-4 words max).\n\n"
        "Rules:\n"
        "- Be as specific as possible — prefer sub-genre names (e.g. 'Hard Bounce UK', "
        "'Bouncy Techno', 'Neo Trance') over broad labels ('Techno', 'Electronic').\n"
        "- Use the playlist names as strong genre signals — they often contain the "
        "sub-genre name directly.\n"
        "- Communities can share a genre name if they genuinely represent the same style.\n"
        "- If a community mixes genres, pick the dominant one or combine two "
        "(e.g. 'Acid / Hard Techno').\n\n"
        + "\n\n".join(community_lines)
        + "\n\nRespond ONLY with a JSON object mapping community ID (int) to name (string). "
        "Example: {\"0\": \"Hard Bounce\", \"1\": \"Neo Trance\"}"
    )

    client = LLMClient()
    # Force cloud models (Gemini/Groq) — local models lack sub-genre knowledge
    cloud_models = [
        (p, m) for p, m in client._models if p != "ollama"
    ]
    if cloud_models:
        client._models = cloud_models
    raw = client.generate(system_prompt, user_prompt, max_rounds=1)
    logger.debug("LLM community naming raw response: {}", raw)

    # Parse JSON from response (handle markdown code blocks)
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]

    names = json.loads(text)
    return {int(k): v for k, v in names.items()}


def _build_artist_nodes(
    session: Session,
    G: nx.Graph,
    node_ids: list[str],
    uuid_to_int: dict[str, int],
    positions: dict[str, tuple[float, float, float]],
    node_community: dict[str, int],
) -> tuple[list[dict], dict[int, list[dict]]]:
    """Build node JSON array and tracks sidecar for artist graphs."""
    artist_platforms = _get_artist_platforms(session)
    artist_tracks = _get_artist_tracks(session)
    artist_playlist_counts = _get_artist_playlist_counts(session)
    artist_track_counts = _get_artist_track_counts(session)

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

    return nodes, tracks_sidecar


def _build_track_nodes(
    session: Session,
    G: nx.Graph,
    node_ids: list[str],
    uuid_to_int: dict[str, int],
    positions: dict[str, tuple[float, float, float]],
    node_community: dict[str, int],
) -> tuple[list[dict], dict]:
    """Build node JSON array for track graphs (no sidecar needed)."""
    track_platforms = _get_track_platforms(session)
    track_playlist_counts = _get_track_playlist_counts(session)
    track_meta = _get_track_metadata(session, set(node_ids))

    nodes = []
    for uid in node_ids:
        node_data = G.nodes[uid]
        connections = G.degree(uid)
        playlist_count = track_playlist_counts.get(uid, 0)
        pos = positions.get(uid, (500, 500, 500))
        int_id = uuid_to_int[uid]
        meta = track_meta.get(uid, {})
        node_json: dict = {
            "id": int_id,
            "name": node_data.get("label", "Unknown"),
            "x": round(pos[0], 1),
            "y": round(pos[1], 1),
            "z": round(pos[2], 1),
            "community": node_community.get(uid, 0),
            "connections": connections,
            "playlists": playlist_count,
            "platforms": track_platforms.get(uid, []),
            "artistName": meta.get("artistName", ""),
        }
        if meta.get("duration") is not None:
            node_json["duration"] = meta["duration"]
        if meta.get("deezerId"):
            node_json["deezerId"] = meta["deezerId"]
        if meta.get("url"):
            node_json["url"] = meta["url"]
        nodes.append(node_json)

    return nodes, {}


def _build_track_communities_summary(
    G: nx.Graph,
    communities: list[set[str]],
    graph_nodes: set[str],
) -> list[dict]:
    """Build communities summary for track graphs.

    Extracts artist names from track node labels (format: "Title - Artist").
    """
    communities_summary = []
    for idx, community in enumerate(communities):
        community_in_graph = [n for n in community if n in graph_nodes]
        community_with_degree = [
            (G.degree(n, weight="weight"), G.nodes[n].get("label", ""))
            for n in community_in_graph
        ]
        community_with_degree.sort(reverse=True)
        # Extract artist names from track labels "Title - Artist"
        top_artists = []
        seen_artists: set[str] = set()
        for _, label in community_with_degree:
            artist = G.nodes.get(
                next((n for n in community_in_graph if G.nodes[n].get("label") == label), ""),
                {},
            ).get("artist", "")
            if not artist:
                # Fallback: parse from label "Title - Artist"
                parts = label.rsplit(" - ", 1)
                artist = parts[-1] if len(parts) > 1 else label
            if artist and artist not in seen_artists:
                seen_artists.add(artist)
                top_artists.append(artist)
                if len(top_artists) >= 5:
                    break
        communities_summary.append({
            "id": idx,
            "size": len(community_in_graph),
            "top_artists": top_artists,
            "top_playlists": [],
        })
    return communities_summary


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

    node_type = config.node_type

    # Input filters: select which playlists feed the projection
    playlist_ids = get_playlist_ids(session, max_tier=config.max_tier)

    G = build_graph(
        session,
        node_type=node_type,
        algorithm="jaccard",
        min_weight=config.min_weight,
        min_cooccurrence=config.min_cooccurrence,
        playlist_ids=playlist_ids,
    )

    if G.number_of_nodes() == 0:
        logger.warning("Empty graph, nothing to export")
        return {"nodes": 0, "edges": 0, "communities": 0}

    # Apply pluggable filters
    G = filter_graph(G, config, session=session)

    if G.number_of_nodes() == 0:
        logger.warning("All nodes filtered out, nothing to export")
        return {"nodes": 0, "edges": 0, "communities": 0}

    # Community detection (Leiden)
    communities = _detect_communities_leiden(G, resolution=config.resolution)

    # Merge tiny communities (<10 nodes) into their closest neighbor
    communities = _merge_small_communities(G, communities, min_size=10)

    node_community: dict[str, int] = {}
    for idx, community in enumerate(communities):
        for node_id in community:
            node_community[node_id] = idx

    logger.info("Detected {} communities via Leiden (resolution={}) after merge",
                len(communities), config.resolution)

    # Layout
    positions = _compute_community_layout(G, communities, node_community)

    # Map UUIDs to integers for smaller JSON
    node_ids = list(G.nodes())
    uuid_to_int: dict[str, int] = {uid: i for i, uid in enumerate(node_ids)}

    # Enrich nodes with metadata — branch by node_type
    if node_type == "track":
        nodes, tracks_sidecar = _build_track_nodes(
            session, G, node_ids, uuid_to_int, positions, node_community,
        )
    else:
        nodes, tracks_sidecar = _build_artist_nodes(
            session, G, node_ids, uuid_to_int, positions, node_community,
        )

    # Build links array
    links = []
    for u, v, d in G.edges(data=True):
        links.append({
            "source": uuid_to_int[u],
            "target": uuid_to_int[v],
            "weight": round(d.get("weight", 0), 4),
        })

    # Build communities summary
    graph_nodes = set(G.nodes())

    # For tracks, extract artist names from node labels for community naming
    if node_type == "track":
        communities_summary = _build_track_communities_summary(
            G, communities, graph_nodes,
        )
    else:
        community_playlist_kw = _get_community_playlist_keywords(
            session, communities, graph_nodes,
        )
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
                "top_playlists": community_playlist_kw[idx],
            })

    # Name communities via LLM (single attempt, fall back to top artists)
    try:
        community_names = _name_communities_llm(communities_summary)
        for c in communities_summary:
            c["name"] = community_names.get(c["id"], "")
        logger.info("Communities named via LLM: {}", community_names)
    except Exception as e:
        logger.warning("LLM naming failed ({}), using top-artist fallback", e)
        for c in communities_summary:
            artists = c.get("top_artists", [])
            c["name"] = ", ".join(artists[:2]) if artists else ""

    # Remove top_playlists from final JSON (only used for LLM context)
    for c in communities_summary:
        c.pop("top_playlists", None)

    data = {
        "graphType": node_type,
        "preset": {"name": config.name, "label": config.label},
        "nodes": nodes,
        "links": links,
        "communities": communities_summary,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    # Write tracks sidecar only for artist graphs
    if node_type == "artist":
        tracks_path = output_path.parent / "graph_tracks.json"
        with open(tracks_path, "w", encoding="utf-8") as f:
            json.dump(tracks_sidecar, f, ensure_ascii=False)
        tracks_size_mb = tracks_path.stat().st_size / (1024 * 1024)
    else:
        tracks_size_mb = 0.0

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info(
        "Exported viz JSON ({}): {} nodes, {} edges, {} communities ({:.1f} MB{})",
        node_type,
        len(nodes),
        len(links),
        len(communities_summary),
        size_mb,
        f" + {tracks_size_mb:.1f} MB tracks" if tracks_size_mb else "",
    )

    return {
        "nodes": len(nodes),
        "edges": len(links),
        "communities": len(communities_summary),
    }
