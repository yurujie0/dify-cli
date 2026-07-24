from __future__ import annotations

import pytest

from dify_cli.core.spec_validator import validate_spec


def _spec(nodes, edges=None):
    return {"mode": "workflow", "name": "T", "dsl_version": "0.5.0", "nodes": nodes, "edges": edges or []}


def test_validate_clean_workflow():
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "code", "type": "code", "title": "C",
             "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
             "outputs": {"r": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E",
             "outputs": [{"variable": "out", "value_selector": ["code", "r"]}]},
        ],
        [
            {"source": "start", "target": "code"},
            {"source": "code", "target": "end"},
        ],
    )
    assert validate_spec(spec) == []


def test_validate_missing_edge_between_siblings():
    """Node references another node's output but no edge connects them."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "code1", "type": "code", "title": "C1",
             "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
             "outputs": {"r": {"type": "string"}}},
            {"id": "code2", "type": "code", "title": "C2",
             "variables": [{"variable": "r", "value_selector": ["code1", "r"]}],  # depends on code1
             "outputs": {"out": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E", "outputs": []},
        ],
        [
            {"source": "start", "target": "code1"},
            # MISSING: {"source": "code1", "target": "code2"}
            {"source": "code2", "target": "end"},
        ],
    )
    errors = validate_spec(spec)
    assert any("no edge connects 'code1'" in e and "'code2'" in e for e in errors)


def test_validate_edge_coverage_ok():
    """All variable references have matching edges (direct or transitive)."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "code1", "type": "code", "title": "C1",
             "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
             "outputs": {"r": {"type": "string"}}},
            {"id": "code2", "type": "code", "title": "C2",
             "variables": [{"variable": "r", "value_selector": ["code1", "r"]}],
             "outputs": {"out": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E",
             "outputs": [{"variable": "result", "value_selector": ["code2", "out"]}]},
        ],
        [
            {"source": "start", "target": "code1"},
            {"source": "code1", "target": "code2"},
            {"source": "code2", "target": "end"},
        ],
    )
    assert validate_spec(spec) == []


def test_validate_edge_coverage_transitive_ok():
    """Transitive path is enough: A->B->C, C references A's output."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "mid", "type": "code", "title": "M",
             "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
             "outputs": {"r": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E",
             "outputs": [{"variable": "q", "value_selector": ["start", "q"]}]},  # references start
        ],
        [
            {"source": "start", "target": "mid"},
            {"source": "mid", "target": "end"},
            # end references start, path: start -> mid -> end (transitive)
        ],
    )
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


def test_validate_missing_edge_between_siblings():
    """Node references another node's output but no edge connects them."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "code1", "type": "code", "title": "C1",
             "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
             "outputs": {"r": {"type": "string"}}},
            {"id": "code2", "type": "code", "title": "C2",
             "variables": [{"variable": "r", "value_selector": ["code1", "r"]}],  # depends on code1
             "outputs": {"out": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E", "outputs": []},
        ],
        [
            {"source": "start", "target": "code1"},
            # MISSING: {"source": "code1", "target": "code2"}
            {"source": "code2", "target": "end"},
        ],
    )
    errors = validate_spec(spec)
    assert any("no edge connects 'code1'" in e and "'code2'" in e for e in errors)


def test_validate_edge_coverage_ok():
    """All variable references have matching edges (direct or transitive)."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "code1", "type": "code", "title": "C1",
             "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
             "outputs": {"r": {"type": "string"}}},
            {"id": "code2", "type": "code", "title": "C2",
             "variables": [{"variable": "r", "value_selector": ["code1", "r"]}],
             "outputs": {"out": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E",
             "outputs": [{"variable": "result", "value_selector": ["code2", "out"]}]},
        ],
        [
            {"source": "start", "target": "code1"},
            {"source": "code1", "target": "code2"},
            {"source": "code2", "target": "end"},
        ],
    )
    assert validate_spec(spec) == []


def test_validate_edge_coverage_transitive_ok():
    """Transitive path is enough: A->B->C, C references A's output."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "mid", "type": "code", "title": "M",
             "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
             "outputs": {"r": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E",
             "outputs": [{"variable": "q", "value_selector": ["start", "q"]}]},  # references start
        ],
        [
            {"source": "start", "target": "mid"},
            {"source": "mid", "target": "end"},
            # end references start, path: start -> mid -> end (transitive)
        ],
    )
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


