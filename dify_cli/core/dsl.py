from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .errors import DslLoadError

DEFAULT_DSL_VERSION = "0.5.0"

_APP_MODES = {"chat", "completion", "advanced-chat", "workflow", "agent-chat"}


class DslDocument:
    def __init__(self, data: dict[str, Any]):
        self.data = data

    @property
    def version(self) -> str:
        return str(self.data.get("version", ""))

    @property
    def kind(self) -> str:
        return str(self.data.get("kind", "app"))

    @property
    def app(self) -> dict[str, Any]:
        return self.data.setdefault("app", {})

    @property
    def app_mode(self) -> str:
        return str(self.app.get("mode", ""))

    @property
    def workflow(self) -> dict[str, Any] | None:
        return self.data.get("workflow")

    def ensure_workflow(self) -> dict[str, Any]:
        wf = self.data.setdefault("workflow", {})
        wf.setdefault("graph", {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}})
        wf.setdefault("environment_variables", [])
        wf.setdefault("conversation_variables", [])
        wf.setdefault("features", {})
        graph = wf["graph"]
        graph.setdefault("nodes", [])
        graph.setdefault("edges", [])
        return wf

    @property
    def graph(self) -> dict[str, Any]:
        return self.ensure_workflow()["graph"]

    @property
    def nodes(self) -> list[dict[str, Any]]:
        return self.graph["nodes"]

    @property
    def edges(self) -> list[dict[str, Any]]:
        return self.graph["edges"]

    @property
    def environment_variables(self) -> list[dict[str, Any]]:
        return self.ensure_workflow()["environment_variables"]

    @property
    def conversation_variables(self) -> list[dict[str, Any]]:
        return self.ensure_workflow()["conversation_variables"]

    def to_yaml(self) -> str:
        return yaml.safe_dump(deepcopy(self.data), allow_unicode=True, sort_keys=False, width=10000)


def load(path: str | Path) -> DslDocument:
    p = Path(path)
    if not p.exists():
        raise DslLoadError(f"DSL file not found: {p}")
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise DslLoadError(f"Invalid YAML in {p}: {e}") from e
    if not isinstance(raw, dict):
        raise DslLoadError(f"DSL root must be a mapping, got {type(raw).__name__}")
    if "version" not in raw:
        raise DslLoadError("Missing required top-level key: version")
    if "app" not in raw:
        raise DslLoadError("Missing required top-level key: app")
    if "workflow" not in raw and "model_config" not in raw:
        raise DslLoadError("DSL must contain either 'workflow' or 'model_config'")
    return DslDocument(raw)


def save(path: str | Path, doc: DslDocument) -> None:
    Path(path).write_text(doc.to_yaml(), encoding="utf-8")


def init_skeleton(
    *,
    mode: str,
    name: str,
    dsl_version: str = DEFAULT_DSL_VERSION,
    description: str = "",
) -> DslDocument:
    if mode not in _APP_MODES:
        raise DslLoadError(f"Unsupported app mode {mode!r}. Valid: {sorted(_APP_MODES)}")
    data: dict[str, Any] = {
        "version": dsl_version,
        "kind": "app",
        "app": {
            "name": name,
            "mode": mode,
            "icon": "🤖",
            "icon_background": "#FFEAD5",
            "description": description,
            "use_icon_as_answer_icon": False,
        },
    }
    if mode in {"advanced-chat", "workflow"}:
        data["workflow"] = {
            "graph": {
                "nodes": [],
                "edges": [],
                "viewport": {"x": 0, "y": 0, "zoom": 1},
            },
            "features": {},
            "environment_variables": [],
            "conversation_variables": [],
        }
    else:
        data["model_config"] = {}
    return DslDocument(data)
