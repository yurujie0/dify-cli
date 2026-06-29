from __future__ import annotations

import uuid
from typing import Any

from .errors import GraphValidationError

_START_NODE_TYPES = {"start", "datasource", "trigger-webhook", "trigger-schedule", "trigger-plugin"}


def new_node_id(node_type: str) -> str:
    return f"{node_type}-{uuid.uuid4().hex[:8]}"


def new_edge_id() -> str:
    return f"edge-{uuid.uuid4().hex[:8]}"


def find_node(nodes: list[dict[str, Any]], node_id: str) -> dict[str, Any] | None:
    for n in nodes:
        if n.get("id") == node_id:
            return n
    return None


def add_node(doc, node: dict[str, Any]) -> None:
    if find_node(doc.nodes, node["id"]) is not None:
        raise GraphValidationError(f"Node id {node['id']!r} already exists")
    doc.nodes.append(node)


def remove_node(doc, node_id: str) -> bool:
    node = find_node(doc.nodes, node_id)
    if node is None:
        return False
    doc.nodes = [n for n in doc.nodes if n.get("id") != node_id]
    doc.edges = [
        e
        for e in doc.edges
        if e.get("source") != node_id and e.get("target") != node_id
    ]
    return True


def add_edge(doc, edge: dict[str, Any]) -> None:
    doc.edges.append(edge)


def remove_edge(doc, edge_id: str) -> bool:
    before = len(doc.edges)
    doc.edges = [e for e in doc.edges if e.get("id") != edge_id]
    return len(doc.edges) < before


def validate_graph(doc) -> list[str]:
    errors: list[str] = []
    node_ids: set[str] = set()
    start_count = 0
    for n in doc.nodes:
        nid = n.get("id")
        if not nid:
            errors.append("Node missing 'id'")
            continue
        if nid in node_ids:
            errors.append(f"Duplicate node id: {nid}")
        node_ids.add(nid)
        data = n.get("data") or {}
        ntype = data.get("type")
        if not ntype:
            errors.append(f"Node {nid!r} missing data.type")
        if ntype in _START_NODE_TYPES:
            start_count += 1
    if doc.nodes and start_count == 0:
        errors.append("Graph has no start node (expected one of: " + ", ".join(sorted(_START_NODE_TYPES)) + ")")
    if start_count > 1:
        errors.append(f"Graph has {start_count} start nodes; expected exactly 1")

    for e in doc.edges:
        eid = e.get("id")
        src = e.get("source")
        dst = e.get("target")
        if not eid:
            errors.append("Edge missing 'id'")
        if src and src not in node_ids:
            errors.append(f"Edge {eid!r} source {src!r} does not match any node")
        if dst and dst not in node_ids:
            errors.append(f"Edge {eid!r} target {dst!r} does not match any node")
    return errors
