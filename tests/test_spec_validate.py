from __future__ import annotations

import pytest

from dify_cli.core.spec_validator import validate_spec


def _spec(nodes, edges=None):
    return {"mode": "workflow", "name": "T", "dsl_version": "0.5.0", "nodes": nodes, "edges": edges or []}


def test_validate_clean_workflow():
    spec = _spec([
        {"id": "start", "type": "start", "title": "S",
         "variables": [{"variable": "q", "label": "Q", "type": "text-input"}],
         "fields": {}},
        {"id": "code", "type": "code", "title": "C",
         "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
         "outputs": {"r": {"type": "string"}},
         "fields": {"code_language": "python3", "code": "def main(q): return {'r': q}"}},
        {"id": "end", "type": "end", "title": "E",
         "outputs": [{"variable": "out", "value_selector": ["code", "r"]}],
         "fields": {}},
    ])
    assert validate_spec(spec) == []


def test_validate_missing_target_node():
    spec = _spec([
        {"id": "end", "type": "end", "title": "E",
         "outputs": [{"variable": "x", "value_selector": ["nonexistent", "y"]}],
         "fields": {}},
    ])
    errors = validate_spec(spec)
    assert any("does not exist" in e for e in errors)


def test_validate_undeclared_variable():
    spec = _spec([
        {"id": "start", "type": "start", "title": "S",
         "variables": [{"variable": "q", "label": "Q", "type": "text-input"}], "fields": {}},
        {"id": "code", "type": "code", "title": "C",
         "variables": [{"variable": "q", "value_selector": ["start", "wrong"]}],
         "outputs": {"r": {"type": "string"}}, "fields": {}},
    ])
    errors = validate_spec(spec)
    assert any("does not expose variable 'wrong'" in e for e in errors)


def test_validate_loop_missing_loop_variable():
    """loopbody references loop.counter but loop has no loop_variables."""
    spec = _spec([
        {"id": "loop", "type": "loop", "title": "L", "fields": {},
         "children": [
            {"id": "body", "type": "code", "title": "B",
             "variables": [{"variable": "c", "value_selector": ["loop", "counter"]}],
             "outputs": {"o": {"type": "string"}}, "fields": {}},
        ]},
    ])
    errors = validate_spec(spec)
    assert any("'loop' (loop) does not expose variable 'counter'" in e for e in errors)


def test_validate_cannot_reference_inside_container_from_outside():
    """end references body (inside loop) from outside."""
    spec = _spec([
        {"id": "loop", "type": "loop", "title": "L", "fields": {},
         "children": [
            {"id": "body", "type": "code", "title": "B",
             "variables": [], "outputs": {"o": {"type": "number"}}, "fields": {}},
        ]},
        {"id": "end", "type": "end", "title": "E",
         "outputs": [{"variable": "x", "value_selector": ["body", "o"]}], "fields": {}},
    ])
    errors = validate_spec(spec)
    assert any("cannot reference 'body'" in e and "inside container" in e for e in errors)


def test_validate_iteration_output_selector_can_reference_child():
    """iteration.output_selector legitimately points at an inner node."""
    spec = _spec([
        {"id": "start", "type": "start", "title": "S",
         "variables": [{"variable": "items", "label": "I", "type": "text-input"}], "fields": {}},
        {"id": "iter", "type": "iteration", "title": "I",
         "iterator_selector": ["start", "items"], "output_selector": ["inner", "out"],
         "fields": {}, "children": [
            {"id": "inner", "type": "code", "title": "In",
             "variables": [{"variable": "item", "value_selector": ["iter", "item"]}],
             "outputs": {"out": {"type": "number"}}, "fields": {}},
        ]},
    ])
    errors = validate_spec(spec)
    assert errors == []


def test_validate_iteration_item_from_outside_invalid():
    """Outside node can't reference iter.item (only iter.output)."""
    spec = _spec([
        {"id": "start", "type": "start", "title": "S",
         "variables": [{"variable": "items", "label": "I", "type": "text-input"}], "fields": {}},
        {"id": "iter", "type": "iteration", "title": "I",
         "iterator_selector": ["start", "items"], "output_selector": ["inner", "out"],
         "fields": {}, "children": [
            {"id": "inner", "type": "code", "title": "In",
             "variables": [{"variable": "item", "value_selector": ["iter", "item"]}],
             "outputs": {"out": {"type": "number"}}, "fields": {}},
        ]},
        {"id": "end", "type": "end", "title": "E",
         "outputs": [{"variable": "x", "value_selector": ["iter", "item"]}], "fields": {}},
    ])
    errors = validate_spec(spec)
    assert any("does not expose variable 'item'" in e for e in errors)


def test_validate_loop_break_condition_cannot_reference_child():
    """break_conditions should reference loop's own variables, not child outputs."""
    spec = _spec([
        {"id": "loop", "type": "loop", "title": "L",
         "break_conditions": [{"variable_selector": ["body", "done"], "comparison_operator": "is", "value": "true"}],
         "fields": {}, "children": [
            {"id": "body", "type": "code", "title": "B",
             "variables": [], "outputs": {"done": {"type": "boolean"}}, "fields": {}},
        ]},
    ])
    errors = validate_spec(spec)
    assert any("cannot reference 'body'" in e for e in errors)


def test_validate_loop_with_loop_variables_ok():
    """loop with loop_variables declared; child references one - valid."""
    spec = _spec([
        {"id": "loop", "type": "loop", "title": "L",
         "loop_variables": [{"label": "counter", "var_type": "number", "value": "0", "value_type": "constant"}],
         "break_conditions": [{"variable_selector": ["loop", "counter"], "comparison_operator": "≥", "value": "5"}],
         "fields": {}, "children": [
            {"id": "body", "type": "code", "title": "B",
             "variables": [{"variable": "c", "value_selector": ["loop", "counter"]}],
             "outputs": {"o": {"type": "number"}}, "fields": {}},
        ]},
    ])
    assert validate_spec(spec) == []
