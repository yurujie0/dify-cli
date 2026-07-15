from __future__ import annotations

import time
import uuid
from typing import Any

from .errors import GraphValidationError

_START_NODE_TYPES = {"start", "datasource", "trigger-webhook", "trigger-schedule", "trigger-plugin"}


def new_node_id(node_type: str) -> str:
    """Generate a node id matching the Dify frontend algorithm.

    The frontend (web/app/components/workflow/utils/node.ts:generateNewNode)
    uses `String(Date.now())` — a millisecond timestamp as a string. We mirror
    that so CLI-generated ids look identical to UI-generated ones.
    """
    return str(int(time.time() * 1000))


def new_iteration_start_id(iteration_node_id: str) -> str:
    """Iteration-start child node id: parent_id + 'start' (frontend convention)."""
    return f"{iteration_node_id}start"


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
    nodes = doc.nodes
    node = find_node(nodes, node_id)
    if node is None:
        return False
    # Mutate in place — doc.nodes is a read-only property.
    nodes[:] = [n for n in nodes if n.get("id") != node_id]
    edges = doc.edges
    edges[:] = [
        e
        for e in edges
        if e.get("source") != node_id and e.get("target") != node_id
    ]
    return True


def add_edge(doc, edge: dict[str, Any]) -> None:
    doc.edges.append(edge)


def build_edge(
    doc,
    source: str,
    target: str,
    source_handle: str | None = None,
    target_handle: str | None = None,
    edge_id: str | None = None,
) -> dict[str, Any]:
    """Construct an edge dict matching the frontend's expected shape.

    An edge is "in iteration/loop" if both endpoints share the same parentId
    (i.e. both live inside the same container). The frontend uses this to
    render the edge clipped to the container.
    """
    src_node = find_node(doc.nodes, source)
    dst_node = find_node(doc.nodes, target)
    src_type = (src_node.get("data") or {}).get("type", "") if src_node else ""
    dst_type = (dst_node.get("data") or {}).get("type", "") if dst_node else ""
    src_parent = src_node.get("parentId") if src_node else None
    dst_parent = dst_node.get("parentId") if dst_node else None
    shared_parent = bool(src_parent) and src_parent == dst_parent
    parent_data = {}
    if shared_parent:
        parent = find_node(doc.nodes, src_parent)
        parent_data = (parent.get("data") or {}) if parent else {}
    in_iteration = shared_parent and parent_data.get("type") == "iteration"
    in_loop = shared_parent and parent_data.get("type") == "loop"
    return {
        "id": edge_id or new_edge_id(),
        "source": source,
        "target": target,
        "sourceHandle": source_handle or "source",
        "targetHandle": target_handle or "target",
        "type": "custom",
        "zIndex": 1002 if (in_iteration or in_loop) else 0,
        "data": {
            "sourceType": src_type,
            "targetType": dst_type,
            "isInIteration": in_iteration,
            "isInLoop": in_loop,
        },
    }


def remove_edge(doc, edge_id: str) -> bool:
    edges = doc.edges
    before = len(edges)
    edges[:] = [e for e in edges if e.get("id") != edge_id]
    return len(edges) < before


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
