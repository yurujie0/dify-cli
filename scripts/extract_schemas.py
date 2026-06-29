"""Extract Dify DSL node schemas into a versioned JSON bundle.

Run from the repo root with the api environment available:

    uv run --project api python cli/scripts/extract_schemas.py --out cli/dify_cli/schemas/v0.5.0.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

TOP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["version", "kind", "app"],
    "properties": {
        "version": {"type": "string"},
        "kind": {"type": "string"},
        "app": {
            "type": "object",
            "required": ["name", "mode"],
            "properties": {
                "name": {"type": "string"},
                "mode": {"type": "string"},
                "icon": {"type": "string"},
                "icon_background": {"type": "string"},
                "description": {"type": "string"},
                "use_icon_as_answer_icon": {"type": "boolean"},
            },
        },
        "workflow": {
            "type": "object",
            "properties": {
                "graph": {
                    "type": "object",
                    "properties": {
                        "nodes": {"type": "array"},
                        "edges": {"type": "array"},
                        "viewport": {"type": "object"},
                    },
                },
                "environment_variables": {"type": "array"},
                "conversation_variables": {"type": "array"},
                "features": {"type": "object"},
            },
        },
        "model_config": {"type": "object"},
        "dependencies": {"type": "array"},
    },
}


def extract() -> dict[str, Any]:
    from core.workflow.nodes.base.entities import BaseNodeData
    from core.workflow.nodes.node_mapping import NODE_TYPE_CLASSES_MAPPING
    from services.app_dsl_service import CURRENT_DSL_VERSION

    node_types: dict[str, Any] = {}
    skipped: list[str] = []
    for node_type, version_map in NODE_TYPE_CLASSES_MAPPING.items():
        node_cls = version_map.get("latest") or next(iter(version_map.values()))
        if node_cls is None:
            skipped.append(str(node_type))
            continue
        data_cls = node_cls._node_data_type
        if data_cls is None or data_cls is BaseNodeData:
            schema = BaseNodeData.model_json_schema()
        else:
            try:
                schema = data_cls.model_json_schema()
            except Exception as e:  # noqa: BLE001
                skipped.append(f"{node_type} ({e})")
                continue
        node_types[str(node_type)] = schema

    return {
        "dsl_version": CURRENT_DSL_VERSION,
        "top_schema": TOP_SCHEMA,
        "node_types": node_types,
        "skipped": skipped,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, type=Path, help="Output JSON path")
    args = ap.parse_args()

    bundle = extract()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")

    n = len(bundle["node_types"])
    skipped = bundle.get("skipped", [])
    print(f"Wrote {args.out} (dsl_version={bundle['dsl_version']}, node_types={n})", file=sys.stderr)
    if skipped:
        print(f"Skipped: {', '.join(skipped)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
