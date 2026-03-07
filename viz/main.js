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

// === State ===
let graphData = null;
let graph = null; // also exposed as window._graph for debugging
let SPREAD = 5.0; // recalculated after data load
let selectedNode = null;
let selectedNeighborIds = new Set();
let hoveredNode = null;
let selectedCommunity = null; // community id when clicking legend
let initialCamera = null; // { pos, lookAt } saved after first layout
let cameraAnimating = false; // true during programmatic camera flights
let graphRadius = 1000; // bounding sphere radius, set after layout
let showLabels = false;
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
const nodeById = new Map(); // id -> copy of original node (pre-SPREAD)
const liveNodeById = new Map(); // id -> live node object from graphData (post-SPREAD)
const neighborMap = new Map(); // nodeId -> [{node, weight}]
let labelledNodeIds = new Set(); // top N nodes that get permanent labels

// === Sprite cache (Step 2) ===
const spriteCache = new Map(); // nodeId -> SpriteText

// === Tracks lazy cache (Step 5) ===
let tracksData = null; // loaded on first click

// === Deezer preview playback ===
let previewAudio = null; // current Audio instance
let previewBtn = null; // current playing button element

function deezerJsonp(deezerId) {
  return new Promise((resolve, reject) => {
    const cb = `_dz_${Date.now()}`;
    const script = document.createElement("script");
    script.src = `https://api.deezer.com/track/${deezerId}?output=jsonp&callback=${cb}`;
    const cleanup = () => {
      delete window[cb];
      script.remove();
      clearTimeout(timer);
    };
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error("JSONP timeout"));
    }, 10000);
    window[cb] = (data) => {
      cleanup();
      resolve(data);
    };
    script.onerror = () => {
      cleanup();
      reject(new Error("JSONP failed"));
    };
    document.head.appendChild(script);
  });
}

async function playDeezerPreview(deezerId, btn) {
  // If clicking the same button that's playing, toggle pause/play
  if (previewAudio && previewBtn === btn) {
    if (previewAudio.paused) {
      previewAudio.play();
      btn.textContent = "⏸";
    } else {
      previewAudio.pause();
      btn.textContent = "▶";
    }
    return;
  }

  // Stop any current preview
  if (previewAudio) {
    previewAudio.pause();
    previewAudio = null;
    if (previewBtn) previewBtn.textContent = "▶";
  }

  btn.textContent = "…";

  try {
    const data = await deezerJsonp(deezerId);
    const previewUrl = data.preview;

    if (!previewUrl) {
      btn.textContent = "✕";
      setTimeout(() => (btn.textContent = "▶"), 2000);
      return;
    }

    previewAudio = new Audio(previewUrl);
    previewBtn = btn;
    btn.textContent = "⏸";

    previewAudio.addEventListener("ended", () => {
      btn.textContent = "▶";
      previewAudio = null;
      previewBtn = null;
    });

    previewAudio.addEventListener("error", () => {
      btn.textContent = "✕";
      setTimeout(() => (btn.textContent = "▶"), 2000);
      previewAudio = null;
      previewBtn = null;
    });

    previewAudio.play();
  } catch {
    btn.textContent = "✕";
    setTimeout(() => (btn.textContent = "▶"), 2000);
  }
}

// === Preset handling ===
let currentPreset = "full-scene";

function getPresetFromUrl() {
  const params = new URLSearchParams(window.location.search);
  return params.get("preset") || "full-scene";
}

function dataPath(file) {
  return `./data/${currentPreset}/${file}`;
}

