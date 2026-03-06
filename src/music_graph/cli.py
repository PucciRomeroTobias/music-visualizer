"""CLI interface for music-graph."""

from pathlib import Path

import typer
from loguru import logger

app = typer.Typer(name="music-graph", help="Build music co-occurrence graphs.")


@app.command()
def collect(
    platform: str = typer.Option("spotify", help="Platform to collect from"),
    max_depth: int = typer.Option(2, help="Maximum BFS depth"),
) -> None:
    """Collect music data from a platform using BFS expansion."""
    from music_graph.db import get_engine, init_db, get_session

    engine = get_engine()
    init_db(engine)

    from music_graph.pipeline.collect import BFSOrchestrator

    if platform == "deezer":
        from music_graph.collectors.deezer import DeezerCollector

        collector = DeezerCollector()
    elif platform == "spotify":
        from music_graph.collectors.spotify import SpotifyCollector

        collector = SpotifyCollector()
    else:
        logger.error("Platform '{}' not yet supported", platform)
        raise typer.Exit(1)

    with get_session(engine) as session:
        orchestrator = BFSOrchestrator(session, collector)
        orchestrator.run(max_depth=max_depth)


@app.command()
def stats() -> None:
    """Show database statistics with platform breakdown."""
    from sqlmodel import func, select

    from music_graph.db import get_engine, get_session
    from music_graph.models.artist import Artist, ArtistSource
    from music_graph.models.genre import Genre
    from music_graph.models.playlist import Playlist, PlaylistTrack
    from music_graph.models.track import Track, TrackSource

    engine = get_engine()
    with get_session(engine) as session:
        tracks = session.exec(select(func.count(Track.id))).one()
        track_sources = session.exec(select(func.count(TrackSource.id))).one()
        artists = session.exec(select(func.count(Artist.id))).one()
        artist_sources = session.exec(select(func.count(ArtistSource.id))).one()
        genres = session.exec(select(func.count(Genre.id))).one()
        playlists = session.exec(select(func.count(Playlist.id))).one()
        playlist_tracks = session.exec(
            select(func.count()).select_from(PlaylistTrack)
        ).one()

        # Platform breakdown for artists
        artist_platform_counts = session.exec(
            select(
                ArtistSource.platform,
                func.count(func.distinct(ArtistSource.artist_id)),
            ).group_by(ArtistSource.platform)
        ).all()
        artist_cross = session.exec(
            select(func.count()).select_from(
                select(ArtistSource.artist_id)
                .group_by(ArtistSource.artist_id)
                .having(func.count(func.distinct(ArtistSource.platform)) > 1)
                .subquery()
            )
        ).one()

        # Platform breakdown for tracks
        track_platform_counts = session.exec(
            select(
                TrackSource.platform,
                func.count(func.distinct(TrackSource.track_id)),
            ).group_by(TrackSource.platform)
        ).all()
        track_cross = session.exec(
            select(func.count()).select_from(
                select(TrackSource.track_id)
                .group_by(TrackSource.track_id)
                .having(func.count(func.distinct(TrackSource.platform)) > 1)
                .subquery()
            )
        ).one()

    # Format platform breakdowns
    artist_parts = [f"{count} {plat.value}" for plat, count in artist_platform_counts]
    if artist_cross:
        artist_parts.append(f"{artist_cross} cross-platform")
    artist_breakdown = ", ".join(artist_parts)

    track_parts = [f"{count} {plat.value}" for plat, count in track_platform_counts]
    if track_cross:
        track_parts.append(f"{track_cross} cross-platform")
    track_breakdown = ", ".join(track_parts)

    typer.echo("=== Music Graph Database Stats ===")
    typer.echo(f"Tracks:          {tracks} canonical ({track_breakdown})")
    typer.echo(f"  Sources:       {track_sources}")
    typer.echo(f"Artists:         {artists} canonical ({artist_breakdown})")
    typer.echo(f"  Sources:       {artist_sources}")
    typer.echo(f"Genres:          {genres}")
    typer.echo(f"Playlists:       {playlists}")
    typer.echo(f"Playlist-Tracks: {playlist_tracks}")


@app.command()
def build_graph(
    node_type: str = typer.Option("track", help="Node type: track, artist, genre"),
    algorithm: str = typer.Option("jaccard", help="Weight algorithm: raw, jaccard, pmi, cosine"),
    min_weight: float = typer.Option(0.01, help="Minimum edge weight threshold"),
    min_cooccurrence: int = typer.Option(1, "--min-cooccurrence", help="Minimum raw co-occurrence count"),
    output: Path = typer.Option(
        Path("data/exports/graph.gexf"), help="Output file path"
    ),
    export_format: str = typer.Option(None, "--format", help="Export format (gexf, graphml, json). Inferred from extension if not set."),
) -> None:
    """Build a co-occurrence graph and export it."""
    from music_graph.db import get_engine, get_session
    from music_graph.pipeline.build_graph import build_graph as _build_graph

    # Infer format from extension if not explicitly set
    if export_format is None:
        ext = output.suffix.lstrip(".")
        export_format = ext if ext in ("gexf", "graphml", "json") else "gexf"

    engine = get_engine()
    with get_session(engine) as session:
        graph = _build_graph(
            session,
            node_type=node_type,
            algorithm=algorithm,
            min_weight=min_weight,
            min_cooccurrence=min_cooccurrence,
            output_path=output,
            export_format=export_format,
        )

    typer.echo(
        f"Graph built: {graph.number_of_nodes()} nodes, "
        f"{graph.number_of_edges()} edges → {output}"
    )


