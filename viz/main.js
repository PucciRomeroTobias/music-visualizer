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

const INITIAL_ROTATE_DELAY_MS = 500;
const IDLE_ROTATE_DELAY_MS = 5000;
const HIT_RADIUS_SCALE = isMobile ? 2.2 : 1.8;
const HIT_RADIUS_PADDING = isMobile ? 3.5 : 2.25;
const DENSE_CLUSTER_RELAX_ITERATIONS = 2;
const DENSE_CLUSTER_RELAX_STRENGTH = 0.6;
const DENSE_CLUSTER_MAX_SHIFT = 4.5;
const DENSE_CLUSTER_BASE_GAP = isMobile ? 8 : 6;
const MAX_SELECTION_LABEL_NEIGHBORS = isMobile ? 8 : 16;
const DENSE_SELECTION_DISTANCE_BOOST = isMobile ? 1.55 : 1.35;

let pauseAutoRotate = () => {};
let deferAutoRotate = () => {};

// === Node indexes ===
const nodeById = new Map(); // id -> copy of original node (pre-SPREAD)
const liveNodeById = new Map(); // id -> live node object from graphData (post-SPREAD)
const neighborMap = new Map(); // nodeId -> [{node, weight}]
const navHistory = []; // stack of visited node ids for back navigation
let navHistoryIndex = -1; // current position in navHistory
let navProgrammatic = false; // true when navigating via arrows (skip push)
let labelledNodeIds = new Set(); // top N nodes that get permanent labels
let selectedLabelIds = new Set();

// === Sprite cache (Step 2) ===
const spriteCache = new Map(); // nodeId -> SpriteText

// === Tracks lazy cache (Step 5) ===
let tracksData = null; // loaded on first click

// === Deezer preview playback ===
let previewAudio = null; // current Audio instance
let previewBtn = null; // current playing button element
let previewDeezerId = null; // deezerId currently playing

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
  // If clicking the same track that's playing, toggle pause/play
  if (previewAudio && previewDeezerId === deezerId) {
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
    previewDeezerId = deezerId;
    btn.textContent = "⏸";

    previewAudio.addEventListener("ended", () => {
      btn.textContent = "▶";
      previewAudio = null;
      previewBtn = null;
      previewDeezerId = null;
    });

    previewAudio.addEventListener("error", () => {
      btn.textContent = "✕";
      setTimeout(() => (btn.textContent = "▶"), 2000);
      previewAudio = null;
      previewBtn = null;
      previewDeezerId = null;
    });

    previewAudio.play();
  } catch {
    btn.textContent = "✕";
    setTimeout(() => (btn.textContent = "▶"), 2000);
  }
}

// === Preset & graph type handling ===
let currentPreset = "bounce-focus";
let currentGraphType = "artist";

function getParamsFromUrl() {
  const params = new URLSearchParams(window.location.search);
  return {
    preset: params.get("preset") || "bounce-focus",
  };
}

function normalizeDiscoverUrl() {
  const url = new URL(window.location);
  if (!url.searchParams.has("type")) return;
  url.searchParams.delete("type");
  window.history.replaceState({}, "", url.toString());
}

function dataPath(file) {
  return `./data/${currentGraphType}/${currentPreset}/${file}`;
}

function getNodeSizeMetric(node) {
  return currentGraphType === "track" ? (node.playlists || 1) : (node.trackCount || 1);
}

function getNodeVisualRadius(node) {
  const metric = getNodeSizeMetric(node);
  const value = Math.pow(Math.log(metric + 1), 2);
  return Math.cbrt(value) * 2.5;
}

function getNodeHitRadius(node) {
  const radius = getNodeVisualRadius(node);
  return Math.max(radius * HIT_RADIUS_SCALE, radius + HIT_RADIUS_PADDING);
}

function getNodeWorldPosition(node) {
  return {
    x: Number.isFinite(node.fx) ? node.fx : (node.x - 500) * SPREAD,
    y: Number.isFinite(node.fy) ? node.fy : (node.y - 500) * SPREAD,
    z: Number.isFinite(node.fz) ? node.fz : ((node.z || 500) - 500) * SPREAD,
  };
}

