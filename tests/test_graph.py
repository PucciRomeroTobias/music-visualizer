import math

import networkx as nx
import pytest

from music_graph.graph.edge_weights import JaccardWeight, PMIWeight
from music_graph.pipeline.viz_filters import VizFilterConfig, filter_graph


def test_jaccard_weight() -> None:
    result = JaccardWeight().compute({("a", "b"): 2}, {"a": 3, "b": 4})

    assert result[("a", "b")] == pytest.approx(0.4)


def test_pmi_weight() -> None:
    result = PMIWeight().compute(
        {("a", "b"): 2}, {"a": 4, "b": 5}, total_contexts=10
    )

    assert result[("a", "b")] == pytest.approx(math.log2(1.0))


def test_filter_graph_prunes_until_degree_is_stable() -> None:
    graph = nx.path_graph(["a", "b", "c", "d"])
    config = VizFilterConfig(min_degree=2, max_nodes=None, max_edges=None)

    result = filter_graph(graph, config)

    assert result.number_of_nodes() == 0


def test_filter_graph_keeps_highest_weight_edges() -> None:
    graph = nx.Graph()
    graph.add_edge("a", "b", weight=0.1)
    graph.add_edge("a", "c", weight=0.9)
    graph.add_edge("b", "c", weight=0.5)
    config = VizFilterConfig(min_degree=0, max_nodes=None, max_edges=2)

    result = filter_graph(graph, config)

    assert {data["weight"] for *_, data in result.edges(data=True)} == {0.9, 0.5}
