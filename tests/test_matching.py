from music_graph.matching.normalize import normalize_name, normalize_track_title
from music_graph.matching.title_parser import parse_soundcloud_title


def test_normalize_artist_name_removes_noise_and_diacritics() -> None:
    assert normalize_name("  D.J. Ácido Official Music ") == "dj acido"


def test_normalize_track_title_removes_release_tags() -> None:
    assert normalize_track_title("Éxtasis (Original Mix) [Free DL]") == "extasis"


def test_parse_soundcloud_title_extracts_collaborators_and_feature() -> None:
    parsed = parse_soundcloud_title("Premiere: Alpha x Beta - Pulse (feat. Gamma)")

    assert parsed.is_parsed is True
    assert parsed.artists == ["Alpha", "Beta", "Gamma"]
    assert parsed.title == "Pulse"


def test_parse_soundcloud_title_falls_back_to_uploader() -> None:
    parsed = parse_soundcloud_title("Untitled live recording", "Local Label")

    assert parsed.is_parsed is False
    assert parsed.artists == ["Local Label"]
    assert parsed.title == "Untitled live recording"
