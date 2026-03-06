import ForceGraph3D from "3d-force-graph";
import SpriteText from "three-spritetext";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { AfterimagePass } from "three/examples/jsm/postprocessing/AfterimagePass.js";
import * as THREE from "three";

// === Color palette ===
const COMMUNITY_COLORS = [
  "#c02deb", // violeta neón (primary)
  "#65edfa", // cian eléctrico
  "#f000d8", // rosa neón
  "#a855f7", // purple
  "#22d3ee", // electric blue
  "#e040fb", // magenta
  "#7c4dff", // deep purple
  "#18ffff", // cyan bright
  "#ea80fc", // pink light
  "#b388ff", // lavender
  "#84ffff", // teal bright
  "#d500f9", // purple accent
];

const BG_COLOR = "#000000";
const SPREAD = 5.0;

// === State ===
let graphData = null;
let graph = null; // also exposed as window._graph for debugging
let selectedNode = null;
let selectedNeighborIds = new Set();
const isMobile = "ontouchstart" in window || navigator.maxTouchPoints > 0;

// === Performance profile ===
const PERF = {
  bloom: !isMobile,
  bloomStrength: isMobile ? 0 : 0.8,
  nodeResolution: isMobile ? 8 : 16,
  labelTopN: isMobile ? 15 : 60,
  linkDefaultVisible: false,
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

  // Step 1: Pre-compute fixed positions from exported 3D layout
  for (const node of graphData.nodes) {
    node.fx = (node.x - 500) * SPREAD;
    node.fy = (node.y - 500) * SPREAD;
    node.fz = ((node.z || 500) - 500) * SPREAD;
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

// === Node object builder (emissive sphere + label) ===
function buildNodeObject(node) {
  const isSelected = selectedNode && node.id === selectedNode.id;
  const isNeighbor = selectedNode && selectedNeighborIds.has(node.id);

  // Sphere size from nodeVal formula
  const t = node.trackCount || 1;
  const val = Math.pow(Math.log(t + 1), 2);
  const radius = Math.cbrt(val) * 2.5;

  // Color
  let color;
  if (!selectedNode) {
    color = COMMUNITY_COLORS[node.community % COMMUNITY_COLORS.length];
  } else if (isSelected) {
    color = "#ffffff";
  } else if (isNeighbor) {
    color = COMMUNITY_COLORS[node.community % COMMUNITY_COLORS.length];
  } else {
    color = "#0a0014";
  }

  const threeColor = new THREE.Color(color);
  const emissiveIntensity = isSelected ? 2.0 : (selectedNode && !isNeighbor ? 0.1 : 0.6);

  const geometry = new THREE.SphereGeometry(radius, PERF.nodeResolution, PERF.nodeResolution);
  const material = new THREE.MeshStandardMaterial({
    color: threeColor,
    emissive: threeColor,
    emissiveIntensity: emissiveIntensity,
    roughness: 0.4,
    metalness: 0.1,
  });

  const mesh = new THREE.Mesh(geometry, material);

  // Add sprite label
  const sprite = getOrCreateSprite(node);
  if (sprite) {
    mesh.add(sprite);
  }

  return mesh;
}

// === Create 3D graph ===
function createGraph() {
  const container = document.getElementById("graph-container");

  graph = ForceGraph3D()(container)
    .graphData(graphData)
    .backgroundColor(BG_COLOR)
    // Node sizing: log scale of track count for visible difference
    .nodeRelSize(6)
    .nodeVal((n) => {
      const t = n.trackCount || 1;
      return Math.pow(Math.log(t + 1), 2);
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
      return "#0a0014"; // dimmed
    })
    .nodeOpacity(1)
    .nodeResolution(PERF.nodeResolution)
    .nodeLabel("")
    // Custom emissive sphere + label sprite
    .nodeThreeObjectExtend(false)
    .nodeThreeObject((node) => {
      return buildNodeObject(node);
    })
    // Step 3a: Link visibility — hidden by default, show on click
    .linkVisibility((link) => {
      if (!selectedNode) return false;
      const src = typeof link.source === "object" ? link.source.id : link.source;
      const tgt = typeof link.target === "object" ? link.target.id : link.target;
      return src === selectedNode.id || tgt === selectedNode.id;
    })
    .linkColor((link) => {
      if (!selectedNode) return "rgba(192, 45, 235, 0.07)";
      const color =
        COMMUNITY_COLORS[selectedNode.community % COMMUNITY_COLORS.length];
      return color + "80"; // 50% opacity hex
    })
    .linkWidth((link) => {
      if (!selectedNode) return 0;
      return Math.sqrt(link.weight) * 2;
    })
    .linkOpacity(0.3)
    .linkCurvature(0.15)
    .linkCurveRotation(0)
    // Particles on selected node's links only
    .linkDirectionalParticles((link) => {
      if (!selectedNode) return 0;
      const src = typeof link.source === "object" ? link.source.id : link.source;
      const tgt = typeof link.target === "object" ? link.target.id : link.target;
      return (src === selectedNode.id || tgt === selectedNode.id) ? 4 : 0;
    })
    .linkDirectionalParticleWidth(1.5)
    .linkDirectionalParticleSpeed(0.005)
    .linkDirectionalParticleColor((link) => {
      if (!selectedNode) return "#c02deb";
      return COMMUNITY_COLORS[selectedNode.community % COMMUNITY_COLORS.length];
    })
    .onNodeClick(handleNodeClick)
    .onBackgroundClick(handleBackgroundClick)
    // Step 1: No force simulation — positions are pre-computed
    .warmupTicks(0)
    .cooldownTicks(0);

  // Add ambient light for MeshStandardMaterial
  const scene = graph.scene();
  scene.add(new THREE.AmbientLight(0xffffff, 0.3));

  // Step 4: Bloom only on desktop
  if (PERF.bloom) {
    const bloomPass = new UnrealBloomPass(
      new THREE.Vector2(window.innerWidth, window.innerHeight),
      PERF.bloomStrength, // strength
      0.4, // radius
      0.85 // threshold
    );
    const afterimagePass = new AfterimagePass(0.3);
    graph.postProcessingComposer().addPass(afterimagePass);

    graph.postProcessingComposer().addPass(bloomPass);
  }

  // Limit max zoom-out based on bounding sphere + camera FOV
  requestAnimationFrame(() => {
    // 1. Compute bounding sphere center (barycenter)
    let cx = 0, cy = 0, cz = 0;
    const N = graphData.nodes.length;
    for (const n of graphData.nodes) {
      cx += (n.x - 500) * SPREAD;
      cy += (n.y - 500) * SPREAD;
      cz += ((n.z || 500) - 500) * SPREAD;
    }
    cx /= N; cy /= N; cz /= N;

    // 2. Compute bounding sphere radius (P90 to ignore outliers)
    const radii = [];
    for (const n of graphData.nodes) {
      const dx = (n.x - 500) * SPREAD - cx;
      const dy = (n.y - 500) * SPREAD - cy;
      const dz = ((n.z || 500) - 500) * SPREAD - cz;
      radii.push(Math.sqrt(dx * dx + dy * dy + dz * dz));
    }
    radii.sort((a, b) => a - b);
    const radius = radii[Math.floor(radii.length * 0.95)];

    // 3. Camera distance to fit sphere in view: d = r / tan(fov/2)
    const camera = graph.camera();
    const fovRad = (camera.fov * Math.PI) / 180;
    const maxDist = radius / Math.tan(fovRad / 2);

    // 4. Set controls target to barycenter and limit distance
    const controls = graph.controls();
    controls.target.set(cx, cy, cz);
    controls.maxDistance = maxDist;
    controls.update();

    // 5. Slow idle rotation around the look-at target
    let isUserInteracting = false;
    let idleTimer = null;
    const canvas = graph.renderer().domElement;
    const startInteraction = () => {
      isUserInteracting = true;
      clearTimeout(idleTimer);
    };
    const endInteraction = () => {
      idleTimer = setTimeout(() => { isUserInteracting = false; }, 500);
    };
    canvas.addEventListener("mousedown", startInteraction);
    canvas.addEventListener("wheel", startInteraction);
    canvas.addEventListener("touchstart", startInteraction);
    canvas.addEventListener("mouseup", endInteraction);
    canvas.addEventListener("touchend", endInteraction);
    canvas.addEventListener("wheel", () => {
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => { isUserInteracting = false; }, 500);
    });

    const rotSpeed = 0.00042;
    const center = { x: cx, y: cy, z: cz };
    (function autoRotate() {
      requestAnimationFrame(autoRotate);
      if (isUserInteracting) return;
      const cam = graph.camera();
      const dx = cam.position.x - center.x;
      const dz = cam.position.z - center.z;
      const cos = Math.cos(rotSpeed);
      const sin = Math.sin(rotSpeed);
      cam.position.x = center.x + dx * cos - dz * sin;
      cam.position.z = center.z + dx * sin + dz * cos;
      cam.lookAt(center.x, center.y, center.z);
    })();

    // 6. Position camera looking at the barycenter from a nice angle
    const initDist = maxDist * 0.6;
    graph.cameraPosition(
      { x: cx + initDist * 0.5, y: cy + initDist * 0.3, z: cz + initDist * 0.8 },
      { x: cx, y: cy, z: cz },
      0 // instant, no animation
    );
  });

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
    sprite.backgroundColor = "rgba(10, 0, 20, 0.95)";
    sprite.textHeight = 6;
  } else if (isNeighbor) {
    sprite.color = "rgba(255, 255, 255, 0.85)";
    sprite.backgroundColor = "rgba(0, 0, 0, 0.7)";
    sprite.textHeight = 3.5;
  } else if (selectedNode) {
    // Permanent label but not related — dim it
    sprite.color = "rgba(255, 255, 255, 0.15)";
    sprite.backgroundColor = "rgba(0, 0, 0, 0.3)";
    sprite.textHeight = 4;
  } else {
    sprite.color = "#ffffff";
    sprite.backgroundColor = "rgba(0, 0, 0, 0.6)";
    sprite.textHeight = 4;
  }

  const t = node.trackCount || 1;
  const nodeSize = Math.pow(Math.log(t + 1), 2);
  const yOffset = isSelected
    ? Math.cbrt(nodeSize) * 5 + 10
    : Math.cbrt(nodeSize) * 4 + 6;
  sprite.position.set(0, yOffset, 0);
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
  graph.linkDirectionalParticles(graph.linkDirectionalParticles());
  graph.nodeThreeObject(graph.nodeThreeObject());

  showDetail(node);

  // Focus camera on node
  const distance = 500;
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

  // Restore visual state (clear particles too)
  graph.nodeColor(graph.nodeColor());
  graph.linkVisibility(graph.linkVisibility());
  graph.linkColor(graph.linkColor());
  graph.linkWidth(graph.linkWidth());
  graph.linkDirectionalParticles(graph.linkDirectionalParticles());
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