// === Load data ===
async function init() {
  currentPreset = getPresetFromUrl();

  const res = await fetch(dataPath("graph.json"));
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
  // Scale spread with node count: ~5.0 for 3500 nodes, ~1.5 for 200 nodes
  SPREAD = Math.max(1.5, Math.sqrt(graphData.nodes.length / 140));
  for (const node of graphData.nodes) {
    node.fx = (node.x - 500) * SPREAD;
    node.fy = (node.y - 500) * SPREAD;
    node.fz = ((node.z || 500) - 500) * SPREAD;
    liveNodeById.set(node.id, node);
  }

  createGraph();
  buildLegend();
  setupSearch();
  setupDetailPanel();
  setupLabelsToggle();
  setupResetCamera();
  setupPresetSelector();
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

// === Node mesh cache ===
const meshCache = new Map(); // nodeId -> THREE.Mesh

function buildNodeObject(node) {
  let mesh = meshCache.get(node.id);
  if (!mesh) {
    const t = node.trackCount || 1;
    const val = Math.pow(Math.log(t + 1), 2);
    const radius = Math.cbrt(val) * 2.5;
    const baseColor = new THREE.Color(
      COMMUNITY_COLORS[node.community % COMMUNITY_COLORS.length]
    );
    const geometry = new THREE.SphereGeometry(radius, PERF.nodeResolution, PERF.nodeResolution);
    const material = new THREE.MeshStandardMaterial({
      color: baseColor,
      emissive: baseColor,
      emissiveIntensity: 0.6,
      roughness: 0.4,
      metalness: 0.1,
    });
    mesh = new THREE.Mesh(geometry, material);
    meshCache.set(node.id, mesh);
  }

  // Update material state (cheap — no geometry recreation)
  updateNodeMaterial(node, mesh);

  // Update sprite label
  // Remove old sprite children first
  for (let i = mesh.children.length - 1; i >= 0; i--) {
    mesh.remove(mesh.children[i]);
  }
  const sprite = getOrCreateSprite(node);
  if (sprite) {
    mesh.add(sprite);
  }

  return mesh;
}

function updateNodeMaterial(node, mesh) {
  const isSelected = selectedNode && node.id === selectedNode.id;
  const isNeighbor = selectedNode && selectedNeighborIds.has(node.id);
  const isHovered = hoveredNode && node.id === hoveredNode.id;
  const isCommunityMember = selectedCommunity !== null && node.community === selectedCommunity;
  // When a node is selected, softly highlight same-community peers
  const isSameCommunity = selectedNode && !isSelected && !isNeighbor
    && node.community === selectedNode.community;
  const mat = mesh.material;

  let color;
  if (selectedCommunity !== null) {
    // Legend community highlight mode
    color = isCommunityMember
      ? COMMUNITY_COLORS[node.community % COMMUNITY_COLORS.length]
      : "#0a0014";
  } else if (!selectedNode) {
    color = COMMUNITY_COLORS[node.community % COMMUNITY_COLORS.length];
  } else if (isSelected) {
    color = "#ffffff";
  } else if (isNeighbor || isSameCommunity) {
    color = COMMUNITY_COLORS[node.community % COMMUNITY_COLORS.length];
  } else {
    color = "#0a0014";
  }

  const c = new THREE.Color(color);
  mat.color.copy(c);
  mat.emissive.copy(c);

  let intensity;
  if (isSelected) intensity = 2.0;
  else if (isHovered) intensity = 1.5;
  else if (isNeighbor) intensity = 0.8;
  else if (isCommunityMember) intensity = 0.8;
  else if (isSameCommunity) intensity = 0.25;
  else if (selectedNode || selectedCommunity !== null) intensity = 0.1;
  else intensity = 0.6;
  mat.emissiveIntensity = intensity;

  // Scale up on hover for visual feedback
  const scale = isHovered ? 1.6 : 1.0;
  mesh.scale.set(scale, scale, scale);
}

// Fast material-only update for all visible nodes (no mesh recreation)
function refreshNodeMaterials() {
  // Determine which nodes need sprite updates
  const updateAll = showLabels;
  let spriteNodes;
  if (!updateAll) {
    spriteNodes = new Set();
    if (selectedNode) {
      spriteNodes.add(selectedNode.id);
      for (const id of selectedNeighborIds) spriteNodes.add(id);
    }
    // Also update nodes that HAD sprites before (to remove them)
    for (const id of spriteCache.keys()) spriteNodes.add(id);
  }

  for (const node of graphData.nodes) {
    const mesh = meshCache.get(node.id);
    if (!mesh) continue;
    updateNodeMaterial(node, mesh);

    if (updateAll || spriteNodes.has(node.id)) {
      for (let i = mesh.children.length - 1; i >= 0; i--) mesh.remove(mesh.children[i]);
      const sprite = getOrCreateSprite(node);
      if (sprite) mesh.add(sprite);
    }
  }
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
    .linkDirectionalParticles(0)
    .onNodeClick(handleNodeClick)
    .onNodeHover(handleNodeHover)
    .onBackgroundClick(handleBackgroundClick)
    .enableNodeDrag(false)
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
    graphRadius = radius;

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
      if (isUserInteracting || cameraAnimating) return;
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
    const initPos = { x: cx + initDist * 0.5, y: cy + initDist * 0.3, z: cz + initDist * 0.8 };
    const initLookAt = { x: cx, y: cy, z: cz };
    graph.cameraPosition(initPos, initLookAt, 0);
    initialCamera = { pos: { ...initPos }, lookAt: { ...initLookAt } };
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
  // Show label if: selected, neighbor of selected, or toggle is on (all nodes)
  if (!isSelected && !isNeighbor && !showLabels) {
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

  // Update visual properties
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
    sprite.textHeight = 8;
  } else {
    sprite.color = "#ffffff";
    sprite.backgroundColor = "rgba(0, 0, 0, 0.6)";
    sprite.textHeight = 8;
  }

  const t = node.trackCount || 1;
  const nodeSize = Math.pow(Math.log(t + 1), 2);
  const yOffset = isSelected
    ? Math.cbrt(nodeSize) * 5 + 10
    : Math.cbrt(nodeSize) * 4 + 6;
  sprite.position.set(0, yOffset, 0);
  return sprite;
}

// === Camera flight helper ===
function flyTo(pos, lookAt, duration = 2000) {
  cameraAnimating = true;
  graph.cameraPosition(pos, lookAt, duration);
  setTimeout(() => {
    cameraAnimating = false;
    const controls = graph.controls();
    controls.target.set(lookAt.x, lookAt.y, lookAt.z);
    controls.update();
  }, duration + 100);
}

// === Interactions ===
function handleNodeClick(node) {
  if (!node) return;
  selectedNode = node;
  // Keep selectedCommunity if set (from legend click), clear otherwise
  if (selectedCommunity !== null && node.community !== selectedCommunity) {
    selectedCommunity = null;
  }

  // Build neighbor set for highlighting
  const neighbors = neighborMap.get(node.id) || [];
  selectedNeighborIds = new Set(neighbors.map((n) => n.node?.id).filter(Boolean));

  // Refresh visual state (materials only — no mesh recreation)
  refreshNodeMaterials();
  // Single link refresh — triggers one digest cycle for all link props
  graph.linkVisibility(graph.linkVisibility());

  showDetail(node);

  // Fly camera to node — distance proportional to graph size
  const nx = node.x || 0;
  const ny = node.y || 0;
  const nz = node.z || 0;
  const flyDist = graphRadius * 0.3;
  flyTo(
    { x: nx + flyDist * 0.5, y: ny + flyDist * 0.3, z: nz + flyDist * 0.8 },
    { x: nx, y: ny, z: nz }
  );
}

let hoverSprite = null; // temporary sprite for hovered node

function handleNodeHover(node) {
  const prev = hoveredNode;
  hoveredNode = node || null;

  // Remove hover sprite from previous node
  if (prev && hoverSprite) {
    const prevMesh = meshCache.get(prev.id);
    if (prevMesh) prevMesh.remove(hoverSprite);
    hoverSprite = null;
  }

  // Update materials
  if (prev) {
    const mesh = meshCache.get(prev.id);
    if (mesh) updateNodeMaterial(prev, mesh);
  }
  if (hoveredNode) {
    const mesh = meshCache.get(hoveredNode.id);
    if (mesh) {
      updateNodeMaterial(hoveredNode, mesh);
      // Add hover label if no label already showing
      const isSelected = selectedNode && hoveredNode.id === selectedNode.id;
      const isNeighbor = selectedNode && selectedNeighborIds.has(hoveredNode.id);
      if (!isSelected && !isNeighbor && !showLabels) {
        hoverSprite = new SpriteText(hoveredNode.name.toUpperCase());
        hoverSprite.fontFace = "Inter, system-ui, sans-serif";
        hoverSprite.fontSize = 90;
        hoverSprite.fontWeight = "bold";
        hoverSprite.color = "#ffffff";
        hoverSprite.backgroundColor = "rgba(0, 0, 0, 0.7)";
        hoverSprite.borderRadius = 2;
        hoverSprite.padding = 1;
        hoverSprite.textHeight = 5;
        const t = hoveredNode.trackCount || 1;
        const nodeSize = Math.pow(Math.log(t + 1), 2);
        hoverSprite.position.y = Math.cbrt(nodeSize) * 4 + 8;
        mesh.add(hoverSprite);
      }
    }
  }

  // Pointer cursor
  const container = document.getElementById("graph-container");
  container.style.cursor = hoveredNode ? "pointer" : "default";
}

function handleBackgroundClick() {
  selectedNode = null;
  selectedNeighborIds = new Set();
  selectedCommunity = null;

  // Restore visual state (materials only — no mesh recreation)
  refreshNodeMaterials();
  // Single link refresh — triggers one digest cycle for all link props
  graph.linkVisibility(graph.linkVisibility());

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
    const res = await fetch(dataPath("graph_tracks.json"));
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
  const communityName = communityInfo?.name;
  const topArtists = communityInfo
    ? communityInfo.top_artists.slice(0, 3).join(", ")
    : "";
  document.getElementById("detail-community").textContent =
    communityName || (`#${communityIdx}` + (topArtists ? ` (${topArtists})` : ""));

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
    const titleHtml = t.url
      ? `<a href="${t.url}" target="_blank" rel="noopener">${escapeHtml(t.title)}</a>`
      : escapeHtml(t.title);
    const playBtn = t.deezerId
      ? `<button class="track-play" data-deezer-id="${t.deezerId}" title="Preview">▶</button>`
      : "";
    li.innerHTML = `${playBtn}${titleHtml}<span class="track-platform">${t.platform}</span>`;
    tracksList.appendChild(li);
  }
  // Attach play handlers
  tracksList.querySelectorAll(".track-play").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      playDeezerPreview(btn.dataset.deezerId, btn);
    });
  });

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
    li.addEventListener("click", () => {
      const realNode = liveNodeById.get(n.id);
      if (realNode) handleNodeClick(realNode);
    });
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

  const sorted = [...communities].sort((a, b) => b.size - a.size);

  for (const c of sorted) {
    const color = COMMUNITY_COLORS[c.id % COMMUNITY_COLORS.length];
    const label = c.name || c.top_artists.slice(0, 2).join(", ");

    const item = document.createElement("div");
    item.className = "legend-item";
    item.innerHTML = `<span class="legend-color" style="background:${color}"></span><span>${escapeHtml(label)} (${c.size})</span>`;
    item.addEventListener("click", () => {
      if (selectedCommunity === c.id) {
        // Toggle off
        handleBackgroundClick();
        return;
      }
      // Find the most connected node in this community
      const communityNodes = graphData.nodes
        .filter((n) => n.community === c.id)
        .sort((a, b) => b.connections - a.connections);
      const topNode = communityNodes[0];
      if (!topNode) return;
      selectedCommunity = c.id;
      handleNodeClick(topNode);
    });
    container.appendChild(item);
  }
}