function getDeterministicUnitVector(aId, bId) {
  const seed = hashCode(`${aId}:${bId}`);
  const angle = (seed % 360) * (Math.PI / 180);
  const z = ((((seed >> 8) % 200) / 100) - 1) * 0.35;
  const planar = Math.sqrt(Math.max(0.1, 1 - z * z));
  return {
    x: Math.cos(angle) * planar,
    y: Math.sin(angle) * planar,
    z,
  };
}

function relaxDenseClusters(nodes) {
  const communityBuckets = new Map();
  for (const node of nodes) {
    if (!communityBuckets.has(node.community)) {
      communityBuckets.set(node.community, []);
    }
    communityBuckets.get(node.community).push(node);
  }

  for (const communityNodes of communityBuckets.values()) {
    if (communityNodes.length < 2) continue;

    for (let iteration = 0; iteration < DENSE_CLUSTER_RELAX_ITERATIONS; iteration++) {
      const deltas = new Map(communityNodes.map((node) => [node.id, { x: 0, y: 0, z: 0 }]));
      let movedAny = false;

      for (let i = 0; i < communityNodes.length; i++) {
        const a = communityNodes[i];
        const radiusA = getNodeVisualRadius(a);

        for (let j = i + 1; j < communityNodes.length; j++) {
          const b = communityNodes[j];
          const radiusB = getNodeVisualRadius(b);
          const minDist = Math.max(
            (radiusA + radiusB) * 1.35,
            radiusA + radiusB + DENSE_CLUSTER_BASE_GAP
          );

          let dx = b.fx - a.fx;
          let dy = b.fy - a.fy;
          let dz = b.fz - a.fz;
          let distSq = dx * dx + dy * dy + dz * dz;

          if (distSq >= minDist * minDist) continue;

          if (distSq < 0.0001) {
            const dir = getDeterministicUnitVector(a.id, b.id);
            dx = dir.x;
            dy = dir.y;
            dz = dir.z;
            distSq = dx * dx + dy * dy + dz * dz;
          }

          const dist = Math.sqrt(distSq);
          const ux = dx / dist;
          const uy = dy / dist;
          const uz = dz / dist;
          const push = (minDist - dist) * DENSE_CLUSTER_RELAX_STRENGTH * 0.5;

          const deltaA = deltas.get(a.id);
          const deltaB = deltas.get(b.id);
          deltaA.x -= ux * push;
          deltaA.y -= uy * push;
          deltaA.z -= uz * push;
          deltaB.x += ux * push;
          deltaB.y += uy * push;
          deltaB.z += uz * push;
          movedAny = true;
        }
      }

      if (!movedAny) break;

      for (const node of communityNodes) {
        const delta = deltas.get(node.id);
        const deltaMag = Math.hypot(delta.x, delta.y, delta.z);
        if (!deltaMag) continue;

        const clamp = Math.min(1, DENSE_CLUSTER_MAX_SHIFT / deltaMag);
        node.fx += delta.x * clamp;
        node.fy += delta.y * clamp;
        node.fz += delta.z * clamp;
        node.x = node.fx;
        node.y = node.fy;
        node.z = node.fz;
      }
    }
  }
}

// === Load data ===
async function init() {
  const params = getParamsFromUrl();
  currentPreset = params.preset;
  currentGraphType = "artist";
  normalizeDiscoverUrl();

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

  // Determine top N nodes by size metric for permanent labels
  const sorted = [...graphData.nodes].sort((a, b) => getNodeSizeMetric(b) - getNodeSizeMetric(a));
  labelledNodeIds = new Set(sorted.slice(0, PERF.labelTopN).map((n) => n.id));

  // Step 1: Pre-compute fixed positions from exported 3D layout
  // Scale spread with node count: ~5.0 for 3500 nodes, ~1.5 for 200 nodes
  SPREAD = Math.max(1.5, Math.sqrt(graphData.nodes.length / 140));
  for (const node of graphData.nodes) {
    node.fx = (node.x - 500) * SPREAD;
    node.fy = (node.y - 500) * SPREAD;
    node.fz = ((node.z || 500) - 500) * SPREAD;
    node.x = node.fx;
    node.y = node.fy;
    node.z = node.fz;
    liveNodeById.set(node.id, node);
  }
  relaxDenseClusters(graphData.nodes);

  createGraph();
  buildLegend();
  setupSearch();
  setupDetailPanel();
  setupLabelsToggle();
  setupResetCamera();
  setupPresetSelector();
  setupGraphTypeTabs();
  hideLoading();
}

