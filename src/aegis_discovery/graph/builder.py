"""Build a small graph view of an agent.

Layout (per assignment bonus):
    Agent -> Identity -> Tools -> Data Classes -> Policy

We emit it as a flat {nodes, edges} JSON so the HTML UI can render it with a
tiny SVG layout. Node `type` lets the UI color them by category.
"""

from __future__ import annotations

from aegis_discovery.schemas import Agent, AgentGraph, GraphEdge, GraphNode


def build_graph(agent: Agent) -> AgentGraph:
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    agent_node_id = f"agent:{agent.agent_id}"
    nodes.append(GraphNode(id=agent_node_id, type="agent", label=agent.agent_id))

    # Identity nodes (whichever we have).
    identity_targets: list[str] = []
    if agent.nhi_id:
        nid = f"nhi:{agent.nhi_id}"
        nodes.append(GraphNode(id=nid, type="identity", label=f"NHI {agent.nhi_id}"))
        identity_targets.append(nid)
    if agent.workload_id:
        wid = f"workload:{agent.workload_id}"
        nodes.append(GraphNode(id=wid, type="identity", label=f"workload {agent.workload_id}"))
        identity_targets.append(wid)
    if agent.host_id:
        hid = f"host:{agent.host_id}"
        label = f"host {agent.host_id}" + (f" pid {agent.pid}" if agent.pid else "")
        nodes.append(GraphNode(id=hid, type="identity", label=label))
        identity_targets.append(hid)
    for target in identity_targets:
        edges.append(GraphEdge(source=agent_node_id, target=target, label="identity"))

    # Tool nodes.
    for tool in agent.tools:
        tid = f"tool:{tool}"
        nodes.append(GraphNode(id=tid, type="tool", label=tool))
        edges.append(GraphEdge(source=agent_node_id, target=tid, label="uses"))

    # Data class nodes.
    for dc in agent.data_classes:
        did = f"data:{dc}"
        nodes.append(GraphNode(id=did, type="data", label=dc))
        edges.append(GraphEdge(source=agent_node_id, target=did, label="touches"))

    # Destination nodes (external egress).
    for dest in agent.destinations:
        did = f"dest:{dest}"
        nodes.append(GraphNode(id=did, type="destination", label=dest))
        edges.append(GraphEdge(source=agent_node_id, target=did, label="egress"))

    # Policy.
    if agent.recommended_policy:
        pid = f"policy:{agent.recommended_policy}"
        nodes.append(GraphNode(id=pid, type="policy", label=agent.recommended_policy))
        edges.append(GraphEdge(source=agent_node_id, target=pid, label="recommends"))

    return AgentGraph(agent_id=agent.agent_id, nodes=nodes, edges=edges)
