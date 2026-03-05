"""Pluggable edge weight algorithms for graph construction."""

import math
from abc import ABC, abstractmethod
from collections import defaultdict


class EdgeWeightAlgorithm(ABC):
    """Abstract base for edge weight computation."""

    @abstractmethod
    def compute(
        self,
        cooccurrence: dict[tuple, int],
        node_counts: dict | None = None,
        total_contexts: int = 0,
    ) -> dict[tuple, float]:
        """Compute edge weights from co-occurrence data.

        Args:
            cooccurrence: {(node_a, node_b): count} pairs.
            node_counts: {node_id: number_of_contexts} for each node.
            total_contexts: Total number of contexts (playlists/artists).

        Returns:
            {(node_a, node_b): weight} dict.
        """
        ...


class WeightedCooccurrence(EdgeWeightAlgorithm):
    """Raw co-occurrence count as weight."""

    def compute(
        self,
        cooccurrence: dict[tuple, int],
        node_counts: dict | None = None,
        total_contexts: int = 0,
    ) -> dict[tuple, float]:
        return {pair: float(count) for pair, count in cooccurrence.items()}


class JaccardWeight(EdgeWeightAlgorithm):
    """Jaccard similarity: |A ∩ B| / |A ∪ B|."""

    def compute(
        self,
        cooccurrence: dict[tuple, int],
        node_counts: dict | None = None,
        total_contexts: int = 0,
    ) -> dict[tuple, float]:
        if node_counts is None:
            raise ValueError("JaccardWeight requires node_counts")

        weights = {}
        for (a, b), intersection in cooccurrence.items():
            union = node_counts.get(a, 0) + node_counts.get(b, 0) - intersection
            if union > 0:
                weights[(a, b)] = intersection / union
        return weights


class PMIWeight(EdgeWeightAlgorithm):
    """Pointwise Mutual Information — good for discovering niche associations."""

    def compute(
        self,
        cooccurrence: dict[tuple, int],
        node_counts: dict | None = None,
        total_contexts: int = 0,
    ) -> dict[tuple, float]:
        if node_counts is None or total_contexts == 0:
            raise ValueError("PMIWeight requires node_counts and total_contexts")

        weights = {}
        for (a, b), count in cooccurrence.items():
            p_ab = count / total_contexts
            p_a = node_counts.get(a, 1) / total_contexts
            p_b = node_counts.get(b, 1) / total_contexts
            denom = p_a * p_b
            if denom > 0 and p_ab > 0:
                weights[(a, b)] = math.log2(p_ab / denom)
        return weights


class CosineWeight(EdgeWeightAlgorithm):
    """Cosine similarity on co-occurrence vectors."""

    def compute(
        self,
        cooccurrence: dict[tuple, int],
        node_counts: dict | None = None,
        total_contexts: int = 0,
    ) -> dict[tuple, float]:
        # Build adjacency vectors per node
        vectors: dict = defaultdict(lambda: defaultdict(int))
        for (a, b), count in cooccurrence.items():
            vectors[a][b] = count
            vectors[b][a] = count

        # Compute norms
        norms: dict = {}
        for node, vec in vectors.items():
            norms[node] = math.sqrt(sum(v * v for v in vec.values()))

        weights = {}
        for (a, b), count in cooccurrence.items():
            norm_a = norms.get(a, 1.0)
            norm_b = norms.get(b, 1.0)
            if norm_a > 0 and norm_b > 0:
                weights[(a, b)] = count / (norm_a * norm_b)
        return weights


ALGORITHMS: dict[str, type[EdgeWeightAlgorithm]] = {
    "raw": WeightedCooccurrence,
    "jaccard": JaccardWeight,
    "pmi": PMIWeight,
    "cosine": CosineWeight,
}
