/**
 * NOWARMUP — Artist Graph (Sigma.js + Graphology)
 *
 * 2D WebGL graph visualization with pre-computed community-aware layout,
 * community coloring, search, and detail panel.
 */

import Graph from "graphology";
import Sigma from "sigma";

// ── Community color palette (neon/rave) ──────────────────────────
const COMMUNITY_COLORS = [
  "#aa23b1", // rosa-neon (primary)
  "#06b6d4", // cyan
  "#f97316", // orange neon
  "#22d3ee", // electric blue
  "#a855f7", // purple
  "#14b8a6", // teal
  "#f43f5e", // rose
  "#eab308", // yellow
  "#3b82f6", // blue
  "#10b981", // emerald
  "#ec4899", // pink
  "#8b5cf6", // violet
];

// ── State ────────────────────────────────────────────────────────
let highlightedNode = null;
let highlightedNeighbors = new Set();
let searchQuery = "";

// ── Load data & init ─────────────────────────────────────────────
async function main() {
  const res = await fetch("./data/graph.json");
  const data = await res.json();

  const graph = new Graph();

  // Index for quick lookup
  const nodeById = new Map();

  // Compute max playlists for sizing (log scale for less extreme variation)
  const playlistValues = data.nodes.map((n) => n.playlists || 1);
  const maxLog = Math.log2(Math.max(...playlistValues) + 1);

  // Add nodes — small sizes to avoid overlap
  for (const node of data.nodes) {
    const logVal = Math.log2((node.playlists || 1) + 1);
    const size = 2 + (logVal / maxLog) * 6; // range: 2–8px
    const color =
      COMMUNITY_COLORS[node.community % COMMUNITY_COLORS.length] || "#aa23b1";

    graph.addNode(node.id, {
      x: node.x,
      y: node.y,
      size,
      color,
      label: node.name,
      community: node.community,
    });

    nodeById.set(node.id, node);
  }

  // Add edges — barely visible, only show structure on hover/click
  for (const link of data.links) {
    graph.addEdge(link.source, link.target, {
      weight: link.weight,
      size: 0.15,
      color: "rgba(100, 60, 120, 0.06)",
    });
  }

  // ── Sigma renderer ───────────────────────────────────────────
  const container = document.getElementById("sigma-container");

  const renderer = new Sigma(graph, container, {
    allowInvalidContainer: true,
    defaultEdgeType: "line",
    // Labels: white for readability against dark bg
    labelFont: "Inter, system-ui, sans-serif",
    labelColor: { color: "#e0dce4" },
    labelSize: 13,
    labelWeight: "600",
    // Show more labels — higher density + lower size threshold
    labelDensity: 0.7,
    labelGridCellSize: 200,
    labelRenderedSizeThreshold: 4,
    stagePadding: 60,
    zoomToSizeRatioFunction: (ratio) => ratio,
    nodeReducer(node, attrs) {
      const res = { ...attrs };

      if (highlightedNode) {
        if (
          node !== highlightedNode &&
          !highlightedNeighbors.has(node)
        ) {
          res.color = "#1a1020";
          res.label = "";
          res.zIndex = 0;
        } else {
          res.zIndex = 1;
          res.forceLabel = true;
        }
      }

      // Search dimming
      if (
        searchQuery &&
        !attrs.label?.toLowerCase().includes(searchQuery)
      ) {
        if (!highlightedNode) {
          res.color = "#1a1020";
          res.label = "";
        }
      }

      return res;
    },
    edgeReducer(edge, attrs) {
      const res = { ...attrs };

      if (highlightedNode) {
        const src = graph.source(edge);
        const tgt = graph.target(edge);
        if (src !== highlightedNode && tgt !== highlightedNode) {
          res.hidden = true;
        } else {
          // Make connected edges visible and colored
          const nodeColor =
            graph.getNodeAttribute(highlightedNode, "color") || "#aa23b1";
          res.color = nodeColor + "60";
          res.size = 0.8;
        }
      }

      return res;
    },
  });

  // ── Build community legend ───────────────────────────────────
  const legendItems = document.getElementById("legend-items");
  if (data.communities) {
    const sorted = [...data.communities].sort((a, b) => b.size - a.size);
    for (const comm of sorted) {
      if (comm.size < 3) continue;
      const color =
        COMMUNITY_COLORS[comm.id % COMMUNITY_COLORS.length] || "#aa23b1";
      const label =
        comm.top_artists?.slice(0, 3).join(", ") ||
        `Community ${comm.id}`;

      const item = document.createElement("div");
      item.className = "legend-item";
      item.innerHTML = `
        <span class="legend-color" style="background:${color}"></span>
        <span>${label} (${comm.size})</span>
      `;
      legendItems.appendChild(item);
    }
  }

  // ── Click handler → detail panel ─────────────────────────────
  const detailPanel = document.getElementById("detail-panel");
  const detailName = document.getElementById("detail-name");
  const detailPlatforms = document.getElementById("detail-platforms");
  const detailCommunity = document.getElementById("detail-community");
  const detailConnections = document.getElementById("detail-connections");
  const detailPlaylists = document.getElementById("detail-playlists");
  const detailTrackCount = document.getElementById("detail-track-count");
  const detailTracks = document.getElementById("detail-tracks");
  const detailNeighbors = document.getElementById("detail-neighbors");
  const detailClose = document.getElementById("detail-close");

  function showDetail(nodeId) {
    const nodeData = nodeById.get(Number(nodeId) || nodeId);
    if (!nodeData) return;

    highlightedNode = String(nodeId);
    highlightedNeighbors = new Set(graph.neighbors(String(nodeId)));
    renderer.refresh();

    detailName.textContent = nodeData.name;

    detailPlatforms.innerHTML = "";
    for (const p of nodeData.platforms || []) {
      const badge = document.createElement("span");
      badge.className = `platform-badge ${p.toLowerCase()}`;
      badge.textContent = p.toUpperCase();
      detailPlatforms.appendChild(badge);
    }

    const comm = data.communities?.find((c) => c.id === nodeData.community);
    detailCommunity.textContent = comm
      ? comm.top_artists?.slice(0, 3).join(", ") || `#${nodeData.community}`
      : `#${nodeData.community}`;

    detailConnections.textContent = nodeData.connections || 0;
    detailPlaylists.textContent = nodeData.playlists || 0;
    detailTrackCount.textContent = nodeData.trackCount || 0;

    detailTracks.innerHTML = "";
    for (const t of nodeData.tracks || []) {
      const li = document.createElement("li");
      li.innerHTML = `${t.title} <span class="track-platform">${t.platform}</span>`;
      detailTracks.appendChild(li);
    }

    detailNeighbors.innerHTML = "";
    const neighbors = graph.neighbors(String(nodeId));
    const neighborWeights = neighbors
      .map((nid) => {
        const edgeKey =
          graph.hasEdge(String(nodeId), nid)
            ? graph.getEdgeAttributes(graph.edge(String(nodeId), nid))
            : graph.hasEdge(nid, String(nodeId))
              ? graph.getEdgeAttributes(graph.edge(nid, String(nodeId)))
              : { weight: 0 };
        return {
          id: nid,
          name: graph.getNodeAttribute(nid, "label"),
          weight: edgeKey.weight || 0,
        };
      })
      .sort((a, b) => b.weight - a.weight)
      .slice(0, 15);

    for (const nb of neighborWeights) {
      const li = document.createElement("li");
      li.innerHTML = `${nb.name} <span class="neighbor-weight">${nb.weight.toFixed(3)}</span>`;
      li.addEventListener("click", () => {
        renderer.getCamera().animate(
          { ...renderer.getNodeDisplayData(nb.id), ratio: 0.15 },
          { duration: 600 }
        );
        showDetail(nb.id);
      });
      detailNeighbors.appendChild(li);
    }

    detailPanel.classList.remove("hidden");
  }

  function hideDetail() {
    detailPanel.classList.add("hidden");
    highlightedNode = null;
    highlightedNeighbors = new Set();
    renderer.refresh();
  }

  renderer.on("clickNode", ({ node }) => {
    renderer.getCamera().animate(
      { ...renderer.getNodeDisplayData(node), ratio: 0.15 },
      { duration: 600 }
    );
    showDetail(node);
  });

  renderer.on("clickStage", () => {
    hideDetail();
  });

  detailClose.addEventListener("click", hideDetail);

  // ── Search ───────────────────────────────────────────────────
  const searchInput = document.getElementById("search-input");
  const searchResults = document.getElementById("search-results");

  searchInput.addEventListener("input", (e) => {
    const query = e.target.value.toLowerCase().trim();
    searchQuery = query;
    searchResults.innerHTML = "";

    if (query.length < 2) {
      searchResults.classList.remove("visible");
      renderer.refresh();
      return;
    }

    const matches = [];
    graph.forEachNode((node, attrs) => {
      if (attrs.label?.toLowerCase().includes(query)) {
        matches.push({ id: node, name: attrs.label, size: attrs.size });
      }
    });

    matches.sort((a, b) => b.size - a.size);

    if (matches.length === 0) {
      searchResults.classList.remove("visible");
      renderer.refresh();
      return;
    }

    searchResults.classList.add("visible");
    for (const m of matches.slice(0, 10)) {
      const item = document.createElement("div");
      item.className = "search-result-item";
      item.textContent = m.name;
      item.addEventListener("click", () => {
        searchInput.value = m.name;
        searchResults.classList.remove("visible");
        searchQuery = "";

        renderer.getCamera().animate(
          { ...renderer.getNodeDisplayData(m.id), ratio: 0.1 },
          { duration: 600 }
        );
        showDetail(m.id);
      });
      searchResults.appendChild(item);
    }

    renderer.refresh();
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#search-bar")) {
      searchResults.classList.remove("visible");
    }
  });

  // ── Hide loading ─────────────────────────────────────────────
  const loading = document.getElementById("loading");
  loading.classList.add("fade-out");
  setTimeout(() => loading.remove(), 600);
}

main().catch(console.error);
