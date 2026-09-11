"""Configuration loading."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import ValidationError

from reducto.models import AppConfig


class ConfigError(ValueError):
    """Invalid configuration, safe to display without exposing setting values."""


def load_config(config_path: str | None = None) -> AppConfig:
    cfg = AppConfig()
    paths: list[Path] = []
    if config_path is not None:
        paths.append(Path(config_path))
    else:
        paths.extend([Path(".reducto.yaml"), Path.home() / ".reducto.yaml"])

    for p in paths:
        try:
            source = p.read_text(encoding="utf-8")
        except FileNotFoundError:
            if config_path is None:
                continue
            raise ConfigError(f"Configuration file not found: {p}") from None
        except OSError, UnicodeError:
            raise ConfigError(f"Cannot read configuration file: {p}") from None
        try:
            data = yaml.safe_load(source)
        except yaml.YAMLError as error:
            mark = getattr(error, "problem_mark", None)
            location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
            raise ConfigError(f"Invalid YAML in {p}{location}") from None
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise ConfigError(f"Configuration must be a mapping: {p}")
        try:
            return AppConfig.model_validate({**cfg.model_dump(), **data})
        except (ValidationError, TypeError) as error:
            fields = ""
            if isinstance(error, ValidationError):
                fields = ": " + ", ".join(
                    ".".join(map(str, issue["loc"])) for issue in error.errors()
                )
            raise ConfigError(f"Invalid configuration fields in {p}{fields}") from None
    return cfg


def apply_env(cfg: AppConfig) -> AppConfig:
    if v := os.environ.get("REDUCTO_MODEL"):
        cfg.model = v
    for name, field in (("REDUCTO_PREFER_LOCAL", "prefer_local"), ("REDUCTO_VERBOSE", "verbose")):
        value = os.environ.get(name, "").strip().lower()
        if not value:
            continue
        if value not in ("1", "true", "yes", "on", "0", "false", "no", "off"):
            raise ConfigError(f"{name} must be a boolean (true/false, yes/no, on/off, 1/0)")
        setattr(cfg, field, value in ("1", "true", "yes", "on"))
    return cfg
