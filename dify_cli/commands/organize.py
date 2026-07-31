"""Organize node positions in a DSL file based on graph topology.

Topological layering: each node's column = max(column of predecessors) + 1.
Containers (iteration/loop) position their children inside.
"""
from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Any

import typer

from ..core import dsl as dsl_mod
from ..core.errors import DifyCliError

# Layout constants (match frontend node sizes).
_COL_WIDTH = 320
_ROW_HEIGHT = 130
_NODE_MARGIN_X = 76
_NODE_MARGIN_Y = 40
_CONTAINER_PADDING = 24


def organize(
    file: Path = typer.Argument(Path("dsl.yaml"), help="DSL YAML file (modified in place)"),
) -> None:
    """Organize node positions in a DSL file based on graph topology.

    Re-arranges node position/positionAbsolute so the workflow reads
    left-to-right following data flow. Does NOT change node data, edges,
    or topology. Modifies the file in place.
    """
    doc = dsl_mod.load(file)
    if "workflow" not in doc.data:
        raise DifyCliError(f"{file} has no 'workflow' section")
    graph = doc.graph
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    if not nodes:
        raise DifyCliError("No nodes to organize")

    # Build adjacency and in-degree.
    node_ids = [n.get("id") for n in nodes if n.get("id")]
    node_by_id = {n["id"]: n for n in nodes if n.get("id")}
    adjacency: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {nid: 0 for nid in node_ids}
    for e in edges:
        src = e.get("source", "")
        dst = e.get("target", "")
        if src in node_by_id and dst in node_by_id:
            adjacency[src].append(dst)
            in_degree[dst] = in_degree.get(dst, 0) + 1

    # Topological sort (Kahn's algorithm) to assign layers.
    # layer[node] = max(layer[predecessors]) + 1, start nodes at layer 0.
    layers: dict[str, int] = {}
    queue: deque[str] = deque()
    remaining_in_degree = dict(in_degree)
    for nid in node_ids:
        if remaining_in_degree.get(nid, 0) == 0:
            queue.append(nid)
            layers[nid] = 0
    while queue:
        nid = queue.popleft()
        for child in adjacency.get(nid, []):
            remaining_in_degree[child] -= 1
            layers[child] = max(layers.get(child, 0), layers.get(nid, 0) + 1)
            if remaining_in_degree[child] == 0:
                queue.append(child)

    # Handle cycles: any node not assigned a layer gets layer 0.
    for nid in node_ids:
        if nid not in layers:
            layers[nid] = 0

    # Group nodes by layer, preserving original order within each layer.
    layer_nodes: dict[int, list[str]] = defaultdict(list)
    for nid in node_ids:
        layer_nodes[layers[nid]].append(nid)

    # Separate container nodes from regular nodes for positioning.
    container_ids = {
        n["id"] for n in nodes
        if (n.get("data") or {}).get("type") in ("iteration", "loop")
    }
    # Child -> parent mapping.
    child_to_parent = {}
    for n in nodes:
        pid = n.get("parentId")
        if pid:
            child_to_parent[n.get("id", "")] = pid

    # Assign positions: top-level nodes get absolute coords, children
    # get coords relative to their container's interior.
    max_layer = max(layers.values()) if layers else 0
    # Track y offset per layer.
    layer_y: dict[int, float] = {i: 0.0 for i in range(max_layer + 1)}

    for layer in range(max_layer + 1):
        for nid in layer_nodes.get(layer, []):
            node = node_by_id.get(nid)
            if node is None:
                continue
            ntype = (node.get("data") or {}).get("type", "")
            # Skip children - they're positioned relative to their container.
            if nid in child_to_parent:
                continue
            # Determine node dimensions.
            if ntype in ("iteration", "loop"):
                width, height = 388, 178
            elif ntype in ("iteration-start", "loop-start"):
                width, height = 44, 48
            else:
                width, height = 244, 90

            x = layer * _COL_WIDTH
            y = layer_y[layer]
            node["position"] = {"x": x, "y": y}
            node["positionAbsolute"] = {"x": x, "y": y}
            # Also sync width/height if missing.
            node.setdefault("width", width)
            node.setdefault("height", height)
            layer_y[layer] = y + height + _NODE_MARGIN_Y

    # Position container children relative to their parent.
    for n in nodes:
        nid = n.get("id", "")
        ntype = (n.get("data") or {}).get("type", "")
        parent_id = n.get("parentId")
        if not parent_id:
            continue
        parent = node_by_id.get(parent_id, {})
        parent_pos = parent.get("position", {"x": 0, "y": 0})
        px, py = parent_pos.get("x", 0), parent_pos.get("y", 0)

        if ntype in ("iteration-start", "loop-start"):
            # Start node: fixed position inside container.
            cx = px + _CONTAINER_PADDING
            cy = py + _CONTAINER_PADDING + 20  # below the title bar
        else:
            # Regular child: offset from start node.
            # Find sibling index for vertical stacking.
            siblings = [
                s for s in nodes
                if s.get("parentId") == parent_id
                and (s.get("data") or {}).get("type") not in ("iteration-start", "loop-start")
            ]
            idx = next((i for i, s in enumerate(siblings) if s.get("id") == nid), 0)
            cx = px + _CONTAINER_PADDING + 104  # right of start node
            cy = py + _CONTAINER_PADDING + 20 + idx * _ROW_HEIGHT

        n["position"] = {"x": cx - px, "y": cy - py}
        n["positionAbsolute"] = {"x": cx, "y": cy}

    dsl_mod.save(file, doc)
    typer.secho(f"Organized {len(nodes)} nodes in {file}", fg=typer.colors.GREEN)
