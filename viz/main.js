import ForceGraph3D from "3d-force-graph";
import SpriteText from "three-spritetext";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import * as THREE from "three";

// === Color palette ===
const COMMUNITY_COLORS = [
  "#aa23b1", // rosa-neon (primary)
  "#06b6d4", // cyan
  "#f97316", // orange neon
  "#22d3ee", // electric blue
  "#a855f7", // purple
  "#14b8a6", // teal
  "#f43f5e", // rose
  "#eab308", // yellow
  "#6366f1", // indigo
  "#84cc16", // lime
  "#ec4899", // pink
  "#0ea5e9", // sky
];

const BG_COLOR = "#06030b";

// === State ===
let graphData = null;
let graph = null;
let selectedNode = null;
let selectedNeighborIds = new Set();
const isMobile = "ontouchstart" in window || navigator.maxTouchPoints > 0;

// === Performance profile ===
const PERF = {
  bloom: !isMobile,
  bloomStrength: isMobile ? 0 : 1.2,
  nodeResolution: isMobile ? 3 : 6,
  labelTopN: isMobile ? 15 : 60,
  linkDefaultVisible: !isMobile,
};

// === Node indexes ===
const nodeById = new Map();
const neighborMap = new Map(); // nodeId -> [{node, weight}]
let labelledNodeIds = new Set(); // top N nodes that get permanent labels

// === Sprite cache (Step 2) ===
const spriteCache = new Map(); // nodeId -> SpriteText

// === Tracks lazy cache (Step 5) ===
let tracksData = null; // loaded on first click

// === Load data ===
async function init() {
  const res = await fetch("./data/graph.json");
  graphData = await res.json();

  // Build indexes — store copies since 3d-force-graph mutates node objects
  for (const node of graphData.nodes) {
    const copy = { ...node };
    nodeById.set(node.id, copy);
    neighborMap.set(node.id, []);
  }
  for (const link of graphData.links) {
    const src = typeof link.source === "object" ? link.source.id : link.source;
    const tgt = typeof link.target === "object" ? link.target.id : link.target;
    neighborMap.get(src)?.push({ node: nodeById.get(tgt), weight: link.weight });
    neighborMap.get(tgt)?.push({ node: nodeById.get(src), weight: link.weight });
  }

  // Determine top N nodes by playlist count for permanent labels
  const sorted = [...graphData.nodes].sort((a, b) => b.playlists - a.playlists);
  labelledNodeIds = new Set(sorted.slice(0, PERF.labelTopN).map((n) => n.id));

  // Step 1: Pre-compute fixed positions from exported layout
  const SPREAD = 2.0;
  for (const node of graphData.nodes) {
    node.fx = (node.x - 500) * SPREAD;
    node.fy = (node.y - 500) * SPREAD;
    node.fz =
      ((node.community * 73) % 11 - 5) * 40 +
      (hashCode(node.name) % 100 - 50) * 0.5;
  }

  createGraph();
  buildLegend();
  setupSearch();
  setupDetailPanel();
  hideLoading();
}

