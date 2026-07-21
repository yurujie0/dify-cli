"""Spec format constants: which node fields are hoisted to the spec layer
(vs. internal config in impl files).

Hoisted fields contain variable selectors (dependencies) or IO declarations,
so they must be visible to `spec validate` at design stage (when impl files
don't exist yet). Internal config (code, prompt_template, model params, etc.)
lives in impl files, one per node, at a convention-based path.
"""
from __future__ import annotations

import re
from pathlib import Path

# Per node type, the fields that live at the spec node top-level (not in
# impl files). apply merges these with the impl file content to form the
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
    "document-extractor": ["variable_selector"],
}

# Spec-layer metadata fields that apply/spec_validator ignore. They carry
# design-stage info (IO contract schema, implementation hints for sub-agents).
IGNORED_SPEC_FIELDS = {"_output_schema", "implementation_hint"}

# Node types whose required fields are ALL hoisted (or have frontend defaults).
# These don't need an impl file - the spec layer is complete at design stage.
# All other node types need an impl file (code, model, prompt_template, etc.).
NODES_WITHOUT_INTERNAL_CONFIG = {"start", "end", "iteration", "loop", "document-extractor", "if-else"}

# Node ids must be path-safe: lowercase alphanumerics, underscore, hyphen.
# Used directly as impl filename (<id>.json), so this avoids path traversal
# and weird characters.
NODE_ID_PATTERN = re.compile(r"^[a-z0-9_-]+$")


def hoisted_fields_for(node_type: str) -> list[str]:
    return HOISTED_FIELDS.get(node_type, [])


def needs_implementation(node_type: str) -> bool:
    """Whether a node type needs an impl file (internal config filled at
    implementation stage)."""
    return node_type not in NODES_WITHOUT_INTERNAL_CONFIG


def impl_dir_for(spec_path: Path) -> Path:
    """Derive the impl directory from the spec file path.
    e.g. /work/mitr_spec.json -> /work/mitr_impl/
         /work/spec.json      -> /work/impl/
    """
    spec_path = Path(spec_path)
    stem = spec_path.stem
    if stem.endswith("_spec"):
        stem = stem[:-5]
    elif stem == "spec":
        stem = ""
    return spec_path.parent / (f"{stem}_impl" if stem else "impl")


def impl_file_for(spec_path: Path, node_id: str) -> Path:
    """Derive the impl file path for a node."""
    return impl_dir_for(spec_path) / f"{node_id}.json"


def is_valid_node_id(node_id: str) -> bool:
    return bool(NODE_ID_PATTERN.match(node_id or ""))
