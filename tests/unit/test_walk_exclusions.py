"""repo.walk must skip the tool's own output and other dot-directories."""

from reducio.repo import _should_exclude_file, walk


def test_walk_excludes_dot_reducio(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    sessions = tmp_path / ".reducio" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "x.json").write_text("{}\n")
    assert [f.path for f in walk(str(tmp_path))] == ["a.py"]


def test_walk_excludes_arbitrary_dotdir(tmp_path):
    (tmp_path / "keep.py").write_text("x = 1\n")
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "secret.py").write_text("y = 2\n")
    assert [f.path for f in walk(str(tmp_path))] == ["keep.py"]


def test_walk_include_patterns(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.txt").write_text("nope\n")
    assert {f.path for f in walk(str(tmp_path), include_patterns=["*.py"])} == {"a.py"}


def test_should_exclude_file_rules():
    assert _should_exclude_file(".env") is True
    assert _should_exclude_file(".gitignore") is False
    assert _should_exclude_file("a.py") is False
    assert _should_exclude_file("img.png") is True
    assert _should_exclude_file("app.min.js") is True