// === Simple string hash for z-spread ===
function hashCode(str) {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = (hash * 31 + str.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

// === Create 3D graph ===
function createGraph() {
  const container = document.getElementById("graph-container");

  // Compute node size range for visual mapping
  const playlistCounts = graphData.nodes.map((n) => n.playlists || 1);
  const maxPlaylists = Math.max(...playlistCounts);
  const minPlaylists = Math.min(...playlistCounts);
  const playlistRange = maxPlaylists - minPlaylists || 1;

  // Store for sprite positioning
  createGraph._minPlaylists = minPlaylists;
  createGraph._playlistRange = playlistRange;

  graph = ForceGraph3D()(container)
    .graphData(graphData)
    .backgroundColor(BG_COLOR)
    // Node sizing: map playlist count to volume (1-8 range)
    .nodeVal((n) => {
      const normalized = ((n.playlists || 1) - minPlaylists) / playlistRange;
      return 1 + normalized * 7;
    })
    .nodeColor((n) => {
      if (!selectedNode) {
        return COMMUNITY_COLORS[n.community % COMMUNITY_COLORS.length];
      }
      if (n.id === selectedNode.id) {
        return "#ffffff"; // selected node: white
      }
      if (selectedNeighborIds.has(n.id)) {
        return COMMUNITY_COLORS[n.community % COMMUNITY_COLORS.length];
      }
      return "#1a1020"; // dimmed
    })
    .nodeOpacity(0.85)
    .nodeResolution(PERF.nodeResolution)
    .nodeLabel("")
    // Extend default sphere with text label for top nodes
    .nodeThreeObjectExtend(true)
    .nodeThreeObject((node) => {
      return getOrCreateSprite(node);
    })
    // Step 3a: Link visibility — hide unrelated links
    .linkVisibility((link) => {
      if (!selectedNode) return PERF.linkDefaultVisible;
      const src = typeof link.source === "object" ? link.source.id : link.source;
      const tgt = typeof link.target === "object" ? link.target.id : link.target;
      return src === selectedNode.id || tgt === selectedNode.id;
    })
    .linkColor((link) => {
      if (!selectedNode) return "rgba(170, 35, 177, 0.07)";
      const color =
        COMMUNITY_COLORS[selectedNode.community % COMMUNITY_COLORS.length];
      return color + "80"; // 50% opacity hex
    })
    .linkWidth((link) => {
      if (!selectedNode) return 0;
      return Math.sqrt(link.weight) * 2;
    })
    .linkOpacity(0.3)
    // No particles by default (huge perf win)
    .linkDirectionalParticles(0)
    .onNodeClick(handleNodeClick)
    .onBackgroundClick(handleBackgroundClick)
    // Step 1: No force simulation — positions are pre-computed
    .warmupTicks(0)
    .cooldownTicks(0);

  // Step 4: Bloom only on desktop
  if (PERF.bloom) {
    const bloomPass = new UnrealBloomPass(
      new THREE.Vector2(window.innerWidth, window.innerHeight),
      PERF.bloomStrength, // strength
      0.4, // radius
      0.85 // threshold
    );
    graph.postProcessingComposer().addPass(bloomPass);
  }

  // Responsive resize
  window.addEventListener("resize", () => {
    graph.width(window.innerWidth).height(window.innerHeight);
  });
}

// === Step 2: Sprite cache ===
function getOrCreateSprite(node) {
  const isSelected = selectedNode && node.id === selectedNode.id;
  const isNeighbor = selectedNode && selectedNeighborIds.has(node.id);
  const hasLabel = labelledNodeIds.has(node.id);

  // No label needed — remove from cache if it was a temporary neighbor label
  if (!hasLabel && !isSelected && !isNeighbor) {
    spriteCache.delete(node.id);
    return false;
  }

  let sprite = spriteCache.get(node.id);
  if (!sprite) {
    sprite = new SpriteText(node.name.toUpperCase());
    sprite.fontFace = "Inter, system-ui, sans-serif";
    sprite.fontSize = 90;
    sprite.fontWeight = "bold";
    sprite.borderRadius = 2;
    sprite.padding = 1;
    spriteCache.set(node.id, sprite);
  }

  // Update visual properties (cheap — no canvas recreation if text unchanged)
  if (isSelected) {
    sprite.color = "#ffffff";
    sprite.backgroundColor = "rgba(170, 35, 177, 0.7)";
    sprite.textHeight = 5;
  } else if (isNeighbor) {
    sprite.color = "rgba(255, 255, 255, 0.85)";
    sprite.backgroundColor = "rgba(6, 3, 11, 0.7)";
    sprite.textHeight = 3.5;
  } else if (selectedNode) {
    // Permanent label but not related — dim it
    sprite.color = "rgba(255, 255, 255, 0.15)";
    sprite.backgroundColor = "rgba(6, 3, 11, 0.3)";
    sprite.textHeight = 4;
  } else {
    sprite.color = "#ffffff";
    sprite.backgroundColor = "rgba(6, 3, 11, 0.6)";
    sprite.textHeight = 4;
  }

  const minPlaylists = createGraph._minPlaylists;
  const playlistRange = createGraph._playlistRange;
  const nodeSize =
    1 + (((node.playlists || 1) - minPlaylists) / playlistRange) * 7;
  sprite.position.set(0, Math.cbrt(nodeSize) * 3 + 3, 0);
  return sprite;
}

// === Interactions ===
function handleNodeClick(node) {
  if (!node) return;
  selectedNode = node;

  // Build neighbor set for highlighting
  const neighbors = neighborMap.get(node.id) || [];
  selectedNeighborIds = new Set(neighbors.map((n) => n.node?.id).filter(Boolean));

  // Refresh visual state
  graph.nodeColor(graph.nodeColor());
  graph.linkVisibility(graph.linkVisibility());
  graph.linkColor(graph.linkColor());
  graph.linkWidth(graph.linkWidth());
  graph.nodeThreeObject(graph.nodeThreeObject());

  showDetail(node);

  // Focus camera on node
  const distance = 150;
  const distRatio =
    1 + distance / Math.hypot(node.x || 0, node.y || 0, node.z || 0);
  graph.cameraPosition(
    {
      x: (node.x || 0) * distRatio,
      y: (node.y || 0) * distRatio,
      z: (node.z || 0) * distRatio,
    },
    node,
    1200
  );
}

function handleBackgroundClick() {
  selectedNode = null;
  selectedNeighborIds = new Set();

  // Restore visual state
  graph.nodeColor(graph.nodeColor());
  graph.linkVisibility(graph.linkVisibility());
  graph.linkColor(graph.linkColor());
  graph.linkWidth(graph.linkWidth());
  graph.nodeThreeObject(graph.nodeThreeObject());

  hideDetail();
}

// === Detail panel ===
function setupDetailPanel() {
  document.getElementById("detail-close").addEventListener("click", () => {
    handleBackgroundClick();
  });
}

// Step 5: Lazy-load tracks
async function loadTracks() {
  if (tracksData) return tracksData;
  try {
    const res = await fetch("./data/graph_tracks.json");
    tracksData = await res.json();
  } catch {
    tracksData = {};
  }
  return tracksData;
}

async function showDetail(node) {
  // Use stored copy since 3d-force-graph strips custom fields from node objects
  const data = nodeById.get(node.id) || node;

  const panel = document.getElementById("detail-panel");
  document.getElementById("detail-name").textContent = data.name;

  // Platforms
  const platformsEl = document.getElementById("detail-platforms");
  platformsEl.innerHTML = "";
  for (const p of data.platforms || []) {
    const badge = document.createElement("span");
    badge.className = `platform-badge ${p}`;
    badge.textContent =
      p === "deezer" ? "DZ" : p === "soundcloud" ? "SC" : p.toUpperCase();
    platformsEl.appendChild(badge);
  }

  // Community
  const communityIdx = data.community;
  const communityInfo = graphData.communities[communityIdx];
  const topArtists = communityInfo
    ? communityInfo.top_artists.slice(0, 3).join(", ")
    : "";
  document.getElementById("detail-community").textContent =
    `#${communityIdx}` + (topArtists ? ` (${topArtists})` : "");

  // Stats
  document.getElementById("detail-connections").textContent = data.connections ?? 0;
  document.getElementById("detail-playlists").textContent = data.playlists ?? 0;
  document.getElementById("detail-track-count").textContent = data.trackCount ?? 0;

  // Tracks — lazy load from sidecar
  const tracksList = document.getElementById("detail-tracks");
  tracksList.innerHTML = "<li>Loading...</li>";
  const tracks = await loadTracks();
  const nodeTracks = (tracks[data.id] || []).slice(0, 10);
  tracksList.innerHTML = "";
  for (const t of nodeTracks) {
    const li = document.createElement("li");
    li.innerHTML = `${escapeHtml(t.title)}<span class="track-platform">${t.platform}</span>`;
    tracksList.appendChild(li);
  }

  // Connected artists (top 10 by weight)
  const neighbors = (neighborMap.get(data.id) || [])
    .filter((n) => n.node)
    .sort((a, b) => b.weight - a.weight)
    .slice(0, 10);
  const neighborsList = document.getElementById("detail-neighbors");
  neighborsList.innerHTML = "";
  for (const { node: n, weight } of neighbors) {
    const li = document.createElement("li");
    li.innerHTML = `${escapeHtml(n.name)}<span class="neighbor-weight">${weight.toFixed(3)}</span>`;
    li.addEventListener("click", () => handleNodeClick(n));
    neighborsList.appendChild(li);
  }

  panel.classList.remove("hidden");
}

function hideDetail() {
  document.getElementById("detail-panel").classList.add("hidden");
}

// === Search ===
function setupSearch() {
  const input = document.getElementById("search-input");
  const results = document.getElementById("search-results");

  input.addEventListener("input", () => {
    const query = input.value.trim().toLowerCase();
    results.innerHTML = "";

    if (query.length < 2) {
      results.classList.remove("visible");
      return;
    }

    const matches = graphData.nodes
      .filter((n) => n.name.toLowerCase().includes(query))
      .sort((a, b) => b.playlists - a.playlists) // best matches first
      .slice(0, 15);

    if (matches.length === 0) {
      results.classList.remove("visible");
      return;
    }

    for (const node of matches) {
      const div = document.createElement("div");
      div.className = "search-result-item";
      div.textContent = node.name;
      div.addEventListener("click", () => {
        handleNodeClick(node);
        input.value = node.name;
        results.classList.remove("visible");
      });
      results.appendChild(div);
    }
    results.classList.add("visible");
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#search-bar")) {
      results.classList.remove("visible");
    }
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const first = results.querySelector(".search-result-item");
      if (first) first.click();
    }
  });
}

// === Legend ===
function buildLegend() {
  const container = document.getElementById("legend-items");
  const communities = graphData.communities || [];

  const sorted = [...communities].sort((a, b) => b.size - a.size).slice(0, 10);

  for (const c of sorted) {
    const color = COMMUNITY_COLORS[c.id % COMMUNITY_COLORS.length];
    const label = c.top_artists.slice(0, 2).join(", ");

    const item = document.createElement("div");
    item.className = "legend-item";
    item.innerHTML = `<span class="legend-color" style="background:${color}"></span><span>${escapeHtml(label)} (${c.size})</span>`;
    item.addEventListener("click", () => {
      const communityNode = graphData.nodes.find((n) => n.community === c.id);
      if (communityNode) handleNodeClick(communityNode);
    });
    container.appendChild(item);
  }
}

// === Loading ===
function hideLoading() {
  const loading = document.getElementById("loading");
  loading.classList.add("fade-out");
  setTimeout(() => loading.remove(), 600);
}

// === Utils ===
function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// === Start ===
init();
