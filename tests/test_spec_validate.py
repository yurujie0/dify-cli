from __future__ import annotations

import pytest

from dify_cli.core.spec_validator import validate_spec


def _spec(nodes, edges=None):
    return {"mode": "workflow", "name": "T", "dsl_version": "0.5.0", "nodes": nodes, "edges": edges or []}


def test_validate_clean_workflow():
    spec = _spec([
        {"id": "start", "type": "start", "title": "S", "fields": {"variables": [{"variable": "q", "label": "Q", "type": "text-input"}]}},
        {"id": "code", "type": "code", "title": "C", "fields": {
            "code_language": "python3", "code": "def main(q): return {'r': q}",
            "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
            "outputs": {"r": {"type": "string"}},
        }},
        {"id": "end", "type": "end", "title": "E", "fields": {
            "outputs": [{"variable": "out", "value_selector": ["code", "r"]}],
        }},
    ])
    assert validate_spec(spec) == []


def test_validate_missing_target_node():
    spec = _spec([
        {"id": "end", "type": "end", "title": "E", "fields": {
            "outputs": [{"variable": "x", "value_selector": ["nonexistent", "y"]}],
        }},
    ])
    errors = validate_spec(spec)
    assert any("does not exist" in e for e in errors)


def test_validate_undeclared_variable():
    spec = _spec([
        {"id": "start", "type": "start", "title": "S", "fields": {"variables": [{"variable": "q", "label": "Q", "type": "text-input"}]}},
        {"id": "code", "type": "code", "title": "C", "fields": {
            "code_language": "python3", "code": "def main(q): return {'r': q}",
            "variables": [{"variable": "q", "value_selector": ["start", "wrong"]}],
            "outputs": {"r": {"type": "string"}},
        }},
    ])
    errors = validate_spec(spec)
    assert any("does not expose variable 'wrong'" in e for e in errors)


def test_validate_loop_missing_loop_variable():
    """spec6-style error: loopbody references loop.counter but loop has no loop_variables."""
    spec = _spec([
        {"id": "loop", "type": "loop", "title": "L", "fields": {"loop_start_node_id": "loopstart"},
         "children": [
            {"id": "body", "type": "code", "title": "B", "fields": {
                "code_language": "python3", "code": "def main(c): return {}",
                "variables": [{"variable": "c", "value_selector": ["loop", "counter"]}],
                "outputs": {"o": {"type": "string"}},
            }},
        ]},
    ])
    errors = validate_spec(spec)
    assert any("'loop' (loop) does not expose variable 'counter'" in e for e in errors)


def test_validate_cannot_reference_inside_container_from_outside():
    """spec6-style error: end references loopbody (inside loop) from outside."""
    spec = _spec([
        {"id": "loop", "type": "loop", "title": "L", "fields": {"loop_start_node_id": "ls"},
         "children": [
            {"id": "body", "type": "code", "title": "B", "fields": {
                "code_language": "python3", "code": "def main(): return {'o': 1}",
                "variables": [], "outputs": {"o": {"type": "number"}},
            }},
        ]},
        {"id": "end", "type": "end", "title": "E", "fields": {
            "outputs": [{"variable": "x", "value_selector": ["body", "o"]}],
        }},
    ])
    errors = validate_spec(spec)
    assert any("cannot reference 'body'" in e and "inside container" in e for e in errors)


def test_validate_iteration_output_selector_can_reference_child():
    """iteration.output_selector legitimately points at an inner node."""
    spec = _spec([
        {"id": "start", "type": "start", "title": "S", "fields": {"variables": [{"variable": "items", "label": "I", "type": "text-input"}]}},
        {"id": "iter", "type": "iteration", "title": "I", "fields": {
            "iterator_selector": ["start", "items"],
            "output_selector": ["inner", "out"],
        }, "children": [
            {"id": "inner", "type": "code", "title": "In", "fields": {
                "code_language": "python3", "code": "def main(item): return {'out': 1}",
                "variables": [{"variable": "item", "value_selector": ["iter", "item"]}],
                "outputs": {"out": {"type": "number"}},
            }},
        ]},
    ])
    errors = validate_spec(spec)
    assert errors == []


def test_validate_iteration_item_from_outside_invalid():
    """Outside node can't reference iter.item (only iter.output)."""
    spec = _spec([
        {"id": "start", "type": "start", "title": "S", "fields": {"variables": [{"variable": "items", "label": "I", "type": "text-input"}]}},
        {"id": "iter", "type": "iteration", "title": "I", "fields": {
            "iterator_selector": ["start", "items"], "output_selector": ["inner", "out"],
        }, "children": [
            {"id": "inner", "type": "code", "title": "In", "fields": {
                "code_language": "python3", "code": "def main(item): return {'out': 1}",
                "variables": [{"variable": "item", "value_selector": ["iter", "item"]}],
                "outputs": {"out": {"type": "number"}},
            }},
        ]},
        {"id": "end", "type": "end", "title": "E", "fields": {
            "outputs": [{"variable": "x", "value_selector": ["iter", "item"]}],
        }},
    ])
    errors = validate_spec(spec)
    assert any("does not expose variable 'item'" in e for e in errors)


def test_validate_loop_break_condition_cannot_reference_child():
    """break_conditions should reference loop's own variables, not child outputs."""
    spec = _spec([
        {"id": "loop", "type": "loop", "title": "L",
         "fields": {"loop_start_node_id": "ls",
                    "break_conditions": [{"variable_selector": ["body", "done"], "comparison_operator": "is", "value": "true"}]},
         "children": [
            {"id": "body", "type": "code", "title": "B", "fields": {
                "code_language": "python3", "code": "def main(): return {'done': True}",
                "variables": [], "outputs": {"done": {"type": "boolean"}},
            }},
        ]},
    ])
    errors = validate_spec(spec)
    assert any("cannot reference 'body'" in e for e in errors)