// === Preset selector ===
async function setupPresetSelector() {
  const wrapper = document.getElementById("preset-selector");
  if (!wrapper) return;
  try {
    const res = await fetch("./data/presets.json");
    const presets = await res.json();
    if (presets.length <= 1) { wrapper.style.display = "none"; return; }

    const current = presets.find((p) => p.name === currentPreset) || presets[0];
    const toggle = wrapper.querySelector(".preset-toggle");
    const menu = wrapper.querySelector(".preset-menu");

    toggle.textContent = current.label;

    menu.innerHTML = "";
    for (const p of presets) {
      const item = document.createElement("button");
      item.textContent = p.label;
      item.title = `${p.nodes} artists, ${p.communities} communities`;
      item.classList.add("preset-item");
      if (p.name === currentPreset) item.classList.add("active");
      item.addEventListener("click", () => {
        if (p.name === currentPreset) { menu.classList.remove("open"); return; }
        const url = new URL(window.location);
        url.searchParams.set("preset", p.name);
        window.location.href = url.toString();
      });
      menu.appendChild(item);
    }

    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      menu.classList.toggle("open");
    });
    document.addEventListener("click", () => menu.classList.remove("open"));
  } catch {
    wrapper.style.display = "none";
  }
}

// === Reset camera ===
function setupResetCamera() {
  document.getElementById("reset-camera").addEventListener("click", () => {
    if (!initialCamera) return;
    handleBackgroundClick();
    flyTo(initialCamera.pos, initialCamera.lookAt);
  });
}