@app.command()
def seed_collect(
    artists_file: Path = typer.Option(
        Path("data/soundcloud_artists.json"),
        help="JSON file with artist names from SoundCloud",
    ),
    playlists_per_keyword: int = typer.Option(
        25, help="Max playlists per genre keyword search"
    ),
    min_overlap: int = typer.Option(
        2, help="Minimum known-artist tracks to qualify a playlist"
    ),
    max_minutes: float = typer.Option(
        15.0, help="Maximum batch duration in minutes"
    ),
    reset_db: bool = typer.Option(
        False, "--reset", help="Reset database before collecting"
    ),
) -> None:
    """Seed collection: genre keyword search filtered by SoundCloud artist overlap."""
    from music_graph.db import get_engine, get_session, init_db
    from music_graph.pipeline.seed_from_artists import (
        load_soundcloud_artists,
        seed_from_artists,
    )

    if not artists_file.exists():
        logger.error("Artists file not found: {}", artists_file)
        raise typer.Exit(1)

    engine = get_engine()

    if reset_db:
        from sqlmodel import SQLModel

        SQLModel.metadata.drop_all(engine)
        logger.info("Database reset")

    init_db(engine)

    artist_names = load_soundcloud_artists(artists_file)
    logger.info("Loaded {} artist names from {}", len(artist_names), artists_file)

    with get_session(engine) as session:
        result = seed_from_artists(
            session,
            artist_names,
            playlists_per_keyword=playlists_per_keyword,
            min_overlap=min_overlap,
            max_minutes=max_minutes,
        )

    typer.echo(f"Batch result: {result}")
    if result["timed_out"]:
        typer.echo("Run again to continue where it left off.")


@app.command()
def expand(
    min_playlists: int = typer.Option(
        4, help="Minimum playlist appearances to be a hub artist"
    ),
    playlists_per_artist: int = typer.Option(
        5, help="Max playlists to search per related artist"
    ),
    min_overlap: int = typer.Option(
        2, help="Minimum known-artist tracks to qualify a playlist"
    ),
    max_minutes: float = typer.Option(
        15.0, help="Maximum batch duration in minutes"
    ),
) -> None:
    """Expand the graph via related artists from Deezer."""
    from music_graph.db import get_engine, get_session
    from music_graph.pipeline.expand import expand_via_related

    engine = get_engine()
    with get_session(engine) as session:
        result = expand_via_related(
            session,
            min_playlists=min_playlists,
            playlists_per_artist=playlists_per_artist,
            min_overlap=min_overlap,
            max_minutes=max_minutes,
        )

    typer.echo(f"Batch result: {result}")
    if result["timed_out"]:
        typer.echo("Run again to continue where it left off.")


@app.command("sc-collect")
def sc_collect(
    user_id: str = typer.Option(..., "--user-id", help="SoundCloud user ID to collect from"),
    max_minutes: float = typer.Option(
        15.0, help="Maximum batch duration in minutes"
    ),
) -> None:
    """Collect playlists and tracks from a SoundCloud user."""
    from music_graph.db import get_engine, get_session, init_db
    from music_graph.pipeline.collect_soundcloud import collect_soundcloud

    engine = get_engine()
    init_db(engine)

    with get_session(engine) as session:
        result = collect_soundcloud(
            session,
            user_id=user_id,
            max_minutes=max_minutes,
        )

    typer.echo(f"Batch result: {result}")
    if result["timed_out"]:
        typer.echo("Run again to continue where it left off.")


@app.command("sc-search")
def sc_search(
    max_minutes: float = typer.Option(
        15.0, help="Maximum batch duration in minutes"
    ),
    playlists_per_keyword: int = typer.Option(
        25, help="Max playlists per keyword search"
    ),
) -> None:
    """Search SoundCloud playlists by seed keywords and ingest tracks."""
    from music_graph.db import get_engine, get_session, init_db
    from music_graph.pipeline.collect_soundcloud import search_and_collect_soundcloud

    engine = get_engine()
    init_db(engine)

    with get_session(engine) as session:
        result = search_and_collect_soundcloud(
            session,
            playlists_per_keyword=playlists_per_keyword,
            max_minutes=max_minutes,
        )

    typer.echo(f"Batch result: {result}")
    if result["timed_out"]:
        typer.echo("Run again to continue where it left off.")


