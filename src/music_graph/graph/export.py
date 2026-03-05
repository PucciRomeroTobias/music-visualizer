"""Graph export to multiple formats."""

import json
from pathlib import Path

import networkx as nx
from loguru import logger


def export_gexf(graph: nx.Graph, path: Path) -> None:
    """Export graph to GEXF format (for Gephi)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_gexf(graph, str(path))
    logger.info("Exported GEXF to {}", path)


def export_graphml(graph: nx.Graph, path: Path) -> None:
    """Export graph to GraphML format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(graph, str(path))
    logger.info("Exported GraphML to {}", path)


def export_json(graph: nx.Graph, path: Path) -> None:
    """Export graph to node-link JSON format (for web visualization)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = nx.node_link_data(graph)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    logger.info("Exported JSON to {}", path)


EXPORTERS = {
    "gexf": export_gexf,
    "graphml": export_graphml,
    "json": export_json,
}