def test_validate_missing_edge_between_siblings():
    """Node references another node's output but no edge connects them."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "code1", "type": "code", "title": "C1",
             "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
             "outputs": {"r": {"type": "string"}}},
            {"id": "code2", "type": "code", "title": "C2",
             "variables": [{"variable": "r", "value_selector": ["code1", "r"]}],  # depends on code1
             "outputs": {"out": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E", "outputs": []},
        ],
        [
            {"source": "start", "target": "code1"},
            # MISSING: {"source": "code1", "target": "code2"}
            {"source": "code2", "target": "end"},
        ],
    )
    errors = validate_spec(spec)
    assert any("no edge connects 'code1'" in e and "'code2'" in e for e in errors)


def test_validate_edge_coverage_ok():
    """All variable references have matching edges (direct or transitive)."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "code1", "type": "code", "title": "C1",
             "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
             "outputs": {"r": {"type": "string"}}},
            {"id": "code2", "type": "code", "title": "C2",
             "variables": [{"variable": "r", "value_selector": ["code1", "r"]}],
             "outputs": {"out": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E",
             "outputs": [{"variable": "result", "value_selector": ["code2", "out"]}]},
        ],
        [
            {"source": "start", "target": "code1"},
            {"source": "code1", "target": "code2"},
            {"source": "code2", "target": "end"},
        ],
    )
    assert validate_spec(spec) == []


def test_validate_edge_coverage_transitive_ok():
    """Transitive path is enough: A->B->C, C references A's output."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "mid", "type": "code", "title": "M",
             "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
             "outputs": {"r": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E",
             "outputs": [{"variable": "q", "value_selector": ["start", "q"]}]},  # references start
        ],
        [
            {"source": "start", "target": "mid"},
            {"source": "mid", "target": "end"},
            # end references start, path: start -> mid -> end (transitive)
        ],
    )
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


def test_validate_missing_edge_between_siblings():
    """Node references another node's output but no edge connects them."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "code1", "type": "code", "title": "C1",
             "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
             "outputs": {"r": {"type": "string"}}},
            {"id": "code2", "type": "code", "title": "C2",
             "variables": [{"variable": "r", "value_selector": ["code1", "r"]}],  # depends on code1
             "outputs": {"out": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E", "outputs": []},
        ],
        [
            {"source": "start", "target": "code1"},
            # MISSING: {"source": "code1", "target": "code2"}
            {"source": "code2", "target": "end"},
        ],
    )
    errors = validate_spec(spec)
    assert any("no edge connects 'code1'" in e and "'code2'" in e for e in errors)


def test_validate_edge_coverage_ok():
    """All variable references have matching edges (direct or transitive)."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "code1", "type": "code", "title": "C1",
             "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
             "outputs": {"r": {"type": "string"}}},
            {"id": "code2", "type": "code", "title": "C2",
             "variables": [{"variable": "r", "value_selector": ["code1", "r"]}],
             "outputs": {"out": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E",
             "outputs": [{"variable": "result", "value_selector": ["code2", "out"]}]},
        ],
        [
            {"source": "start", "target": "code1"},
            {"source": "code1", "target": "code2"},
            {"source": "code2", "target": "end"},
        ],
    )
    assert validate_spec(spec) == []


def test_validate_edge_coverage_transitive_ok():
    """Transitive path is enough: A->B->C, C references A's output."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "mid", "type": "code", "title": "M",
             "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
             "outputs": {"r": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E",
             "outputs": [{"variable": "q", "value_selector": ["start", "q"]}]},  # references start
        ],
        [
            {"source": "start", "target": "mid"},
            {"source": "mid", "target": "end"},
            # end references start, path: start -> mid -> end (transitive)
        ],
    )
    assert validate_spec(spec) == []


