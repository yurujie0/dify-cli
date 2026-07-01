from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from .errors import SchemaNotFoundError

SCHEMAS_DIR = Path(__file__).resolve().parent.parent / "schemas"


def available_versions() -> list[str]:
    return sorted(p.stem[1:] for p in SCHEMAS_DIR.glob("v*.json"))


@lru_cache(maxsize=None)
def load_bundle(dsl_version: str) -> dict:
    path = SCHEMAS_DIR / f"v{dsl_version}.json"
    if not path.exists():
        raise SchemaNotFoundError(dsl_version, available_versions())
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def bundle_dsl_version(dsl_version: str) -> str:
    return load_bundle(dsl_version)["dsl_version"]


def node_types(dsl_version: str) -> list[str]:
    return sorted(load_bundle(dsl_version)["node_types"].keys())


def get_node_schema(dsl_version: str, node_type: str) -> dict:
    bundle = load_bundle(dsl_version)
    types = bundle["node_types"]
    if node_type not in types:
        raise SchemaNotFoundError(
            dsl_version,
            available_versions(),
        )
    return types[node_type]


def top_schema(dsl_version: str) -> dict:
    return load_bundle(dsl_version)["top_schema"]


_DEFAULTS_CACHE: dict[str, dict[str, Any] | None] = {}


def _load_defaults_bundle(dsl_version: str) -> dict | None:
    if dsl_version in _DEFAULTS_CACHE:
        return _DEFAULTS_CACHE[dsl_version]
    path = SCHEMAS_DIR / f"defaults-v{dsl_version}.json"
    bundle: dict | None = None
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            bundle = json.load(f)
    _DEFAULTS_CACHE[dsl_version] = bundle
    return bundle


def get_node_defaults(dsl_version: str, node_type: str) -> dict[str, Any] | None:
    bundle = _load_defaults_bundle(dsl_version)
    if not bundle:
        return None
    return bundle.get("node_defaults", {}).get(node_type)
