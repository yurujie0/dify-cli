from __future__ import annotations

import pytest

from dify_cli.core.spec_validator import validate_spec


def _spec(nodes, edges=None):
    return {"mode": "workflow", "name": "T", "dsl_version": "0.5.0", "nodes": nodes, "edges": edges or []}


def test_validate_clean_workflow():
    spec = _spec([
        {"id": "start", "type": "start", "title": "S",
         "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
        {"id": "code", "type": "code", "title": "C",
         "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
         "outputs": {"r": {"type": "string"}}},
        {"id": "end", "type": "end", "title": "E",
         "outputs": [{"variable": "out", "value_selector": ["code", "r"]}]},
    ])
    assert validate_spec(spec) == []


def test_validate_missing_target_node():
    spec = _spec([
        {"id": "end", "type": "end", "title": "E",
         "outputs": [{"variable": "x", "value_selector": ["nonexistent", "y"]}]},
    ])
    errors = validate_spec(spec)
    assert any("does not exist" in e for e in errors)


def test_validate_undeclared_variable():
    spec = _spec([
        {"id": "start", "type": "start", "title": "S",
         "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
        {"id": "code", "type": "code", "title": "C",
         "variables": [{"variable": "q", "value_selector": ["start", "wrong"]}],
         "outputs": {"r": {"type": "string"}}},
    ])
    errors = validate_spec(spec)
    assert any("does not expose variable 'wrong'" in e for e in errors)


def test_validate_loop_missing_loop_variable():
    spec = _spec([
        {"id": "loop", "type": "loop", "title": "L",
         "children": ["body"]},
        {"id": "body", "type": "code", "title": "B",
         "variables": [{"variable": "c", "value_selector": ["loop", "counter"]}],
         "outputs": {"o": {"type": "string"}}},
    ])
    errors = validate_spec(spec)
    assert any("'loop' (loop) does not expose variable 'counter'" in e for e in errors)


def test_validate_cannot_reference_inside_container_from_outside():
    spec = _spec([
        {"id": "loop", "type": "loop", "title": "L",
         "children": ["body"]},
        {"id": "body", "type": "code", "title": "B",
         "variables": [], "outputs": {"o": {"type": "number"}}},
        {"id": "end", "type": "end", "title": "E",
         "outputs": [{"variable": "x", "value_selector": ["body", "o"]}]},
    ])
    errors = validate_spec(spec)
    assert any("cannot reference 'body'" in e and "inside container" in e for e in errors)


def test_validate_iteration_output_selector_can_reference_child():
    spec = _spec([
        {"id": "start", "type": "start", "title": "S",
         "variables": [{"variable": "items", "label": "I", "type": "text-input"}]},
        {"id": "iter", "type": "iteration", "title": "I",
         "iterator_selector": ["start", "items"], "output_selector": ["inner", "out"],
         "children": ["inner"]},
        {"id": "inner", "type": "code", "title": "In",
         "variables": [{"variable": "item", "value_selector": ["iter", "item"]}],
         "outputs": {"out": {"type": "number"}}},
    ])
    assert validate_spec(spec) == []


def test_validate_iteration_item_from_outside_invalid():
    spec = _spec([
        {"id": "start", "type": "start", "title": "S",
         "variables": [{"variable": "items", "label": "I", "type": "text-input"}]},
        {"id": "iter", "type": "iteration", "title": "I",
         "iterator_selector": ["start", "items"], "output_selector": ["inner", "out"],
         "children": ["inner"]},
        {"id": "inner", "type": "code", "title": "In",
         "variables": [{"variable": "item", "value_selector": ["iter", "item"]}],
         "outputs": {"out": {"type": "number"}}},
        {"id": "end", "type": "end", "title": "E",
         "outputs": [{"variable": "x", "value_selector": ["iter", "item"]}]},
    ])
    errors = validate_spec(spec)
    assert any("does not expose variable 'item'" in e for e in errors)


def test_validate_loop_break_condition_cannot_reference_child():
    spec = _spec([
        {"id": "loop", "type": "loop", "title": "L",
         "break_conditions": [{"variable_selector": ["body", "done"], "comparison_operator": "is", "value": "true"}],
         "children": ["body"]},
        {"id": "body", "type": "code", "title": "B",
         "variables": [], "outputs": {"done": {"type": "boolean"}}},
    ])
    errors = validate_spec(spec)
    assert any("cannot reference 'body'" in e for e in errors)


def test_validate_loop_with_loop_variables_ok():
    spec = _spec([
        {"id": "loop", "type": "loop", "title": "L",
         "loop_variables": [{"label": "counter", "var_type": "number", "value": "0", "value_type": "constant"}],
         "break_conditions": [{"variable_selector": ["loop", "counter"], "comparison_operator": "≥", "value": "5"}],
         "children": ["body"]},
        {"id": "body", "type": "code", "title": "B",
         "variables": [{"variable": "c", "value_selector": ["loop", "counter"]}],
         "outputs": {"o": {"type": "number"}}},
    ])
    assert validate_spec(spec) == []


def test_validate_invalid_node_id():
    spec = _spec([
        {"id": "Bad/Id", "type": "start", "title": "S"},
    ])
    errors = validate_spec(spec)
    assert any("must match [a-z0-9_-]" in e for e in errors)


def test_validate_duplicate_node_id():
    spec = _spec([
        {"id": "dup", "type": "start", "title": "S"},
        {"id": "dup", "type": "end", "title": "E", "outputs": []},
    ])
    errors = validate_spec(spec)
    assert any("duplicate node id" in e for e in errors)


def test_validate_invalid_env_var_value_type():
    spec = {
        "mode": "workflow", "name": "T", "dsl_version": "0.5.0",
        "environment_variables": [{"name": "KEY", "value": "v", "value_type": "text"}],
        "nodes": [{"id": "start", "type": "start", "title": "S"}],
        "edges": [],
    }
    errors = validate_spec(spec)
    assert any("value_type 'text'" in e and "Use 'string'" in e for e in errors)


def test_validate_child_not_in_nodes():
    """Iteration references a child id that doesn't exist in spec.nodes."""
    spec = _spec([
        {"id": "start", "type": "start", "title": "S",
         "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
        {"id": "iter", "type": "iteration", "title": "I",
         "iterator_selector": ["start", "q"], "output_selector": ["missing", "out"],
         "children": ["missing"]},
        {"id": "end", "type": "end", "title": "E", "outputs": []},
    ])
    errors = validate_spec(spec)
    assert any("child 'missing' not found" in e for e in errors)


def test_validate_container_to_child_edge_rejected():
    """Container must not directly connect to its own child."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "iter", "type": "iteration", "title": "I",
             "iterator_selector": ["start", "q"], "output_selector": ["inner", "out"],
             "children": ["inner"]},
            {"id": "inner", "type": "code", "title": "In",
             "variables": [{"variable": "item", "value_selector": ["iter", "item"]}],
             "outputs": {"out": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E", "outputs": []},
        ],
        [
            {"source": "start", "target": "iter"},
            {"source": "iter", "target": "inner"},   # WRONG
            {"source": "iter", "target": "end"},
        ],
    )
    errors = validate_spec(spec)
    assert any("container must not directly connect" in e for e in errors)


def test_validate_child_to_external_edge_rejected():
    """Child inside container must not connect to external node."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "iter", "type": "iteration", "title": "I",
             "iterator_selector": ["start", "q"], "output_selector": ["inner", "out"],
             "children": ["inner"]},
            {"id": "inner", "type": "code", "title": "In",
             "variables": [{"variable": "item", "value_selector": ["iter", "item"]}],
             "outputs": {"out": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E", "outputs": []},
        ],
        [
            {"source": "start", "target": "iter"},
            {"source": "inner", "target": "end"},   # WRONG
        ],
    )
    errors = validate_spec(spec)
    assert any("cannot connect to external" in e and "Use 'iter'" in e for e in errors)


def test_validate_correct_container_edges_ok():
    """Correct wiring: start->iter, iter->end, inner->inner2 (siblings)."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "iter", "type": "iteration", "title": "I",
             "iterator_selector": ["start", "q"], "output_selector": ["inner2", "out"],
             "children": ["inner", "inner2"]},
            {"id": "inner", "type": "code", "title": "A",
             "variables": [{"variable": "item", "value_selector": ["iter", "item"]}],
             "outputs": {"mid": {"type": "string"}}},
            {"id": "inner2", "type": "code", "title": "B",
             "variables": [{"variable": "mid", "value_selector": ["inner", "mid"]}],
             "outputs": {"out": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E", "outputs": []},
        ],
        [
            {"source": "start", "target": "iter"},
            {"source": "inner", "target": "inner2"},   # sibling edge OK
            {"source": "iter", "target": "end"},        # container -> external OK
        ],
    )
    assert validate_spec(spec) == []