def test_validate_ifelse_case_wrong_field_names():
    """Case uses 'id' instead of 'case_id', Condition uses 'operator' instead of 'comparison_operator'."""
    spec = _spec([
        {"id": "start", "type": "start", "title": "S",
         "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
        {"id": "ifelse", "type": "if-else", "title": "B",
         "cases": [{"id": "true", "logical_operator": "and",
                     "conditions": [{"variable_selector": ["start", "q"], "operator": "contains", "value": "x"}]}]},
        {"id": "end", "type": "end", "title": "E", "outputs": []},
    ])
    errors = validate_spec(spec)
    assert any("use 'case_id' not 'id'" in e for e in errors)
    assert any("use 'comparison_operator' not 'operator'" in e for e in errors)


def test_validate_ifelse_nested_variable_selector():
    """variable_selector must be flat array, not nested."""
    spec = _spec([
        {"id": "start", "type": "start", "title": "S",
         "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
        {"id": "ifelse", "type": "if-else", "title": "B",
         "cases": [{"case_id": "true", "logical_operator": "and",
                     "conditions": [{"variable_selector": [["start", "q"]], "comparison_operator": "contains", "value": "x"}]}]},
        {"id": "end", "type": "end", "title": "E", "outputs": []},
    ])
    errors = validate_spec(spec)
    assert any("variable_selector must be a flat array" in e for e in errors)


def test_validate_answer_in_workflow_mode_rejected():
    """answer node is only for advanced-chat, not workflow."""
    spec = _spec([
        {"id": "start", "type": "start", "title": "S"},
        {"id": "answer", "type": "answer", "title": "A",
         "implementation_hint": "reply"},
        {"id": "end", "type": "end", "title": "E", "outputs": []},
    ])
    errors = validate_spec(spec)
    assert any("answer" in e and "advanced-chat" in e for e in errors)


def test_validate_answer_in_advanced_chat_ok():
    """answer node is valid in advanced-chat mode."""
    spec = {
        "mode": "advanced-chat", "name": "T", "dsl_version": "0.5.0",
        "nodes": [
            {"id": "start", "type": "start", "title": "S"},
            {"id": "answer", "type": "answer", "title": "A",
             "implementation_hint": "reply"},
        ],
        "edges": [{"source": "start", "target": "answer"}],
    }
    assert validate_spec(spec) == []


def test_validate_missing_edge_between_siblings():
    """Node references another node's output but no edge connects them."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "code1", "type": "code", "title": "C1",
             "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
             "outputs": {"r": {"type": "string"}}},
            {"id": "code2", "type": "code", "title": "C2",
             "variables": [{"variable": "r", "value_selector": ["code1", "r"]}],  # depends on code1
             "outputs": {"out": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E", "outputs": []},
        ],
        [
            {"source": "start", "target": "code1"},
            # MISSING: {"source": "code1", "target": "code2"}
            {"source": "code2", "target": "end"},
        ],
    )
    errors = validate_spec(spec)
    assert any("no edge connects 'code1'" in e and "'code2'" in e for e in errors)


def test_validate_edge_coverage_ok():
    """All variable references have matching edges (direct or transitive)."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "code1", "type": "code", "title": "C1",
             "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
             "outputs": {"r": {"type": "string"}}},
            {"id": "code2", "type": "code", "title": "C2",
             "variables": [{"variable": "r", "value_selector": ["code1", "r"]}],
             "outputs": {"out": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E",
             "outputs": [{"variable": "result", "value_selector": ["code2", "out"]}]},
        ],
        [
            {"source": "start", "target": "code1"},
            {"source": "code1", "target": "code2"},
            {"source": "code2", "target": "end"},
        ],
    )
    assert validate_spec(spec) == []


