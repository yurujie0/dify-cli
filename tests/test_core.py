from __future__ import annotations

import json
from pathlib import Path

import pytest

from dify_cli.core import dsl as dsl_mod
from dify_cli.core import graph as graph_mod
from dify_cli.core.errors import NodeValidationError
from dify_cli.core.node_builder import apply_fields, build_node, parse_field_value
from dify_cli.core.schema_store import available_versions, get_node_schema, load_bundle

DSL_VERSION = "0.5.0"


def test_available_versions_includes_050():
    assert "0.5.0" in available_versions()


def test_bundle_shape():
    b = load_bundle(DSL_VERSION)
    assert b["dsl_version"] == DSL_VERSION
    assert "top_schema" in b
    assert "node_types" in b
    assert "llm" in b["node_types"]


def test_init_skeleton_workflow():
    doc = dsl_mod.init_skeleton(mode="workflow", name="t", dsl_version=DSL_VERSION)
    assert doc.data["version"] == DSL_VERSION
    assert doc.data["app"]["mode"] == "workflow"
    assert doc.graph["nodes"] == []
    assert doc.graph["edges"] == []


def test_init_skeleton_rejects_bad_mode():
    with pytest.raises(dsl_mod.DslLoadError):
        dsl_mod.init_skeleton(mode="bogus", name="t", dsl_version=DSL_VERSION)


def test_parse_field_value_json():
    assert parse_field_value('{"a": 1}') == {"a": 1}
    assert parse_field_value('[1, 2]') == [1, 2]
    assert parse_field_value("plain") == "plain"


def test_parse_field_value_from_file(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("import json\nresult = {'x': 1}\n", encoding="utf-8")
    val = parse_field_value(f"@{f}")
    assert val == "import json\nresult = {'x': 1}\n"


def test_apply_fields_dotted():
    target: dict = {}
    apply_fields(target, ["model.name=gpt-4o", "model.mode=chat"])
    assert target == {"model": {"name": "gpt-4o", "mode": "chat"}}


def test_build_node_validates_llm():
    node = build_node(
        node_type="llm",
        dsl_version=DSL_VERSION,
        title="T",
        fields=[
            "model.provider=openai",
            "model.name=gpt-4o",
            "model.mode=chat",
            'context={"enabled": false}',
            'prompt_template=[{"role":"user","text":"hi"}]',
        ],
    )
    assert node["type"] == "custom"
    assert node["data"]["type"] == "llm"
    assert node["data"]["model"]["name"] == "gpt-4o"
    assert node["positionAbsolute"] == node["position"]
    assert node["width"] == 244
    assert node["sourcePosition"] == "right"
    assert node["targetPosition"] == "left"


def test_build_node_uses_frontend_defaults():
    node = build_node(
        node_type="start",
        dsl_version=DSL_VERSION,
        title="Start",
    )
    assert node["data"]["variables"] == []


def test_build_node_layers_frontend_defaults():
    node = build_node(
        node_type="llm",
        dsl_version=DSL_VERSION,
        title="T",
        fields=[
            "model.name=gpt-4o",
        ],
    )
    # User field overlays frontend default
    assert node["data"]["model"]["name"] == "gpt-4o"
    # Frontend defaults preserved where user didn't override
    assert node["data"]["model"]["mode"] == "chat"
    assert node["data"]["model"]["completion_params"]["temperature"] == 0.7
    assert node["data"]["context"]["enabled"] is False
    assert node["data"]["prompt_template"][0]["role"] == "system"


def test_build_node_patches_if_else_conditions():
    node = build_node(
        node_type="if-else",
        dsl_version=DSL_VERSION,
        title="Branch",
        fields=[
            'cases=[{"case_id":"true","logical_operator":"and","conditions":[{"variable_selector":["start-1","input"],"comparison_operator":"contains","value":"hi"}]}]',
        ],
    )
    cond = node["data"]["cases"][0]["conditions"][0]
    assert "id" in cond and isinstance(cond["id"], str) and len(cond["id"]) > 0
    assert cond["varType"] == "string"


def test_build_node_patches_loop_break_conditions():
    node = build_node(
        node_type="loop",
        dsl_version=DSL_VERSION,
        title="Loop",
        fields=[
            'break_conditions=[{"variable_selector":["start-1","x"],"comparison_operator":">","value":"10"}]',
        ],
    )
    cond = node["data"]["break_conditions"][0]
    assert "id" in cond and len(cond["id"]) > 0
    assert cond["varType"] == "string"


def test_build_node_patches_loop_variables():
    node = build_node(
        node_type="loop",
        dsl_version=DSL_VERSION,
        title="Loop",
        fields=[
            'loop_variables=[{"label":"i","var_type":"string","value_type":"constant","value":"0"}]',
        ],
    )
    lv = node["data"]["loop_variables"][0]
    assert "id" in lv and len(lv["id"]) > 0


def test_build_node_patches_knowledge_retrieval_metadata_conditions():
    node = build_node(
        node_type="knowledge-retrieval",
        dsl_version=DSL_VERSION,
        title="KR",
        fields=[
            'metadata_filtering_conditions={"logical_operator":"and","conditions":[{"name":"title","comparison_operator":"is"}]}',
        ],
    )
    cond = node["data"]["metadata_filtering_conditions"]["conditions"][0]
    assert "id" in cond and len(cond["id"]) > 0


def test_build_node_normalizes_code_language_python():
    node = build_node(
        node_type="code",
        dsl_version=DSL_VERSION,
        title="Code",
        fields=[
            "code_language=python",
            "code=def main(): return {}",
            'variables=[]',
            'outputs={}',
        ],
    )
    assert node["data"]["code_language"] == "python3"


def test_build_node_uses_custom_iteration_start_type():
    node = build_node(node_type="iteration-start", dsl_version=DSL_VERSION, title="Iter Start")
    assert node["type"] == "custom-iteration-start"


def test_build_node_uses_custom_loop_start_type():
    node = build_node(node_type="loop-start", dsl_version=DSL_VERSION, title="Loop Start")
    assert node["type"] == "custom-loop-start"


def test_build_node_rejects_bad_enum():
    with pytest.raises(NodeValidationError) as exc:
        build_node(
            node_type="llm",
            dsl_version=DSL_VERSION,
            title="T",
            fields=[
                "model.provider=openai",
                "model.name=gpt-4o",
                "model.mode=bogus",
                'context={"enabled": false}',
                'prompt_template=[{"role":"user","text":"hi"}]',
            ],
        )
    assert "model.mode" in str(exc.value)


def test_graph_validate_detects_duplicate_ids():
    doc = dsl_mod.init_skeleton(mode="workflow", name="t", dsl_version=DSL_VERSION)
    graph_mod.add_node(doc, {"id": "n1", "data": {"type": "start", "title": "s"}})
    with pytest.raises(graph_mod.GraphValidationError):
        graph_mod.add_node(doc, {"id": "n1", "data": {"type": "end", "title": "e"}})


def test_graph_validate_detects_dangling_edge():
    doc = dsl_mod.init_skeleton(mode="workflow", name="t", dsl_version=DSL_VERSION)
    graph_mod.add_node(doc, {"id": "n1", "data": {"type": "start", "title": "s"}})
    doc.edges.append({"id": "e1", "source": "n1", "target": "missing"})
    errors = graph_mod.validate_graph(doc)
    assert any("missing" in e for e in errors)
