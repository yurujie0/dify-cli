from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from dify_cli.commands.apply import apply as apply_cmd
from dify_cli.core.errors import DifyCliError

DSL_VERSION = "0.5.0"


def _write_spec(tmp_path: Path, spec: dict) -> Path:
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(spec), encoding="utf-8")
    return p


def _run_apply(tmp_path: Path, spec: dict) -> Path:
    spec_path = _write_spec(tmp_path, spec)
    out = tmp_path / "dsl.yaml"
    apply_cmd(spec=spec_path, file=out, force=True)
    return out


def test_apply_basic_workflow(tmp_path):
    spec = {
        "mode": "workflow", "name": "T", "dsl_version": DSL_VERSION,
        "nodes": [
            {"id": "start", "type": "start", "title": "Start"},
            {"id": "end", "type": "end", "title": "End", "fields": {"outputs": []}},
        ],
        "edges": [{"source": "start", "target": "end"}],
    }
    out = _run_apply(tmp_path, spec)
    doc = yaml.safe_load(out.read_text())
    g = doc["workflow"]["graph"]
    assert len(g["nodes"]) == 2
    assert {n["id"] for n in g["nodes"]} == {"start", "end"}
    assert g["edges"][0]["source"] == "start"
    assert g["edges"][0]["target"] == "end"
    # Stable edge id (deterministic)
    assert g["edges"][0]["id"] == "start-end"


def test_apply_at_file_for_code(tmp_path):
    code_file = tmp_path / "code.py"
    code_file.write_text("def main():\n    return {'r': 1}\n", encoding="utf-8")
    spec = {
        "mode": "workflow", "name": "T", "dsl_version": DSL_VERSION,
        "nodes": [
            {"id": "start", "type": "start", "title": "Start"},
            {"id": "code", "type": "code", "title": "Node", "title": "Node", "fields": {
                "code_language": "python3",
                "code": f"@{code_file}",
                "variables": [], "outputs": {"r": {"type": "number"}},
            }},
            {"id": "end", "type": "end", "title": "End", "fields": {"outputs": []}},
        ],
        "edges": [{"source": "start", "target": "code"}, {"source": "code", "target": "end"}],
    }
    out = _run_apply(tmp_path, spec)
    doc = yaml.safe_load(out.read_text())
    code_node = [n for n in doc["workflow"]["graph"]["nodes"] if n["id"] == "code"][0]
    assert "def main():" in code_node["data"]["code"]
    assert "\n" in code_node["data"]["code"]


def test_apply_iteration_with_children(tmp_path):
    spec = {
        "mode": "workflow", "name": "T", "dsl_version": DSL_VERSION,
        "nodes": [
            {"id": "start", "type": "start", "title": "Start", "fields": {
                "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]}},
            {"id": "iter", "type": "iteration", "title": "Node", "fields": {
                "iterator_selector": ["start", "q"],
                "output_selector": ["inner", "out"],
            }, "children": [
                {"id": "inner", "type": "code", "title": "Node", "fields": {
                    "code_language": "python3", "code": "def main(): return {}",
                    "variables": [], "outputs": {"out": {"type": "string"}},
                }},
            ]},
            {"id": "end", "type": "end", "title": "End", "fields": {"outputs": []}},
        ],
        "edges": [{"source": "start", "target": "iter"}, {"source": "iter", "target": "end"}],
    }
    out = _run_apply(tmp_path, spec)
    doc = yaml.safe_load(out.read_text())
    nodes = doc["workflow"]["graph"]["nodes"]
    iter_node = [n for n in nodes if n["id"] == "iter"][0]
    start_node = [n for n in nodes if n["data"]["type"] == "iteration-start"][0]
    inner = [n for n in nodes if n["id"] == "inner"][0]
    # iteration-start auto-created and linked
    assert iter_node["data"]["start_node_id"] == start_node["id"]
    assert start_node["parentId"] == "iter"
    assert start_node["type"] == "custom-iteration-start"
    # inner child attached to iter
    assert inner["parentId"] == "iter"
    assert inner["data"]["isInIteration"] is True


def test_apply_idempotent(tmp_path):
    spec = {
        "mode": "workflow", "name": "T", "dsl_version": DSL_VERSION,
        "nodes": [
            {"id": "start", "type": "start", "title": "Start", "fields": {
                "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]}},
            {"id": "ifelse", "type": "if-else", "title": "Node", "fields": {
                "cases": [{"case_id": "true", "logical_operator": "and",
                           "conditions": [{"variable_selector": ["start", "q"],
                                           "comparison_operator": "contains", "value": "x"}]}],
            }},
            {"id": "end", "type": "end", "title": "End", "fields": {"outputs": []}},
        ],
        "edges": [
            {"source": "start", "target": "ifelse"},
            {"source": "ifelse", "target": "end", "src_handle": "true"},
        ],
    }
    spec_path = _write_spec(tmp_path, spec)
    out1 = tmp_path / "d1.yaml"
    out2 = tmp_path / "d2.yaml"
    apply_cmd(spec=spec_path, file=out1, force=True)
    apply_cmd(spec=spec_path, file=out2, force=True)
    assert out1.read_text() == out2.read_text()


def test_apply_rejects_duplicate_node_id(tmp_path):
    spec = {
        "mode": "workflow", "name": "T", "dsl_version": DSL_VERSION,
        "nodes": [
            {"id": "dup", "type": "start", "title": "Node", "title": "Node"},
            {"id": "dup", "type": "end", "title": "Dup", "fields": {"outputs": []}},
        ],
        "edges": [],
    }
    with pytest.raises(Exception):
        _run_apply(tmp_path, spec)