function autoSelectRandom() {
  if (!graphData || !graphData.nodes.length) return;
  // Sort by degree (neighbor count), pick random from top 30
  const sorted = [...graphData.nodes].sort((a, b) => {
    const da = (neighborMap.get(a.id) || []).length;
    const db = (neighborMap.get(b.id) || []).length;
    return db - da;
  });
  const top = sorted.slice(0, 30);
  const pick = top[Math.floor(Math.random() * top.length)];
  if (pick) handleNodeClick(pick);
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

function clearNodeOverlays(mesh) {
  for (let i = mesh.children.length - 1; i >= 0; i--) {
    const child = mesh.children[i];
    if (child.userData?.kind === "hit-area") continue;
    mesh.remove(child);
  }
}

function attachNodeOverlay(mesh, overlay, kind) {
  overlay.userData = { ...(overlay.userData || {}), kind };
  mesh.add(overlay);
  return overlay;
}

function buildNodeObject(node) {
  let mesh = meshCache.get(node.id);
  if (!mesh) {
    const radius = getNodeVisualRadius(node);
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

    const hitArea = new THREE.Mesh(
      new THREE.SphereGeometry(
        getNodeHitRadius(node),
        Math.max(8, PERF.nodeResolution),
        Math.max(8, PERF.nodeResolution)
      ),
      new THREE.MeshBasicMaterial({
        transparent: true,
        opacity: 0,
        depthWrite: false,
      })
    );
    hitArea.material.colorWrite = false;
    hitArea.userData = { kind: "hit-area" };
    mesh.add(hitArea);

    meshCache.set(node.id, mesh);
  }

  // Update material state (cheap — no geometry recreation)
  updateNodeMaterial(node, mesh);

  // Update sprite label
  // Remove old sprite children first
  clearNodeOverlays(mesh);
  const sprite = getOrCreateSprite(node);
  if (sprite) {
    attachNodeOverlay(mesh, sprite, "node-sprite");
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

  // Interpolate between normal and selection state using selectionFade
  const baseColor = COMMUNITY_COLORS[node.community % COMMUNITY_COLORS.length];
  const baseIntensity = 0.6;

  let targetIntensity;
  if (isSelected) targetIntensity = 2.0;
  else if (isHovered) targetIntensity = 1.5;
  else if (isNeighbor) targetIntensity = 0.8;
  else if (isCommunityMember) targetIntensity = 0.8;
  else if (isSameCommunity) targetIntensity = 0.25;
  else if (selectedNode || selectedCommunity !== null) targetIntensity = 0.1;
  else targetIntensity = baseIntensity;

  const fade = selectionFade;
  const cBase = new THREE.Color(baseColor);
  const cTarget = new THREE.Color(color);
  const c = cBase.lerp(cTarget, fade);
  const intensity = baseIntensity + (targetIntensity - baseIntensity) * fade;

  mat.color.copy(c);
  mat.emissive.copy(c);
  mat.emissiveIntensity = intensity;

  // Scale up selected nodes so they read better inside dense clusters
  let scale = 1.0;
  if (isSelected) scale = isHovered ? 1.7 : 1.45;
  else if (isHovered) scale = 1.6;
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
      for (const id of selectedLabelIds) spriteNodes.add(id);
    }
    // Also update nodes that HAD sprites before (to remove them)
    for (const id of spriteCache.keys()) spriteNodes.add(id);
  }

  for (const node of graphData.nodes) {
    const mesh = meshCache.get(node.id);
    if (!mesh) continue;
    updateNodeMaterial(node, mesh);

    if (updateAll || spriteNodes.has(node.id)) {
      clearNodeOverlays(mesh);
      const sprite = getOrCreateSprite(node);
      if (sprite) attachNodeOverlay(mesh, sprite, "node-sprite");
    }
  }
}

let selectionFade = 1; // 0 = no selection visible, 1 = fully visible

