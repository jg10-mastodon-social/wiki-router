import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    notes: Path
    state: Path
    pod_base: str | None


def load_config(environ: Mapping[str, str] | None = None) -> Config:
    if environ is None:
        environ = os.environ

    notes = environ.get("WIKI_ROUTER_NOTES")
    if not notes:
        raise ConfigError("WIKI_ROUTER_NOTES is not set")

    state = environ.get("WIKI_ROUTER_HOME")
    if not state:
        raise ConfigError("WIKI_ROUTER_HOME is not set")

    pod_base = environ.get("WIKI_ROUTER_POD_BASE") or None
    if pod_base is not None:
        pod_base = pod_base.rstrip("/")

    return Config(notes=Path(notes), state=Path(state), pod_base=pod_base)
