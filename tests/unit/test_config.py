"""Config loading: YAML files + environment overrides."""

from pathlib import Path

import pytest

from reducto.config import ConfigError, apply_env, load_config
from reducto.models import AppConfig


def test_apply_env_model_override(monkeypatch):
    monkeypatch.setenv("REDUCTO_MODEL", "gpt-test")
    assert apply_env(AppConfig()).model == "gpt-test"


def test_apply_env_prefer_local_false(monkeypatch):
    monkeypatch.setenv("REDUCTO_PREFER_LOCAL", "false")
    assert apply_env(AppConfig()).prefer_local is False


def test_apply_env_verbose(monkeypatch):
    monkeypatch.setenv("REDUCTO_VERBOSE", "1")
    assert apply_env(AppConfig()).verbose is True


def test_apply_env_noop_when_unset(monkeypatch):
    for key in ("REDUCTO_MODEL", "REDUCTO_PREFER_LOCAL", "REDUCTO_VERBOSE"):
        monkeypatch.delenv(key, raising=False)
    cfg = apply_env(AppConfig())
    assert cfg.prefer_local is True
    assert cfg.verbose is False
    assert cfg.model == ""


def test_load_config_yaml(tmp_path, monkeypatch):
    (tmp_path / ".reducto.yaml").write_text(
        "verbose: true\ncomplexity_thresholds:\n  cyclomatic_complexity: 3\n"
    )
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.verbose is True
    assert cfg.complexity_thresholds.cyclomatic_complexity == 3


def test_load_config_explicit_path(tmp_path):
    p = tmp_path / "custom.yaml"
    p.write_text("model: zzz\n")
    assert load_config(str(p)).model == "zzz"


def test_load_config_missing_returns_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert load_config().model == AppConfig().model


@pytest.mark.parametrize(
    "source",
    [
        "[private-value]",
        "false",
        "123",
        "model: [private-value]",
        "model: [private-value",
        "verbose: private-value",
    ],
)
def test_invalid_config_does_not_dump_values(tmp_path, source):
    path = tmp_path / "settings.yaml"
    path.write_text(source)
    with pytest.raises(ConfigError) as error:
        load_config(str(path))
    assert str(path) in str(error.value)
    assert "private-value" not in str(error.value)


@pytest.mark.parametrize("source", ["", "# empty", "null", "{}"])
def test_empty_config_is_valid(tmp_path, source):
    path = tmp_path / "settings.yaml"
    path.write_text(source)
    assert load_config(str(path)) == AppConfig()


def test_explicit_config_missing_or_directory(tmp_path):
    for path in (tmp_path / "missing", tmp_path):
        with pytest.raises(ConfigError):
            load_config(str(path))


def test_unreadable_configuration(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("secret details")

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(ConfigError, match="Cannot read") as error:
        load_config(str(tmp_path / "settings.yaml"))
    assert "secret details" not in str(error.value)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("true", True),
        ("1", True),
        ("YES", True),
        ("on", True),
        ("false", False),
        ("0", False),
        ("No", False),
        ("off", False),
    ],
)
def test_environment_boolean_both_directions(monkeypatch, value, expected):
    monkeypatch.setenv("REDUCTO_VERBOSE", value)
    monkeypatch.setenv("REDUCTO_PREFER_LOCAL", value)
    cfg = apply_env(AppConfig(verbose=not expected, prefer_local=not expected))
    assert cfg.verbose is expected
    assert cfg.prefer_local is expected


def test_invalid_environment_boolean(monkeypatch):
    monkeypatch.setenv("REDUCTO_VERBOSE", "private-value")
    with pytest.raises(ConfigError) as error:
        apply_env(AppConfig())
    assert "REDUCTO_VERBOSE" in str(error.value)
    assert "private-value" not in str(error.value)


def test_first_config_wins_without_merging(tmp_path, monkeypatch):
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    (user_dir / ".reducto.yaml").write_text("model: user-model\n")
    monkeypatch.setattr(Path, "home", lambda: user_dir)
    monkeypatch.chdir(tmp_path)
    assert load_config().model == "user-model"
    Path(".reducto.yaml").write_text("verbose: true\n")
    assert load_config().model == ""
    assert load_config().verbose is True


def test_services_preserve_resolved_config(tmp_path, monkeypatch):
    from reducto.services import App

    monkeypatch.setenv("REDUCTO_MODEL", "env-model")
    monkeypatch.setenv("REDUCTO_VERBOSE", "true")
    monkeypatch.setenv("REDUCTO_PREFER_LOCAL", "false")
    cfg = AppConfig(model="cli-model", verbose=False, prefer_local=True)
    service = App(str(tmp_path), cfg)
    assert service.cfg == cfg
    assert service.llm.model_override == "cli-model"
    service.cfg.include_patterns.append("*.txt")
    assert cfg.include_patterns == ["*.py"]


def test_services_without_config_load_environment(tmp_path, monkeypatch):
    from reducto.services import App

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("REDUCTO_MODEL", "env-model")
    assert App(str(tmp_path)).cfg.model == "env-model"