function fadeInSelection(duration = 600) {
  selectionFade = 0;

  // Show links at 0 opacity, then animate
  graph.linkVisibility(graph.linkVisibility());
  graph.linkOpacity(0);

  // Add sprites immediately at opacity 0
  const fadeSprites = [];
  if (selectedNode) {
    const nodesToLabel = [...selectedLabelIds];
    for (const id of nodesToLabel) {
      const node = graphData.nodes.find((n) => n.id === id);
      const mesh = meshCache.get(id);
      if (!node || !mesh) continue;
      // Clear existing children
      clearNodeOverlays(mesh);
      const sprite = getOrCreateSprite(node);
      if (sprite) {
        sprite.material.opacity = 0;
        sprite.material.transparent = true;
        attachNodeOverlay(mesh, sprite, "node-sprite");
        fadeSprites.push(sprite);
      }
    }
  }

  const start = performance.now();
  function tick(now) {
    const t = Math.min((now - start) / duration, 1);
    selectionFade = t * (2 - t); // ease-out quad

    // Animate link opacity
    graph.linkOpacity(0.3 * selectionFade);

    // Fade in sprites
    for (const s of fadeSprites) {
      s.material.opacity = selectionFade;
    }

    // Fast material-only pass (no sprite recreation)
    for (const node of graphData.nodes) {
      const mesh = meshCache.get(node.id);
      if (mesh) updateNodeMaterial(node, mesh);
    }

    if (t < 1) {
      requestAnimationFrame(tick);
    }
  }
  requestAnimationFrame(tick);
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
      const t = getNodeSizeMetric(n);
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
    .showNavInfo(false)
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
      const pos = getNodeWorldPosition(n);
      cx += pos.x;
      cy += pos.y;
      cz += pos.z;
    }
    cx /= N; cy /= N; cz /= N;

    // 2. Compute bounding sphere radius (P90 to ignore outliers)
    const radii = [];
    for (const n of graphData.nodes) {
      const pos = getNodeWorldPosition(n);
      const dx = pos.x - cx;
      const dy = pos.y - cy;
      const dz = pos.z - cz;
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
    controls.zoomSpeed = 2.0;
    controls.update();

    // 5. Slow idle rotation around the look-at target
    let isUserInteracting = true;
    let idleTimer = null;
    const scheduleIdleRotation = (delayMs = IDLE_ROTATE_DELAY_MS) => {
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => {
        isUserInteracting = false;
      }, delayMs);
    };
    pauseAutoRotate = () => {
      isUserInteracting = true;
      clearTimeout(idleTimer);
    };
    deferAutoRotate = (delayMs = IDLE_ROTATE_DELAY_MS) => {
      pauseAutoRotate();
      scheduleIdleRotation(delayMs);
    };
    const canvas = graph.renderer().domElement;
    const startInteraction = () => {
      pauseAutoRotate();
    };
    const endInteraction = () => {
      deferAutoRotate(IDLE_ROTATE_DELAY_MS);
    };
    canvas.addEventListener("mousedown", startInteraction);
    canvas.addEventListener("touchstart", startInteraction);
    canvas.addEventListener("mouseup", endInteraction);
    canvas.addEventListener("touchend", endInteraction);
    canvas.addEventListener("wheel", () => deferAutoRotate(IDLE_ROTATE_DELAY_MS));
    deferAutoRotate(INITIAL_ROTATE_DELAY_MS);

    const rotSpeed = 0.00021;
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
  const isLabelNeighbor = !isSelected && selectedLabelIds.has(node.id);
  // Show label if: selected, curated selection context, or toggle is on (all nodes)
  if (!isSelected && !isLabelNeighbor && !showLabels) {
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
    sprite.textHeight = isMobile ? 7.2 : 6.4;
  } else if (isLabelNeighbor) {
    sprite.color = "rgba(255, 255, 255, 0.85)";
    sprite.backgroundColor = "rgba(0, 0, 0, 0.7)";
    sprite.textHeight = isMobile ? 3.8 : 3.5;
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

  const t = getNodeSizeMetric(node);
  const nodeSize = Math.pow(Math.log(t + 1), 2);
  const yOffset = isSelected
    ? Math.cbrt(nodeSize) * 5.5 + (isMobile ? 14 : 12)
    : Math.cbrt(nodeSize) * 4 + 6;
  sprite.position.set(0, yOffset, 0);

  // Depth testing: labels behind spheres get occluded
  sprite.material.depthTest = !isSelected;
  sprite.material.depthWrite = false;
  // Bigger/more important nodes render on top of smaller ones
  sprite.renderOrder = isSelected ? 3000 : (isLabelNeighbor ? 800 : Math.floor(nodeSize));

  return sprite;
}

