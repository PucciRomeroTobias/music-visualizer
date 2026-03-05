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
    """Show database statistics."""
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

    typer.echo("=== Music Graph Database Stats ===")
    typer.echo(f"Tracks:          {tracks} canonical, {track_sources} sources")
    typer.echo(f"Artists:         {artists} canonical, {artist_sources} sources")
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


def main() -> None:
    """Entry point."""
    app()


if __name__ == "__main__":
    main()
