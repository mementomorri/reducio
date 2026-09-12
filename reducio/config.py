"""Configuration loading."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import ValidationError

from reducio.models import AppConfig


class ConfigError(ValueError):
    """Invalid configuration, safe to display without exposing setting values."""


def load_config(config_path: str | None = None) -> AppConfig:
    cfg = AppConfig()
    paths: list[Path] = []
    if config_path is not None:
        paths.append(Path(config_path))
    else:
        paths.extend([Path(".reducio.yaml"), Path.home() / ".reducio.yaml"])

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
        if {"prefer_local", "prefer_remote", "model_tiers", "tier"}.intersection(data):
            raise ConfigError(
                "Model tiers/preferences were removed; set llm_api and model explicitly"
            )
        if {"api_key", "llm_api_key"}.intersection(data):
            raise ConfigError("Use REDUCIO_API_KEY in the environment, not configuration")
        if "commit_changes" in data:
            raise ConfigError("commit_changes was removed; remove this setting and commit manually")
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
    if "REDUCIO_PREFER_LOCAL" in os.environ or "REDUCIO_PREFER_REMOTE" in os.environ:
        raise ConfigError("Model preferences were removed; use REDUCIO_LLM_API and REDUCIO_MODEL")
    values = cfg.model_dump()
    for name in (
        "model",
        "llm_api",
        "llm_base_url",
        "llm_timeout_seconds",
        "llm_max_tokens",
        "check_fail_on",
    ):
        if value := os.environ.get("REDUCIO_" + name.upper()):
            values[name] = value
    value = os.environ.get("REDUCIO_VERBOSE", "").strip().lower()
    if value:
        if value not in ("1", "true", "yes", "on", "0", "false", "no", "off"):
            raise ConfigError("REDUCIO_VERBOSE must be a boolean (true/false, yes/no, on/off, 1/0)")
        values["verbose"] = value in ("1", "true", "yes", "on")
    try:
        return AppConfig.model_validate(values)
    except ValidationError, TypeError:
        raise ConfigError(
            "Invalid REDUCIO environment configuration; check API, timeout and gate settings"
        ) from None