// === Camera flight helper ===
function flyTo(pos, lookAt, duration = 1200, onLand) {
  pauseAutoRotate();
  cameraAnimating = true;
  graph.cameraPosition(pos, lookAt, duration);
  setTimeout(() => {
    cameraAnimating = false;
    const controls = graph.controls();
    controls.target.set(lookAt.x, lookAt.y, lookAt.z);
    controls.update();
    deferAutoRotate(IDLE_ROTATE_DELAY_MS);
    if (onLand) onLand();
  }, duration + 50);
}

// === Interactions ===
function handleNodeClick(node) {
  if (!node) return;

  selectedNode = node;

  // Track navigation history
  if (!navProgrammatic) {
    if (navHistoryIndex < navHistory.length - 1) {
      navHistory.splice(navHistoryIndex + 1);
    }
    navHistory.push(node.id);
    navHistoryIndex = navHistory.length - 1;
  }
  navProgrammatic = false;
  updateNavButtons();
  // Keep selectedCommunity if set (from legend click), clear otherwise
  if (selectedCommunity !== null && node.community !== selectedCommunity) {
    selectedCommunity = null;
  }

  // Build neighbor set (lightweight — just a Set of IDs)
  const neighbors = neighborMap.get(node.id) || [];
  selectedNeighborIds = new Set(neighbors.map((n) => n.node?.id).filter(Boolean));
  selectedLabelIds = new Set([
    node.id,
    ...neighbors
      .filter((n) => n.node?.id)
      .sort((a, b) => b.weight - a.weight)
      .slice(0, MAX_SELECTION_LABEL_NEIGHBORS)
      .map((n) => n.node.id),
  ]);

  // Show detail panel immediately (DOM-only, fast)
  showDetail(node);

  // Start camera flight — heavy visual updates deferred to landing
  const nx = node.x || 0;
  const ny = node.y || 0;
  const nz = node.z || 0;
  const densityBoost = 1 + Math.min(1, neighbors.length / 24) * (DENSE_SELECTION_DISTANCE_BOOST - 1);
  const flyDist = graphRadius * 0.3 * densityBoost;
  flyTo(
    { x: nx + flyDist * 0.5, y: ny + flyDist * 0.3, z: nz + flyDist * 0.8 },
    { x: nx, y: ny, z: nz },
    1200,
    () => {
      // Fade in visual updates after landing
      fadeInSelection();
    }
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
        const t = getNodeSizeMetric(hoveredNode);
        const nodeSize = Math.pow(Math.log(t + 1), 2);
        hoverSprite.position.y = Math.cbrt(nodeSize) * 4 + 8;
        attachNodeOverlay(mesh, hoverSprite, "hover-sprite");
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
  selectedLabelIds = new Set();
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

// Step 5: Lazy-load tracks (artist mode only)
async function loadTracks() {
  if (currentGraphType === "track") return {};
  if (tracksData) return tracksData;
  try {
    const res = await fetch(dataPath("graph_tracks.json"));
    tracksData = await res.json();
  } catch {
    tracksData = {};
  }
  return tracksData;
}

function formatDuration(seconds) {
  if (!seconds) return "--:--";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

async function showDetail(node) {
  // Use stored copy since 3d-force-graph strips custom fields from node objects
  const data = nodeById.get(node.id) || node;
  const isTrackMode = currentGraphType === "track";

  const panel = document.getElementById("detail-panel");
  document.getElementById("detail-name").textContent = data.name;

  // Artist subtitle (track mode only)
  const subtitleEl = document.getElementById("detail-artist-subtitle");
  if (isTrackMode && data.artistName) {
    subtitleEl.textContent = data.artistName;
    subtitleEl.style.display = "block";
  } else {
    subtitleEl.style.display = "none";
  }

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

  // Stats — dynamic based on mode
  const statsEl = document.getElementById("detail-stats");
  statsEl.innerHTML = "";
  if (isTrackMode) {
    statsEl.innerHTML = `
      <div class="stat-item">
        <div class="stat-value">${data.connections ?? 0}</div>
        <div class="stat-label">CONNECTIONS</div>
      </div>
      <div class="stat-item">
        <div class="stat-value">${data.playlists ?? 0}</div>
        <div class="stat-label">PLAYLISTS</div>
      </div>
      <div class="stat-item">
        <div class="stat-value">${formatDuration(data.duration)}</div>
        <div class="stat-label">DURATION</div>
      </div>
    `;
  } else {
    statsEl.innerHTML = `
      <div class="stat-item">
        <div class="stat-value">${data.connections ?? 0}</div>
        <div class="stat-label">CONNECTIONS</div>
      </div>
      <div class="stat-item">
        <div class="stat-value">${data.playlists ?? 0}</div>
        <div class="stat-label">PLAYLISTS</div>
      </div>
      <div class="stat-item">
        <div class="stat-value">${data.trackCount ?? 0}</div>
        <div class="stat-label">TRACKS</div>
      </div>
    `;
  }

  // Inline play button (track mode with deezerId)
  const playSection = document.getElementById("detail-play-section");
  if (isTrackMode && data.deezerId) {
    playSection.style.display = "block";
    const playBtn = document.getElementById("detail-play-btn");
    playBtn.textContent = "▶";
    playBtn.onclick = (e) => {
      e.stopPropagation();
      playDeezerPreview(data.deezerId, playBtn);
    };
  } else {
    playSection.style.display = "none";
  }

  // Tracks section (artist mode) or hidden (track mode)
  const tracksSection = document.getElementById("detail-tracks-section");
  const tracksList = document.getElementById("detail-tracks");
  if (isTrackMode) {
    tracksSection.style.display = "none";
  } else {
    tracksSection.style.display = "block";
    document.getElementById("detail-tracks-label").textContent = "TRACKS";
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
    tracksList.querySelectorAll(".track-play").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        playDeezerPreview(btn.dataset.deezerId, btn);
      });
    });
  }

  // Connected nodes (top 10 by weight)
  document.getElementById("detail-neighbors-label").textContent =
    isTrackMode ? "CONNECTED TRACKS" : "CONNECTED ARTISTS";
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
  document.getElementById("detail-prev")?.classList.add("hidden");
  document.getElementById("detail-next")?.classList.add("hidden");
}

