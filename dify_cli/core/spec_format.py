"""Spec format constants: which node fields are hoisted to the spec layer
(vs. internal config in @file).

Hoisted fields contain variable selectors (dependencies) or IO declarations,
so they must be visible to `spec validate` at design stage (when @file
doesn't exist yet). `fields` (@file) holds only internal node config
(code, prompt_template, model params, etc.) with no cross-node selectors.
"""
from __future__ import annotations

# Per node type, the fields that live at the spec node top-level (not in
# `fields`/@file). apply merges these with the @file content to form the
# final node data.
HOISTED_FIELDS: dict[str, list[str]] = {
    "start": ["variables"],
    "code": ["variables", "outputs"],
    "end": ["outputs"],
    "llm": ["context"],
    "if-else": ["cases"],
    "iteration": ["iterator_selector", "output_selector"],
    "loop": ["loop_variables", "break_conditions"],
    "template-transform": ["variables"],
    "variable-aggregator": ["variables"],
    "knowledge-retrieval": ["query_variable_selector"],
    "question-classifier": ["query_variable_selector"],
    "parameter-extractor": ["parameters", "query"],
}

# Spec-layer metadata fields that apply/spec_validator ignore. They carry
# design-stage info (IO contract schema, implementation hints for sub-agents).
IGNORED_SPEC_FIELDS = {"_output_schema", "implementation_hint"}


def hoisted_fields_for(node_type: str) -> list[str]:
    return HOISTED_FIELDS.get(node_type, [])
