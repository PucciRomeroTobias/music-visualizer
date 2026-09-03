from typer.testing import CliRunner

from music_graph import db
from music_graph.cli import app


def test_stats_initializes_a_fresh_database(tmp_path, monkeypatch) -> None:
    engine = db.get_engine(tmp_path / "fresh.db")
    monkeypatch.setattr(db, "get_engine", lambda: engine)

    result = CliRunner().invoke(app, ["stats"])

    assert result.exit_code == 0
    assert "Tracks:          0 canonical" in result.stdout
    assert "Playlists:       0" in result.stdout