// === Detail nav arrows ===
function updateNavButtons() {
  const prevBtn = document.getElementById("detail-prev");
  const nextBtn = document.getElementById("detail-next");
  if (!prevBtn || !nextBtn) return;

  const showArrows = selectedNode != null;
  prevBtn.classList.toggle("hidden", !showArrows);
  nextBtn.classList.toggle("hidden", !showArrows);

  if (showArrows) {
    prevBtn.disabled = navHistoryIndex <= 0;
    nextBtn.disabled = !getNextNeighbor();
  }
}

function getNextNeighbor() {
  if (!selectedNode) return null;
  const neighbors = (neighborMap.get(selectedNode.id) || [])
    .filter((n) => n.node);
  if (!neighbors.length) return null;

  const recent = new Set(navHistory.slice(-5));
  const sx = selectedNode.x || 0;
  const sy = selectedNode.y || 0;
  const sz = selectedNode.z || 0;

  // Score: distance + weight + randomness, then pick from top candidates
  const scored = neighbors
    .filter((n) => !recent.has(n.node.id))
    .map((n) => {
      const live = liveNodeById.get(n.node.id);
      const dx = (live?.x || 0) - sx;
      const dy = (live?.y || 0) - sy;
      const dz = (live?.z || 0) - sz;
      const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
      const score = dist / (graphRadius || 1) + n.weight * 0.3 + Math.random() * 0.5;
      return { node: n.node, score };
    })
    .sort((a, b) => b.score - a.score);

  // Pick random from top 5 candidates
  const top = scored.slice(0, 5);
  return top[Math.floor(Math.random() * top.length)]?.node || neighbors[0]?.node || null;
}

