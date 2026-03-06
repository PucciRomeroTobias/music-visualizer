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

const ROSA_NEON = "#aa23b1";
const BG_COLOR = "#06030b";

// === State ===
let graphData = null;
let graph = null;
let selectedNode = null;
const isMobile = "ontouchstart" in window || navigator.maxTouchPoints > 0;

// How many top nodes get permanent labels
const LABEL_TOP_N = isMobile ? 30 : 80;

// === Node indexes ===
const nodeById = new Map();
const neighborMap = new Map(); // nodeId -> [{node, weight}]
let labelledNodeIds = new Set(); // top N nodes that get permanent labels

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
  labelledNodeIds = new Set(sorted.slice(0, LABEL_TOP_N).map((n) => n.id));

  createGraph();
  buildLegend();
  setupSearch();
  setupDetailPanel();
  hideLoading();
}

// === Create 3D graph ===
function createGraph() {
  const container = document.getElementById("graph-container");

  // Compute node size range for visual mapping
  const playlistCounts = graphData.nodes.map((n) => n.playlists || 1);
  const maxPlaylists = Math.max(...playlistCounts);
  const minPlaylists = Math.min(...playlistCounts);
  const playlistRange = maxPlaylists - minPlaylists || 1;

  graph = ForceGraph3D()(container)
    .graphData(graphData)
    .backgroundColor(BG_COLOR)
    // Node sizing: map playlist count to volume (1-8 range)
    .nodeVal((n) => {
      const normalized = ((n.playlists || 1) - minPlaylists) / playlistRange;
      return 1 + normalized * 7;
    })
    .nodeColor((n) => COMMUNITY_COLORS[n.community % COMMUNITY_COLORS.length])
    .nodeOpacity(0.85)
    .nodeResolution(isMobile ? 4 : 8)
    .nodeLabel("")
    // Extend default sphere with text label for top nodes
    .nodeThreeObjectExtend(true)
    .nodeThreeObject((node) => {
      if (!labelledNodeIds.has(node.id)) return false;
      const sprite = new SpriteText(node.name.toUpperCase());
      sprite.color = "#ffffff";
      sprite.backgroundColor = "rgba(6, 3, 11, 0.6)";
      sprite.padding = 1;
      sprite.borderRadius = 2;
      sprite.fontFace = "Inter, system-ui, sans-serif";
      sprite.fontSize = 90;
      sprite.textHeight = 4;
      sprite.fontWeight = "bold";
      // Position above the node sphere
      const nodeSize = 1 + (((node.playlists || 1) - minPlaylists) / playlistRange) * 7;
      sprite.position.set(0, Math.cbrt(nodeSize) * 3 + 3, 0);
      return sprite;
    })
    // Links: minimal and fast
    .linkColor(() => "rgba(170, 35, 177, 0.07)")
    .linkWidth(0)
    .linkOpacity(0.3)
    // No particles by default (huge perf win)
    .linkDirectionalParticles(0)
    .onNodeClick(handleNodeClick)
    .onBackgroundClick(handleBackgroundClick)
    // Performance: pre-compute layout, then freeze
    .warmupTicks(200)
    .cooldownTicks(0)
    // Weaker forces for faster convergence
    .d3VelocityDecay(0.3);

  // Tune forces for better cluster separation
  graph.d3Force("charge").strength(-30).distanceMax(300);
  graph.d3Force("link").distance(30).strength(0.1);

  // Bloom post-processing (neon glow)
  const bloomPass = new UnrealBloomPass(
    new THREE.Vector2(window.innerWidth, window.innerHeight),
    isMobile ? 0.6 : 1.2, // strength
    0.4, // radius
    0.85 // threshold
  );
  graph.postProcessingComposer().addPass(bloomPass);

  // Responsive resize
  window.addEventListener("resize", () => {
    graph.width(window.innerWidth).height(window.innerHeight);
  });
}

// === Interactions ===
function handleNodeClick(node) {
  if (!node) return;
  selectedNode = node;
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
  hideDetail();
}

// === Detail panel ===
function setupDetailPanel() {
  document.getElementById("detail-close").addEventListener("click", () => {
    selectedNode = null;
    hideDetail();
  });
}

function showDetail(node) {
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

  // Tracks
  const tracksList = document.getElementById("detail-tracks");
  tracksList.innerHTML = "";
  for (const t of (data.tracks || []).slice(0, 10)) {
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