def test_validate_edge_coverage_transitive_ok():
    """Transitive path is enough: A->B->C, C references A's output."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "mid", "type": "code", "title": "M",
             "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
             "outputs": {"r": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E",
             "outputs": [{"variable": "q", "value_selector": ["start", "q"]}]},  # references start
        ],
        [
            {"source": "start", "target": "mid"},
            {"source": "mid", "target": "end"},
            # end references start, path: start -> mid -> end (transitive)
        ],
    )
    assert validate_spec(spec) == []


def test_validate_end_in_advanced_chat_rejected():
    """end node is only for workflow, not advanced-chat."""
    spec = {
        "mode": "advanced-chat", "name": "T", "dsl_version": "0.5.0",
        "nodes": [
            {"id": "start", "type": "start", "title": "S"},
            {"id": "end", "type": "end", "title": "E", "outputs": []},
        ],
        "edges": [{"source": "start", "target": "end"}],
    }
    errors = validate_spec(spec)
    assert any("end" in e and "workflow" in e for e in errors)


def test_validate_trigger_in_advanced_chat_rejected():
    """trigger nodes are only for workflow, not advanced-chat."""
    spec = {
        "mode": "advanced-chat", "name": "T", "dsl_version": "0.5.0",
        "nodes": [
            {"id": "start", "type": "start", "title": "S"},
            {"id": "trigger", "type": "trigger-webhook", "title": "T",
             "implementation_hint": "webhook"},
            {"id": "answer", "type": "answer", "title": "A",
             "implementation_hint": "reply"},
        ],
        "edges": [{"source": "trigger", "target": "answer"}],
    }
    errors = validate_spec(spec)
    assert any("trigger-webhook" in e and "workflow" in e for e in errors)


def test_validate_ifelse_case_id_false_rejected():
    """case_id 'false' is the implicit else branch, not an explicit case."""
    spec = _spec([
        {"id": "start", "type": "start", "title": "S",
         "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
        {"id": "ifelse", "type": "if-else", "title": "B",
         "cases": [
             {"case_id": "has_value", "logical_operator": "and",
              "conditions": [{"variable_selector": ["start", "q"], "comparison_operator": "contains", "value": "x"}]},
             {"case_id": "false", "logical_operator": "and", "conditions": []},
         ]},
        {"id": "end", "type": "end", "title": "E", "outputs": []},
    ])
    errors = validate_spec(spec)
    assert any("case_id 'false'" in e and "implicit else" in e for e in errors)


def test_validate_ifelse_edge_wrong_src_handle():
    """src_handle must match a case_id in the if-else node."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "ifelse", "type": "if-else", "title": "B",
             "cases": [{"case_id": "has_value", "logical_operator": "and",
                        "conditions": [{"variable_selector": ["start", "q"], "comparison_operator": "contains", "value": "x"}]}]},
            {"id": "end", "type": "end", "title": "E", "outputs": []},
        ],
        [
            {"source": "ifelse", "target": "end", "src_handle": "true"},  # WRONG
        ],
    )
    errors = validate_spec(spec)
    assert any("src_handle 'true'" in e and "has_value" in e for e in errors)


def test_validate_ifelse_edge_correct_src_handle_ok():
    """src_handle matching case_id or 'false' is valid."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "ifelse", "type": "if-else", "title": "B",
             "cases": [{"case_id": "has_value", "logical_operator": "and",
                        "conditions": [{"variable_selector": ["start", "q"], "comparison_operator": "contains", "value": "x"}]}]},
            {"id": "end", "type": "end", "title": "E", "outputs": []},
        ],
        [
            {"source": "ifelse", "target": "end", "src_handle": "has_value"},  # OK
        ],
    )
    assert validate_spec(spec) == []


def test_validate_missing_edge_between_siblings():
    """Node references another node's output but no edge connects them."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "code1", "type": "code", "title": "C1",
             "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
             "outputs": {"r": {"type": "string"}}},
            {"id": "code2", "type": "code", "title": "C2",
             "variables": [{"variable": "r", "value_selector": ["code1", "r"]}],  # depends on code1
             "outputs": {"out": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E", "outputs": []},
        ],
        [
            {"source": "start", "target": "code1"},
            # MISSING: {"source": "code1", "target": "code2"}
            {"source": "code2", "target": "end"},
        ],
    )
    errors = validate_spec(spec)
    assert any("no edge connects 'code1'" in e and "'code2'" in e for e in errors)


def test_validate_edge_coverage_ok():
    """All variable references have matching edges (direct or transitive)."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "code1", "type": "code", "title": "C1",
             "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
             "outputs": {"r": {"type": "string"}}},
            {"id": "code2", "type": "code", "title": "C2",
             "variables": [{"variable": "r", "value_selector": ["code1", "r"]}],
             "outputs": {"out": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E",
             "outputs": [{"variable": "result", "value_selector": ["code2", "out"]}]},
        ],
        [
            {"source": "start", "target": "code1"},
            {"source": "code1", "target": "code2"},
            {"source": "code2", "target": "end"},
        ],
    )
    assert validate_spec(spec) == []


def test_validate_edge_coverage_transitive_ok():
    """Transitive path is enough: A->B->C, C references A's output."""
    spec = _spec(
        [
            {"id": "start", "type": "start", "title": "S",
             "variables": [{"variable": "q", "label": "Q", "type": "text-input"}]},
            {"id": "mid", "type": "code", "title": "M",
             "variables": [{"variable": "q", "value_selector": ["start", "q"]}],
             "outputs": {"r": {"type": "string"}}},
            {"id": "end", "type": "end", "title": "E",
             "outputs": [{"variable": "q", "value_selector": ["start", "q"]}]},  # references start
        ],
        [
            {"source": "start", "target": "mid"},
            {"source": "mid", "target": "end"},
            # end references start, path: start -> mid -> end (transitive)
        ],
    )
    assert validate_spec(spec) == []