function setupDetailNav() {
  document.getElementById("detail-prev")?.addEventListener("click", () => {
    if (navHistoryIndex <= 0) return;
    navHistoryIndex--;
    const nodeId = navHistory[navHistoryIndex];
    const node = liveNodeById.get(nodeId);
    if (node) {
      navProgrammatic = true;
      handleNodeClick(node);
    }
  });

  document.getElementById("detail-next")?.addEventListener("click", () => {
    // If we have forward history, use it
    if (navHistoryIndex < navHistory.length - 1) {
      navHistoryIndex++;
      const nodeId = navHistory[navHistoryIndex];
      const node = liveNodeById.get(nodeId);
      if (node) {
        navProgrammatic = true;
        handleNodeClick(node);
      }
      return;
    }
    // Otherwise, go to best unvisited neighbor
    const next = getNextNeighbor();
    if (next) {
      const realNode = liveNodeById.get(next.id);
      if (realNode) handleNodeClick(realNode);
    }
  });
}
setupDetailNav();

// === Search ===
function setupSearch() {
  const input = document.getElementById("search-input");
  input.placeholder = currentGraphType === "track" ? "SEARCH TRACK..." : "SEARCH ARTIST...";
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
    const allPresets = await res.json();

    // Support both old array format and new {artist: [...], track: [...]} format
    const presets = Array.isArray(allPresets)
      ? allPresets
      : (allPresets[currentGraphType] || []);

    if (presets.length <= 1) { wrapper.style.display = "none"; return; }

    const current = presets.find((p) => p.name === currentPreset) || presets[0];
    const toggle = wrapper.querySelector(".preset-toggle");
    const menu = wrapper.querySelector(".preset-menu");

    toggle.textContent = current.label;

    menu.innerHTML = "";
    for (const p of presets) {
      const item = document.createElement("button");
      item.textContent = p.label;
      const nodeLabel = currentGraphType === "track" ? "tracks" : "artists";
      item.title = `${p.nodes} ${nodeLabel}, ${p.communities} communities`;
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

// === Graph type tabs ===
function setupGraphTypeTabs() {
  const tabs = document.querySelectorAll(".type-tab");
  if (!tabs.length) return;
  tabs.forEach((tab) => {
    if (tab.dataset.type === currentGraphType) {
      tab.classList.add("active");
    }
    tab.addEventListener("click", () => {
      const type = tab.dataset.type;
      if (type === currentGraphType) return;
      const url = new URL(window.location);
      url.searchParams.set("type", type);
      url.searchParams.set("preset", "bounce-focus");
      window.location.href = url.toString();
    });
  });
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
  if (!btn) return;
  btn.addEventListener("click", () => {
    showLabels = !showLabels;
    btn.classList.toggle("active", showLabels);

    if (!showLabels) {
      // Remove all at once (cheap — just detach sprites)
      labelBatchId++;
      for (const node of graphData.nodes) {
        const mesh = meshCache.get(node.id);
        if (!mesh) continue;
        clearNodeOverlays(mesh);
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
        clearNodeOverlays(mesh);
        const sprite = getOrCreateSprite(node);
        if (sprite) {
          sprite.material.opacity = 0;
          sprite.material.transparent = true;
          attachNodeOverlay(mesh, sprite, "node-sprite");
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
  setTimeout(() => {
    loading.remove();
    showWelcome();
  }, 600);
}

// === Welcome modal ===
function showWelcome() {
  // Always show welcome — it's brief and gives context
  const overlay = document.getElementById("welcome-overlay");
  if (!overlay) return;
  overlay.classList.remove("hidden");

  function dismiss() {
    overlay.classList.add("hidden");
    setTimeout(() => {
      overlay.remove();
      autoSelectRandom();
    }, 400);
  }

  document.getElementById("welcome-enter").addEventListener("click", dismiss);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) dismiss();
  });
}

// === Utils ===
function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}


// === Help panel ===
function setupHelp() {
  const btn = document.getElementById("help-btn");
  const overlay = document.getElementById("help-overlay");
  if (!btn || !overlay) return;

  function open() { overlay.classList.remove("hidden"); }
  function close() { overlay.classList.add("hidden"); }

  btn.addEventListener("click", open);
  document.getElementById("help-close").addEventListener("click", close);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
}
setupHelp();

// === Legend collapsible (mobile) ===
function setupLegendToggle() {
  const toggle = document.getElementById("legend-toggle");
  const legend = document.getElementById("legend");
  if (!toggle || !legend) return;

  toggle.addEventListener("click", () => {
    legend.classList.toggle("legend-open");
  });
}
setupLegendToggle();

// === Start ===
init();