@app.command("dz-search")
def dz_search(
    max_minutes: float = typer.Option(
        15.0, help="Maximum batch duration in minutes"
    ),
    playlists_per_keyword: int = typer.Option(
        25, help="Max playlists per keyword search"
    ),
) -> None:
    """Search Deezer playlists by seed keywords and ingest tracks."""
    from music_graph.db import get_engine, get_session, init_db
    from music_graph.pipeline.collect_deezer import search_and_collect_deezer

    engine = get_engine()
    init_db(engine)

    with get_session(engine) as session:
        result = search_and_collect_deezer(
            session,
            playlists_per_keyword=playlists_per_keyword,
            max_minutes=max_minutes,
        )

    typer.echo(f"Batch result: {result}")
    if result["timed_out"]:
        typer.echo("Run again to continue where it left off.")


@app.command("sc-mine")
def sc_mine(
    max_minutes: float = typer.Option(
        15.0, help="Maximum batch duration in minutes"
    ),
) -> None:
    """Mine playlists from SoundCloud uploaders found in existing tracks."""
    from music_graph.db import get_engine, get_session, init_db
    from music_graph.pipeline.collect_soundcloud import mine_artist_playlists_soundcloud

    engine = get_engine()
    init_db(engine)

    with get_session(engine) as session:
        result = mine_artist_playlists_soundcloud(
            session,
            max_minutes=max_minutes,
        )

    typer.echo(f"Batch result: {result}")
    if result["timed_out"]:
        typer.echo("Run again to continue where it left off.")


@app.command()
def match(
    entity: str = typer.Option(
        "all", help="Entity type to resolve: artist, track, or all"
    ),
    max_minutes: float = typer.Option(
        15.0, help="Maximum batch duration in minutes"
    ),
) -> None:
    """Run cross-platform entity matching and merging."""
    from music_graph.db import get_engine, get_session, init_db
    from music_graph.matching.resolver import CrossPlatformResolver

    engine = get_engine()
    init_db(engine)

    with get_session(engine) as session:
        resolver = CrossPlatformResolver(session)

        if entity in ("artist", "all"):
            artist_result = resolver.resolve_artists(max_minutes=max_minutes)
            typer.echo(f"Artist resolution: {artist_result}")

        if entity in ("track", "all"):
            track_result = resolver.resolve_tracks(max_minutes=max_minutes)
            typer.echo(f"Track resolution: {track_result}")


@app.command("export-viz")
def export_viz(
    output: Path = typer.Option(
        Path("viz/public/data/graph.json"), help="Output JSON file path"
    ),
    min_cooccurrence: int = typer.Option(
        2, "--min-cooccurrence", help="Min co-occurrence count for edges"
    ),
    max_edges: int = typer.Option(
        None, "--max-edges", help="Max edges to include (top by weight)"
    ),
    min_degree: int = typer.Option(
        3, "--min-degree", help="Min connections to keep a node"
    ),
    min_tracks: int = typer.Option(
        0, "--min-tracks", help="Min tracks an artist must have"
    ),
    preset: str = typer.Option(
        None, "--preset", help="Filter preset: 'strict' (overrides other flags)"
    ),
) -> None:
    """Export graph data as JSON for visualization."""
    from music_graph.db import get_engine, get_session
    from music_graph.pipeline.export_viz import export_visualization_json
    from music_graph.pipeline.viz_filters import (
        PRESET_STRICT,
        VizFilterConfig,
    )

    if preset == "strict":
        config = PRESET_STRICT
    else:
        config = VizFilterConfig(
            min_cooccurrence=min_cooccurrence,
            max_edges=max_edges,
            min_degree=min_degree,
            min_tracks=min_tracks,
        )

    engine = get_engine()
    with get_session(engine) as session:
        result = export_visualization_json(
            session,
            output_path=output,
            config=config,
        )

    typer.echo(
        f"Exported: {result['nodes']} nodes, {result['edges']} edges, "
        f"{result['communities']} communities → {output}"
    )


@app.command("match-stats")
def match_stats() -> None:
    """Show match candidate statistics by entity type and status."""
    from sqlmodel import func, select

    from music_graph.db import get_engine, get_session
    from music_graph.models.matching import MatchCandidate

    engine = get_engine()
    with get_session(engine) as session:
        rows = session.exec(
            select(
                MatchCandidate.entity_type,
                MatchCandidate.status,
                func.count(MatchCandidate.id),
            ).group_by(MatchCandidate.entity_type, MatchCandidate.status)
        ).all()

    typer.echo("=== Match Candidate Stats ===")
    if not rows:
        typer.echo("No match candidates yet.")
        return

    for entity_type, status, count in rows:
        typer.echo(f"  {entity_type:8s} {status.value:10s} {count}")


def main() -> None:
    """Entry point."""
    app()


if __name__ == "__main__":
    main()