// === Labels toggle ===
let labelBatchId = 0; // incremented to cancel in-flight batches

function setupLabelsToggle() {
  const btn = document.getElementById("toggle-labels");
  btn.addEventListener("click", () => {
    showLabels = !showLabels;
    btn.classList.toggle("active", showLabels);

    if (!showLabels) {
      // Remove all at once (cheap — just detach sprites)
      labelBatchId++;
      for (const node of graphData.nodes) {
        const mesh = meshCache.get(node.id);
        if (!mesh) continue;
        for (let i = mesh.children.length - 1; i >= 0; i--) mesh.remove(mesh.children[i]);
      }
      spriteCache.clear();
      return;
    }

    // Progressive add: sort by distance to camera, batch in chunks
    const cam = graph.camera();
    const camPos = cam.position;
    const sorted = [...graphData.nodes].sort((a, b) => {
      const da = (a.fx - camPos.x) ** 2 + (a.fy - camPos.y) ** 2 + (a.fz - camPos.z) ** 2;
      const db = (b.fx - camPos.x) ** 2 + (b.fy - camPos.y) ** 2 + (b.fz - camPos.z) ** 2;
      return da - db;
    });

    const batchSize = 150;
    const batchId = ++labelBatchId;
    let idx = 0;

    const fadingSprites = []; // sprites to fade in

    function processBatch() {
      if (batchId !== labelBatchId) return; // cancelled
      const end = Math.min(idx + batchSize, sorted.length);
      for (; idx < end; idx++) {
        const node = sorted[idx];
        const mesh = meshCache.get(node.id);
        if (!mesh) continue;
        for (let i = mesh.children.length - 1; i >= 0; i--) mesh.remove(mesh.children[i]);
        const sprite = getOrCreateSprite(node);
        if (sprite) {
          sprite.material.opacity = 0;
          sprite.material.transparent = true;
          mesh.add(sprite);
          fadingSprites.push(sprite);
        }
      }
      if (idx < sorted.length) {
        requestAnimationFrame(processBatch);
      }
    }
    requestAnimationFrame(processBatch);

    // Fade in all sprites gradually
    function fadeIn() {
      if (batchId !== labelBatchId) return;
      let allDone = true;
      for (const s of fadingSprites) {
        if (s.material.opacity < 1) {
          s.material.opacity = Math.min(s.material.opacity + 0.15, 1);
          allDone = false;
        }
      }
      if (!allDone) requestAnimationFrame(fadeIn);
    }
    requestAnimationFrame(fadeIn);
  });
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
