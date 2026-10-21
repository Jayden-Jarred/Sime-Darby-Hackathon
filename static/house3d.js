/**
 * house3d.js - 3D preview of the selected home (Member 4).
 *
 * Two views:
 *   Exterior  - the home on its street, slowly turning.
 *   Fittings  - walls turn see-through, upper floors lift away, and every
 *               fitting is coloured by its rip-out advice (stop / offer / keep).
 *               Hover a fitting to see its rip-out rate. On homes with more than
 *               one floor, a floor picker shows one floor at a time.
 * Selecting a floor or a fitting zooms the camera in on it.
 * Buyer view (colorBy: 'choice'): view.setChoice(fid, choice, name, upgradeId)
 * shows an upgrade in the finish the buyer picked (see LOOKS).
 *
 * Usage (see templates/dashboard.html):
 *   const view = mountHouse(el, { unit: "T2S", fittings: [...rip-out index rows] });
 *   view.setMode("fittings"); view.setFloor("ff"); view.focus("KIT-CAB"); view.highlight("KIT-CAB");
 * The floor picker fills an element with [data-floor-picker] containing a .seg.
 *
 * Models are simple massing built from boxes - illustrative, not SDP drawings.
 * Units are metres. +z faces the street.
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

// Advice icons. Their colours come from the page's --advice-stop / -offer / -keep
// CSS variables (set from dashboard.ADVICE_COLOUR), the same as the table badges.
export const STATUS = {
  stop:  { icon: '✕' },
  offer: { icon: '!' },
  keep:  { icon: '✓' },
};

export function statusOf(advice = '') {
  if (advice.startsWith('Stop')) return 'stop';
  if (advice.startsWith('Offer')) return 'offer';
  return 'keep';
}

const COL = {
  wall: '#f4eee2', party: '#e9e1d0', slab: '#d8d0bf', roof: '#ffffff',
  glass: '#7f9ba4', frame: '#f7f4ec', ground: '#c9c3ae', road: '#8f918b',
  paving: '#d2cab9', path: '#dcd5c4', grass: '#98ad7f', edge: '#6d685d',
  ghostRoof: '#b9b2ab', wood: '#b8996f', fabric: '#c9c1af', bed: '#ece6d8',
  accent: '#c4623f',
};
// Neighbours get slightly different paint, like a real terrace row.
const NEIGHBOUR_PAINT = ['#ece5d6', '#e3e6da', '#eedfd2', '#e6e2d8', '#efe6cf', '#e0e3dd'];

/** Small seeded random, so the trees and paint land in the same place every load. */
function seeded(a) {
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const STORE_KEY = 'rfh-house-view';

// Buyer view (colorBy: 'choice'): what will actually be installed.
export const CHOICE = {
  keep:    { color: '#7fa08a', label: 'Keep' },          // standard: sage, stands out from furniture
  opt_out: { color: '#b9b4a8', label: 'Opt out' },       // ghosted: not installed
  upgrade: { color: '#c4623f', label: 'Upgrade' },     // brand terracotta
};

// ---- upgrade finishes (buyer view) --------------------------------------
// Canvas painters for the finishes below; `rnd` is seeded so they look the same every load.
const rnd = seeded(11);
const grain = (base, line) => (g, s) => {
  g.fillStyle = base;
  g.fillRect(0, 0, s, s);
  g.strokeStyle = line;
  g.lineWidth = 1.2;
  for (let i = 0; i < 26; i++) {
    const x = rnd() * s;
    g.globalAlpha = 0.18 + rnd() * 0.25;
    g.beginPath();
    g.moveTo(x, 0);
    g.bezierCurveTo(x + (rnd() - 0.5) * 18, s / 3, x + (rnd() - 0.5) * 18, s * 2 / 3, x + (rnd() - 0.5) * 10, s);
    g.stroke();
  }
  g.globalAlpha = 1;
};
const brushed = (g, s) => {
  const gr = g.createLinearGradient(0, 0, s, s);
  gr.addColorStop(0, '#e6eaed');
  gr.addColorStop(1, '#b4bcc2');
  g.fillStyle = gr;
  g.fillRect(0, 0, s, s);
  for (let i = 0; i < 160; i++) {
    g.fillStyle = rnd() < 0.5 ? 'rgba(255,255,255,.2)' : 'rgba(90,100,108,.08)';
    g.fillRect(rnd() * s, 0, 1, s);
  }
};
const veins = (base, vein, n) => (g, s) => {
  g.fillStyle = base;
  g.fillRect(0, 0, s, s);
  g.strokeStyle = vein;
  g.lineCap = 'round';
  for (let i = 0; i < n; i++) {
    g.globalAlpha = 0.25 + rnd() * 0.35;
    g.lineWidth = 0.6 + rnd() * 1.6;
    let x = -10, y = rnd() * s;
    g.beginPath();
    g.moveTo(x, y);
    while (x < s + 10) {
      const nx = x + 20 + rnd() * 40, ny = y + (rnd() - 0.5) * 50;
      g.quadraticCurveTo((x + nx) / 2 + (rnd() - 0.5) * 20, (y + ny) / 2 + (rnd() - 0.5) * 20, nx, ny);
      x = nx; y = ny;
    }
    g.stroke();
  }
  g.globalAlpha = 1;
};
const speckle = (g, s) => {
  g.fillStyle = '#7d766d';
  g.fillRect(0, 0, s, s);
  const cols = ['#2a2724', '#3b3632', '#d9d2c6', '#b49a80', '#efe9de', '#55504a'];
  for (let i = 0; i < 2600; i++) {
    g.fillStyle = cols[Math.floor(rnd() * cols.length)];
    g.beginPath();
    g.arc(rnd() * s, rnd() * s, 0.6 + rnd() * 1.8, 0, Math.PI * 2);
    g.fill();
  }
};
const bigTile = (g, s) => {   // one 1200 x 600 mm polished tile
  g.fillStyle = '#dcd8d0';
  g.fillRect(0, 0, s, s);
  for (let i = 0; i < 40; i++) {
    g.fillStyle = rnd() < 0.5 ? 'rgba(255,255,255,.08)' : 'rgba(120,110,95,.05)';
    g.beginPath();
    g.arc(rnd() * s, rnd() * s, 10 + rnd() * 30, 0, Math.PI * 2);
    g.fill();
  }
  g.strokeStyle = '#b9b2a6';
  g.lineWidth = 3;
  g.strokeRect(0, 0, s, s);
};
const planks = (g, s) => {    // six 200 mm planks, 1.2 m long, joints staggered
  const oak = ['#c9a274', '#bf9566', '#d1ad80', '#b88d5e', '#c49a6b', '#cda679'];
  const w = s / 6;
  for (let i = 0; i < 6; i++) {
    const joint = rnd() * s;
    for (const [y0, y1] of [[0, joint], [joint, s]]) {
      g.fillStyle = oak[Math.floor(rnd() * oak.length)];
      g.fillRect(i * w, y0, w, y1 - y0);
    }
    g.strokeStyle = 'rgba(120,85,50,.35)';
    g.lineWidth = 1;
    g.strokeRect(i * w + 0.5, -1, w - 1, s + 2);
    g.beginPath(); g.moveTo(i * w, joint); g.lineTo(i * w + w, joint); g.stroke();
    g.strokeStyle = 'rgba(140,100,60,.3)';
    g.beginPath(); g.moveTo(i * w + w * (0.3 + rnd() * 0.4), 0); g.lineTo(i * w + w * (0.3 + rnd() * 0.4), s); g.stroke();
  }
};

/**
 * Each upgrade option as it looks in the buyer's 3D view, keyed by upgrade_id
 * (data/upgrades.csv) - the same finishes as the pictures in static/upgrades/.
 * An id not listed here shows as plain terracotta.
 *   paint    canvas pattern; repeat = times it repeats across a face
 *   tile     for floors: [x, z] metres one canvas covers
 *   glow     light colour (lights); cycle = [warm, cool] it slowly moves between
 *   variant  other geometry to show instead of the standard item
 */
export const LOOKS = {
  PLYWOOD:     { roughness: 0.7, paint: grain('#e6cda0', '#a87f4c') },
  ALUMINIUM:   { color: '#cdd4d9', roughness: 0.32, metalness: 0.75, paint: brushed },
  QUARTZ:      { roughness: 0.22, paint: veins('#f5f3ee', '#9d968b', 7), repeat: [3, 1] },
  GRANITE:     { roughness: 0.25, paint: speckle, repeat: [4, 1] },
  SINTERED:    { roughness: 0.55, paint: veins('#3d3e41', '#9a9b9e', 4), repeat: [3, 1] },
  SLIDING:     { color: '#dfe7eb', roughness: 0.05, metalness: 1 },   // mirror doors
  'WALK-IN':   { roughness: 0.65, paint: grain('#d6b585', '#a07a4b'), variant: 'open' },
  STUDY:       { roughness: 0.65, paint: grain('#ece2d2', '#b8a281'), variant: 'study' },
  'LED-WARM':  { color: '#fffaf0', glow: '#ffd59a', variant: 'recessed' },
  SMART:       { color: '#fffaf0', glow: '#fff1d6', cycle: ['#ffc677', '#c9ddff'], variant: 'recessed' },
  HOMOGENEOUS: { roughness: 0.14, paint: bigTile, tile: [1.2, 0.6] },
  VINYL:       { roughness: 0.6, paint: planks, tile: [1.2, 1.2] },
};

/**
 * options:
 *   colorBy      'advice' (SDP dashboard) or 'choice' (buyer Advisor)
 *   initialMode  'exterior' | 'fittings' (default: last view used)
 *   storeKey     sessionStorage key for remembering the view
 *   onPick(fid)  called when a fitting is clicked or tapped
 */
export function mountHouse(el, { unit, fittings, colorBy = 'advice', initialMode = null,
                                 storeKey = STORE_KEY, onPick = null }) {
  const canvasHost = el.querySelector('.house-canvas') || el;
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  } catch (err) {
    el.classList.add('no-webgl');
    return null;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.NeutralToneMapping;
  renderer.toneMappingExposure = 0.9;
  canvasHost.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog('#ebe4d5', 75, 200);
  // Soft studio-style environment light + reflections, generated in code (no download).
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.42;
  const rand = seeded(7);
  const bobbers = [];   // things that gently float (the location pin)
  const camera = new THREE.PerspectiveCamera(32, 1, 0.5, 500);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.maxPolarAngle = Math.PI * 0.47;
  controls.autoRotateSpeed = 0.55;
  controls.addEventListener('start', () => { controls.autoRotate = false; });

  // ---- lights -----------------------------------------------------------
  scene.add(new THREE.HemisphereLight('#f3f7ff', '#c9bea6', 0.8));
  const sun = new THREE.DirectionalLight('#ffe2bd', 2.9);   // warm late-afternoon sun
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.02;
  sun.shadow.intensity = 0.75;
  scene.add(sun, sun.target);

  // ---- registry of things that change between views ---------------------
  const info = new Map(fittings.map(f => [f.fitting_id, f]));
  const fades = [];          // materials that turn see-through
  const lifts = [];          // groups that rise in the Fittings view
  const fitMats = new Map(); // fitting_id -> material
  const fitMeshes = [];      // everything hover can hit

  function fadeMat(color, xray, { solid = 1, roughness = 0.92, metalness = 0, map = null, flat = false } = {}) {
    const mat = new THREE.MeshStandardMaterial({ color, roughness, metalness, map, flatShading: flat });
    const entry = { mat, solid, xray, meshes: [] };
    mat.userData.fade = entry;
    fades.push(entry);
    return mat;
  }
  function lineMat(solid, xray) {
    const mat = new THREE.LineBasicMaterial({ color: COL.edge, transparent: true, opacity: solid });
    fades.push({ mat, solid, xray, meshes: [], line: true });
    return mat;
  }
  const solidMat = (color, roughness = 0.9) => new THREE.MeshStandardMaterial({ color, roughness });

  const edgeLines = lineMat(0.22, 0.38);

  /** Box with its BOTTOM at y. */
  function box(w, h, d, mat, x, y, z, parent, { edges = false } = {}) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
    m.position.set(x, y + h / 2, z);
    m.castShadow = true;
    m.receiveShadow = true;
    parent.add(m);
    if (mat.userData.fade) mat.userData.fade.meshes.push(m);
    if (edges) {
      const l = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry), edgeLines);
      l.position.copy(m.position);
      parent.add(l);
    }
    return m;
  }

  /** Pitched roof: ridge runs parallel to the street (x axis). */
  function roofPrism(w, d, h, mat, x, y, z, parent) {
    const s = new THREE.Shape();
    s.moveTo(-d / 2, 0); s.lineTo(d / 2, 0); s.lineTo(0, h); s.closePath();
    const g = new THREE.ExtrudeGeometry(s, { depth: w, bevelEnabled: false });
    g.rotateY(Math.PI / 2);
    g.translate(-w / 2, 0, 0);
    const m = new THREE.Mesh(g, mat);
    m.position.set(x, y, z);
    m.castShadow = true;
    m.receiveShadow = true;
    parent.add(m);
    if (mat.userData.fade) mat.userData.fade.meshes.push(m);
    return m;
  }

  function lift(obj, dy) { lifts.push({ obj, y0: obj.position.y, dy }); }

  /** Any mesh, centred at (x, y, z). */
  function addMesh(geom, mat, x, y, z, parent) {
    const m = new THREE.Mesh(geom, mat);
    m.position.set(x, y, z);
    m.castShadow = true;
    m.receiveShadow = true;
    parent.add(m);
    if (mat.userData.fade) mat.userData.fade.meshes.push(m);
    return m;
  }

  // ---- procedural textures (drawn in code, no image files) -------------
  function canvasTex(size, draw, repeat = [1, 1]) {
    const cv = document.createElement('canvas');
    cv.width = cv.height = size;
    draw(cv.getContext('2d'), size);
    const t = new THREE.CanvasTexture(cv);
    t.colorSpace = THREE.SRGBColorSpace;
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(...repeat);
    t.anisotropy = 8;
    return t;
  }
  const shade = (hex, k) => '#' + new THREE.Color(hex).multiplyScalar(k).getHexString();

  // Clay roof tiles: one canvas = 1 m x 1 m, three courses with overlap shading.
  const roofTex = canvasTex(256, (g, s) => {
    const rows = 3, cols = 4, rh = s / rows, cw = s / cols;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const k = 0.92 + rand() * 0.16;
        const x = (c + (r % 2) * 0.5) * cw;
        const grd = g.createLinearGradient(0, r * rh, 0, (r + 1) * rh);
        grd.addColorStop(0, shade('#b5674a', k * 1.04));
        grd.addColorStop(0.85, shade('#9b5940', k));
        grd.addColorStop(1, shade('#663a2a', k));
        g.fillStyle = grd;
        g.fillRect(x, r * rh, cw, rh);
        g.fillRect(x - s, r * rh, cw, rh);
      }
    }
    g.strokeStyle = 'rgba(70, 30, 18, .35)';
    g.lineWidth = 2;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c <= cols; c++) {
        const x = (c + (r % 2) * 0.5) * cw;
        g.beginPath(); g.moveTo(x, r * rh); g.lineTo(x, (r + 1) * rh); g.stroke();
      }
    }
  });
  roofTex.center.set(0.5, 0.5);
  roofTex.rotation = Math.PI / 2;   // courses run parallel to the ridge

  // Painted render: faint speckle so walls aren't perfectly flat plastic.
  const plasterTex = canvasTex(256, (g, s) => {
    g.fillStyle = '#ffffff';
    g.fillRect(0, 0, s, s);
    for (let i = 0; i < 2600; i++) {
      g.fillStyle = rand() < 0.5 ? 'rgba(0,0,0,.035)' : 'rgba(255,255,255,.5)';
      g.fillRect(rand() * s, rand() * s, 1 + rand() * 2, 1 + rand() * 2);
    }
  }, [3, 2]);

  // Soft dark pad under buildings so they sit on the ground (fake ambient occlusion).
  const contactTex = canvasTex(256, (g, s) => {
    const grd = g.createRadialGradient(s / 2, s / 2, s * 0.18, s / 2, s / 2, s / 2);
    grd.addColorStop(0, 'rgba(0,0,0,0.9)');
    grd.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = grd;
    g.fillRect(0, 0, s, s);
  });
  function contactShadow(w, d, x, y, z, parent, opacity = 0.32) {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, d),
      new THREE.MeshBasicMaterial({ map: contactTex, color: '#2b241a', transparent: true, opacity, depthWrite: false }));
    m.rotation.x = -Math.PI / 2;
    m.position.set(x, y, z);
    m.renderOrder = -1;
    parent.add(m);
  }

  // ---- windows, street props -------------------------------------------
  function windowAt(w, h, x, y, z, facing, parent, glass, frame, mullion = true) {
    box(w + 0.16, h + 0.16, 0.05, frame, x, y - 0.08, z, parent);
    box(w, h, 0.05, glass, x, y, z + 0.025 * facing, parent);
    if (mullion) box(0.05, h, 0.07, frame, x, y, z + 0.03 * facing, parent);
    box(w + 0.3, 0.06, 0.16, frame, x, y - 0.14, z + 0.06 * facing, parent); // sill
  }

  const propMats = {
    // Street props disappear in the Fittings view so they never block the inside.
    trunk: fadeMat('#7b5b3e', 0, { roughness: 1 }),
    leaves: ['#5f8c55', '#6f9b5f', '#4f7c4a', '#7da267'].map(c => fadeMat(c, 0, { roughness: 0.95, flat: true })),
    tyre: fadeMat('#252523', 0, { roughness: 0.9 }),
    carGlass: fadeMat('#33424a', 0, { roughness: 0.08, metalness: 0.6 }),
    cars: ['#ebe8e1', '#3e4b56', '#9d3b2c', '#c9c2b2', '#2f4a3a'].map(c => fadeMat(c, 0, { roughness: 0.3, metalness: 0.35 })),
    rail: fadeMat('#33372f', 0, { roughness: 0.5, metalness: 0.5 }),
    lowWall: fadeMat('#ebe4d5', 0, { map: plasterTex }),
  };

  function tree(x, z, s, parent) {
    addMesh(new THREE.CylinderGeometry(0.09 * s, 0.15 * s, 2.0 * s, 8), propMats.trunk, x, 1.0 * s, z, parent);
    for (let i = 0; i < 4; i++) {
      const r = (0.75 + rand() * 0.5) * s;
      addMesh(new THREE.IcosahedronGeometry(r, 1), propMats.leaves[Math.floor(rand() * 4)],
        x + (rand() - 0.5) * 1.1 * s, (2.3 + rand() * 1.0) * s, z + (rand() - 0.5) * 1.1 * s, parent);
    }
  }

  function car(x, z, colour, parent, rotY = 0) {
    const g = new THREE.Group();
    g.position.set(x, 0, z);
    g.rotation.y = rotY;
    parent.add(g);
    const paint = propMats.cars[colour % propMats.cars.length];
    box(1.78, 0.6, 4.35, paint, 0, 0.3, 0, g);
    box(1.6, 0.5, 2.2, propMats.carGlass, 0, 0.9, -0.2, g);
    box(1.62, 0.07, 2.05, paint, 0, 1.38, -0.2, g);
    for (const [wx, wz] of [[-0.82, 1.4], [0.82, 1.4], [-0.82, -1.4], [0.82, -1.4]]) {
      addMesh(new THREE.CylinderGeometry(0.34, 0.34, 0.24, 18), propMats.tyre, wx, 0.34, wz, g).rotation.z = Math.PI / 2;
    }
  }

  function frontFence(w, z, parent) {
    box(w, 0.45, 0.16, propMats.lowWall, 0, 0, z, parent);
    box(w, 0.05, 0.05, propMats.rail, 0, 1.25, z, parent);
    box(w, 0.04, 0.04, propMats.rail, 0, 0.85, z, parent);
    const n = Math.round(w / 0.45);
    for (let i = 0; i <= n; i++) box(0.035, 0.8, 0.035, propMats.rail, -w / 2 + (i * w) / n, 0.45, z, parent);
  }

  // ---- fittings, coloured by advice ------------------------------------
  const choices = new Map();  // fitting_id -> buyer choice (choice mode)
  const choiceDetail = new Map();  // fitting_id -> the upgrade picked, e.g. "Quartz top"
  const lookMats = new Map();      // fitting_id -> material of the upgrade finish shown, if any
  const pageStyle = getComputedStyle(el);
  const adviceColor = st => pageStyle.getPropertyValue('--advice-' + st).trim() || '#9a948a';  // grey if unset
  const baseColor = fid => (colorBy === 'choice'
    ? CHOICE.keep.color
    : adviceColor(statusOf(info.get(fid).advice)));

  function fitMat(fid) {
    if (!fitMats.has(fid)) {
      const c = baseColor(fid);
      fitMats.set(fid, new THREE.MeshStandardMaterial({
        color: c, roughness: 0.55, emissive: c, emissiveIntensity: 0,
      }));
    }
    return fitMats.get(fid);
  }
  function tag(m, fid) { m.userData.fid = fid; fitMeshes.push(m); return m; }
  function fit(fid, w, h, d, x, y, z, parent) {
    if (!info.has(fid)) return null;
    return tag(box(w, h, d, fitMat(fid), x, y, z, parent), fid);
  }
  function tiles(fid, w, d, x, y, z, parent) {
    if (!info.has(fid)) return null;
    const c = baseColor(fid);
    const cv = document.createElement('canvas');
    cv.width = cv.height = 64;
    const g = cv.getContext('2d');
    g.fillStyle = '#' + new THREE.Color(c).lerp(new THREE.Color('#ffffff'), 0.6).getHexString();
    g.fillRect(0, 0, 64, 64);
    g.strokeStyle = '#' + new THREE.Color(c).lerp(new THREE.Color('#ffffff'), 0.25).getHexString();
    g.lineWidth = 3;
    g.strokeRect(0, 0, 64, 64);
    const tex = new THREE.CanvasTexture(cv);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(w / 0.6, d / 0.6);
    tex.anisotropy = 4;
    const mat = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.4, emissive: c, emissiveIntensity: 0 });
    fitMats.set(fid, mat);
    const m = box(w, 0.02, d, mat, x, y - 0.005, z, parent);
    m.castShadow = false;
    return tag(m, fid);
  }
  /** Hidden until an upgrade asks for its variant (see LOOKS). */
  function variantOf(m, variant) {
    m.userData.variant = variant;
    m.visible = false;
    return m;
  }
  // Light halos and pools: part of a variant, but not something to hover.
  const decor = [];   // {obj, fid, variant, kind: 'halo' | 'pool'}
  let glowTex = null;
  function softGlowTex() {
    glowTex = glowTex || canvasTex(128, (g, s) => {
      const r = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
      r.addColorStop(0, 'rgba(255,255,255,1)');
      r.addColorStop(1, 'rgba(255,255,255,0)');
      g.fillStyle = r;
      g.fillRect(0, 0, s, s);
    });
    return glowTex;
  }
  function pendant(x, z, ceiling, parent, floorY = 0) {
    const fid = 'LGT-DEC';
    if (!info.has(fid)) return;
    const mat = fitMat(fid);
    // A dome shade on a thin cord
    const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.24, 28, 14, 0, Math.PI * 2, 0, Math.PI / 2), mat);
    lamp.material.side = THREE.DoubleSide;
    lamp.position.set(x, ceiling - 0.95, z);
    lamp.castShadow = true;
    parent.add(lamp);
    tag(lamp, fid);
    fit(fid, 0.02, 0.72, 0.02, x, ceiling - 0.72, z, parent);
    // Recessed-downlight upgrades: two downlights instead, each with a glow and a pool of light.
    for (const dz of [-0.7, 0.7]) {
      const disc = tag(addMesh(new THREE.CylinderGeometry(0.14, 0.14, 0.04, 24), mat, x, ceiling - 0.03, z + dz, parent), fid);
      disc.castShadow = false;
      variantOf(disc, 'recessed');
      const halo = new THREE.Sprite(new THREE.SpriteMaterial());
      halo.position.set(x, ceiling - 0.08, z + dz);
      halo.scale.setScalar(1.1);
      parent.add(halo);
      decor.push({ obj: variantOf(halo, 'recessed'), fid, kind: 'halo' });
      const pool = new THREE.Mesh(new THREE.PlaneGeometry(2.4, 2.4), new THREE.MeshBasicMaterial());
      pool.rotation.x = -Math.PI / 2;
      pool.position.set(x, floorY + 0.03, z + dz);
      pool.renderOrder = 1;
      parent.add(pool);
      decor.push({ obj: variantOf(pool, 'recessed'), fid, kind: 'pool' });
    }
  }
  function toilet(x, y, z, parent) {
    fit('SAN-BTH', 0.38, 0.4, 0.55, x, y, z, parent);
    fit('SAN-BTH', 0.38, 0.38, 0.16, x, y + 0.4, z - 0.2, parent);
  }
  function basin(x, y, z, parent) {
    fit('SAN-BTH', 0.14, 0.72, 0.14, x, y, z, parent);
    fit('SAN-BTH', 0.52, 0.12, 0.42, x, y + 0.72, z, parent);
  }
  /** A run of cabinet / wardrobe doors (~60 cm each) with small gaps between. */
  function doorRun(fid, along, len, h, d, cx, y, cz, parent) {
    if (!info.has(fid)) return;
    const n = Math.max(1, Math.round(len / 0.6)), seg = len / n, gap = 0.022;
    for (let i = 0; i < n; i++) {
      const off = -len / 2 + seg * (i + 0.5);
      if (along === 'x') fit(fid, seg - gap, h, d, cx + off, y, cz, parent);
      else fit(fid, d, h, seg - gap, cx, y, cz + off, parent);
    }
  }
  // Clothes, books and a chair for the wardrobe upgrades (their own colours, not the finish).
  const clothMats = ['#5f7d6b', '#c98b6b', '#3f4a5c', '#e2d3b8', '#8b6f9e', '#7f9bb0'].map(c => solidMat(c));
  const darkM = solidMat('#3a3f45', 0.5);
  const chairM = solidMat('#9aa59b');
  /**
   * Built-in wardrobe: a run of doors (the standard item, also the mirrored
   * sliding upgrade), plus hidden open-shelving and study-desk versions for
   * those upgrades. back: which side of its depth the wall is on (-1 / +1).
   */
  function wardrobe(fid, along, len, h, d, cx, y, cz, back, parent) {
    if (!info.has(fid)) return;
    doorRun(fid, along, len, h, d, cx, y, cz, parent);
    // Local frame: x runs along the wardrobe, z goes from the wall (-d/2) into the room.
    const g = new THREE.Group();
    g.position.set(cx, y, cz);
    g.rotation.y = along === 'x' ? (back < 0 ? 0 : Math.PI) : (back < 0 ? Math.PI / 2 : -Math.PI / 2);
    parent.add(g);
    const part = (variant, w, ph, pd, x, py, z, own = null) => {
      const m = tag(box(w, ph, pd, own || fitMat(fid), x, py, z, g), fid);
      if (own) m.userData.ownMat = true;
      return variantOf(m, variant);
    };
    const L = len / 2, bay = len / 3, t = 0.03;

    // Open walk-in system: uprights, a top shelf, two hanging bays and open shelves.
    for (const x of [-L + t / 2, -bay / 2, bay / 2, L - t / 2]) part('open', t, h, d, x, 0, 0);
    part('open', len, t, d, 0, h - 0.32, 0);
    for (const [bx, drop] of [[-bay, 1.15], [bay, 0.6]]) {
      part('open', bay - t, 0.03, 0.03, bx, h - 0.45, 0);   // rail
      for (let i = 0; i < 4; i++) {
        const gh = drop * (0.75 + ((i * 37) % 10) / 40);
        part('open', 0.08, gh, d * 0.75, bx - bay / 2 + 0.12 + i * (bay - 0.2) / 3.5, h - 0.47 - gh, 0, clothMats[(i + (bx > 0 ? 3 : 0)) % clothMats.length]);
      }
    }
    part('open', bay - t, 0.78, d * 0.95, bay, 0, 0);       // drawers under the short hanging
    for (const sy of [0.35, 0.75, 1.15, 1.55]) part('open', bay - t, t, d, 0, sy, 0);
    part('open', bay * 0.55, 0.14, d * 0.6, 0, 0.75 + t, 0, clothMats[2]);   // folded clothes
    part('open', bay * 0.55, 0.12, d * 0.6, 0, 1.15 + t, 0, clothMats[3]);

    // Study version: a half-width wardrobe, a desk with a shelf above, a laptop and a chair.
    part('study', L / 2 - 0.01, h, d, -L * 0.75, 0, 0);
    part('study', L / 2 - 0.01, h, d, -L * 0.25, 0, 0);
    part('study', L, 0.04, d, L / 2, 0.72, 0);
    part('study', 0.04, 0.72, d, L - 0.02, 0, 0);
    part('study', L - 0.06, t, d * 0.5, L / 2, 1.45, -d / 4);
    part('study', 0.34, 0.02, 0.24, L / 2, 0.76, 0.02, darkM);
    part('study', 0.34, 0.22, 0.015, L / 2, 0.78, -0.1, darkM);
    part('study', 0.42, 0.45, 0.42, L / 2, 0, d / 2 + 0.3, chairM);
    part('study', 0.42, 0.45, 0.05, L / 2, 0.45, d / 2 + 0.5, chairM);
  }
  function kitchen(x0, x1, zBack, sideX, sideLen, y, parent) {
    // Lower run along the back wall, a return along the side wall, and wall units.
    const len = x1 - x0, cx = (x0 + x1) / 2;
    const sideZ = zBack + 0.6 + sideLen / 2;
    doorRun('KIT-CAB', 'x', len, 0.82, 0.6, cx, y + 0.03, zBack + 0.3, parent);
    doorRun('KIT-CAB', 'z', sideLen, 0.82, 0.6, sideX, y + 0.03, sideZ, parent);
    doorRun('KIT-CAB', 'x', len, 0.7, 0.35, cx, y + 1.5, zBack + 0.175, parent);
    fit('KIT-TOP', len + 0.04, 0.04, 0.64, cx, y + 0.85, zBack + 0.32, parent);
    fit('KIT-TOP', 0.64, 0.04, sideLen, sideX, y + 0.85, sideZ, parent);
  }

  // Context furniture (neutral, not a fitting).
  const woodM = solidMat(COL.wood, 0.75);
  const fabricM = solidMat(COL.fabric);
  const bedM = solidMat(COL.bed);
  function sofa(x, y, z, parent) {
    box(2.2, 0.42, 0.9, fabricM, x, y, z, parent);
    box(2.2, 0.42, 0.2, fabricM, x, y + 0.42, z + 0.35, parent);
  }
  function table(x, y, z, parent) {
    box(1.5, 0.05, 0.85, woodM, x, y + 0.7, z, parent);
    for (const [dx, dz] of [[-0.68, -0.36], [0.68, -0.36], [-0.68, 0.36], [0.68, 0.36]]) {
      box(0.06, 0.7, 0.06, woodM, x + dx, y, z + dz, parent);
    }
  }
  function bed(w, x, y, z, parent) {
    box(w, 0.45, 2.0, bedM, x, y, z, parent);
    box(w, 0.9, 0.08, woodM, x, y, z - 1.04, parent);
  }

  // ---- ground -----------------------------------------------------------
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(600, 600), solidMat(COL.ground, 1));
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  scene.add(ground);

  const root = new THREE.Group();
  scene.add(root);

  // ---- the two unit types ----------------------------------------------
  const poses = unit === 'C3R' ? buildCondo(root) : buildTerrace(root);

  function buildTerrace(root) {
    const W = 6.1, D = 15.2, H = 3.3, T = 0.15, S = 0.2;
    const PORCH = 6.1; // 20' x 70' lot = 6.1 m x 21.3 m

    const ZF = D / 2 + PORCH;   // front boundary of the lot

    // Street: footpath, grass verge with trees, two-lane road with centre dashes.
    box(160, 0.06, 1.8, solidMat(COL.path, 1), 0, 0, ZF + 0.9, root);
    box(160, 0.04, 1.6, solidMat(COL.grass, 1), 0, 0, ZF + 2.6, root);
    const roadZ = ZF + 3.4 + 3.6;
    box(160, 0.02, 7.2, solidMat(COL.road, 0.95), 0, 0, roadZ, root);
    const dashM = solidMat('#efece4', 0.8);
    for (let x = -66; x <= 66; x += 4.5) box(2.2, 0.025, 0.14, dashM, x, 0, roadZ, root);
    for (const x of [-4.5, -2.5, 1.5, 3.5]) tree(x * W, ZF + 2.6, 1.05 + rand() * 0.25, root);
    for (const x of [-3.2, -1.4, 1.6, 2.8]) tree(x * W, -D / 2 - 2.6, 1.2 + rand() * 0.3, root); // back lane
    contactShadow(W * 7 + 1.6, D + 2.2, 0, 0.062, 0, root, 0.4);

    const pavingM = solidMat(COL.paving, 1);
    const frameM = fadeMat(COL.frame, 0.08);
    const ghostGlassM = fadeMat('#8fa2aa', 0.04, { roughness: 0.1, metalness: 0.5 });
    const ghostFrameM = fadeMat(COL.frame, 0.03);
    const ghostRoofM = fadeMat(COL.ghostRoof, 0.03, { map: roofTex, roughness: 0.85 });

    // Neighbours either side, same design but their own paint: this is a terrace row.
    [-3, -2, -1, 1, 2, 3].forEach((i, n) => {
      const g = new THREE.Group();
      g.position.x = i * W;
      const paint = fadeMat(NEIGHBOUR_PAINT[n], 0.05, { map: plasterTex });
      box(W - 0.04, 2 * H, D, paint, 0, 0, 0, g);
      roofPrism(W - 0.04, D + 0.8, 2.4, ghostRoofM, 0, 2 * H, 0, g);
      for (const zz of [D / 2 + 0.4, -D / 2 - 0.4]) box(W - 0.04, 0.22, 0.1, ghostFrameM, 0, 2 * H - 0.12, zz, g);
      windowAt(1.0, 2.15, -1.9, S, D / 2 + 0.01, 1, g, ghostGlassM, ghostFrameM, false);
      windowAt(2.8, 1.6, 0.9, 0.95, D / 2 + 0.01, 1, g, ghostGlassM, ghostFrameM);
      windowAt(1.8, 1.4, -1.4, H + 1.0, D / 2 + 0.01, 1, g, ghostGlassM, ghostFrameM);
      windowAt(1.8, 1.4, 1.4, H + 1.0, D / 2 + 0.01, 1, g, ghostGlassM, ghostFrameM);
      box(W - 0.04, 0.15, 1.6, paint, 0, H - 0.15, D / 2 + 0.8, g); // porch canopy
      box(W - 0.04, 0.05, PORCH, pavingM, 0, 0, D / 2 + PORCH / 2, g);
      frontFence(W - 0.04, ZF - 0.08, g);
      if (n % 2 === 0) car(0.9, D / 2 + 3.2, n / 2 + 1, g);
      root.add(g);
    });

    // The selected home.
    const wallM = fadeMat(COL.wall, 0.08, { map: plasterTex });
    const partyM = fadeMat(COL.party, 0.05, { map: plasterTex });
    const partM = fadeMat(COL.wall, 0.16);
    const glassM = fadeMat(COL.glass, 0.06, { roughness: 0.06, metalness: 0.55 });
    const slabM = solidMat(COL.slab);
    const roofM = fadeMat(COL.roof, 0, { map: roofTex, roughness: 0.8 });
    const ceilM = fadeMat(COL.slab, 0);
    const fasciaM = fadeMat(COL.frame, 0);

    const house = new THREE.Group();
    root.add(house);
    box(W, 0.05, PORCH, pavingM, 0, 0, D / 2 + PORCH / 2, house);
    frontFence(W, ZF - 0.08, house);
    car(0.9, D / 2 + 3.2, 0, house);

    function shell(g) {
      box(W, S, D, slabM, 0, 0, 0, g, { edges: true });
      box(T, H, D, partyM, -W / 2 + T / 2, 0, 0, g, { edges: true });
      box(T, H, D, partyM, W / 2 - T / 2, 0, 0, g, { edges: true });
      box(W - 2 * T, H, T, wallM, 0, 0, -D / 2 + T / 2, g, { edges: true });
      box(W - 2 * T, H, T, wallM, 0, 0, D / 2 - T / 2, g, { edges: true });
    }

    // Ground floor: living at the front, dining, kitchen at the back.
    const gf = new THREE.Group();
    house.add(gf);
    shell(gf);
    windowAt(1.0, 2.15, -1.9, S, D / 2 + 0.01, 1, gf, glassM, frameM, false);
    windowAt(2.8, 1.6, 0.9, 0.95, D / 2 + 0.01, 1, gf, glassM, frameM);
    windowAt(0.7, 0.6, -2.0, 1.7, -D / 2 - 0.01, -1, gf, glassM, frameM, false);
    box(W, 0.15, 1.6, wallM, 0, H - 0.15, D / 2 + 0.8, gf); // porch canopy
    tiles('TIL-FLR', W - 2 * T, D - 2 * T, 0, S, 0, gf);
    // Stairs along the left party wall
    for (let i = 0; i < 12; i++) {
      box(1.0, 0.275 * (i + 1), 0.3, woodM, -W / 2 + T + 0.5, S, 1.6 - i * 0.3 - 0.15, gf);
    }
    const zb = -D / 2 + T;
    kitchen(-0.9, W / 2 - T, zb, W / 2 - T - 0.3, 2.4, S, gf);
    box(T, H - S, 2.3, partM, -1.0, S, zb + 1.15, gf, { edges: true }); // bathroom walls
    box(1.95 - T, H - S, T, partM, -1.95, S, zb + 2.3, gf, { edges: true });
    toilet(-2.45, S, zb + 0.35, gf);
    basin(-1.5, S, zb + 0.25, gf);
    sofa(0.9, S, 5.6, gf);
    table(0.8, S, -2.0, gf);
    pendant(0.9, 4.0, H, gf, S);
    pendant(0.8, -2.0, H, gf, S);

    // First floor: master bedroom front, bedroom 2, back bedroom + bathroom.
    const FF_LIFT = 3.8;
    const ff = new THREE.Group();
    ff.position.y = H;
    house.add(ff);
    lift(ff, FF_LIFT);
    shell(ff);
    windowAt(1.8, 1.4, -1.4, 1.0, D / 2 + 0.01, 1, ff, glassM, frameM);
    windowAt(1.8, 1.4, 1.4, 1.0, D / 2 + 0.01, 1, ff, glassM, frameM);
    windowAt(1.4, 1.2, 1.2, 1.1, -D / 2 - 0.01, -1, ff, glassM, frameM);
    const hp = H - S;
    box(3.85, hp, T, partM, -1.025, S, 2.3, ff, { edges: true });
    box(1.05, hp, T, partM, 2.425, S, 2.3, ff, { edges: true });
    box(2.45, hp, T, partM, -1.725, S, -2.6, ff, { edges: true });
    box(2.45, hp, T, partM, 1.725, S, -2.6, ff, { edges: true });
    box(T, hp, 2.3, partM, -0.5, S, zb + 1.15, ff, { edges: true });
    box(2.45, hp, T, partM, -1.725, S, zb + 2.3, ff, { edges: true });
    bed(1.8, 1.0, S, 3.5, ff);
    wardrobe('WRD-MST', 'z', 2.4, 2.3, 0.6, -W / 2 + T + 0.3, S, 5.4, -1, ff);
    bed(1.0, -2.3, S, -0.4, ff);
    wardrobe('WRD-BR2', 'z', 1.8, 2.3, 0.6, W / 2 - T - 0.3, S, -1.4, 1, ff);
    bed(1.2, 1.8, S, -4.4, ff);
    toilet(-2.45, S, zb + 0.35, ff);
    basin(-1.3, S, zb + 0.25, ff);
    pendant(1.0, 4.7, H, ff, S);
    pendant(0.4, -0.2, H, ff, S);

    // Roof and the top-floor ceiling lift off together.
    const roof = new THREE.Group();
    roof.position.y = 2 * H;
    house.add(roof);
    lift(roof, 8);
    box(W, S, D, ceilM, 0, 0, 0, roof);
    roofPrism(W, D + 0.8, 2.4, roofM, 0, S, 0, roof);
    for (const zz of [D / 2 + 0.4, -D / 2 - 0.4]) box(W, 0.22, 0.1, fasciaM, 0, S - 0.12, zz, roof); // fascia boards

    // "This home" pin floating over the roof (fades away in the Fittings view).
    const pinM = fadeMat(COL.accent, 0, { roughness: 0.35 });
    const pinDotM = fadeMat('#fffdf8', 0, { roughness: 0.4 });
    const pin = new THREE.Group();
    pin.position.set(0, 2 * H + 4.6, 0);
    house.add(pin);
    addMesh(new THREE.SphereGeometry(0.75, 32, 20), pinM, 0, 1.2, 0, pin);
    addMesh(new THREE.ConeGeometry(0.62, 1.5, 32), pinM, 0, 0.3, 0, pin).rotation.x = Math.PI;
    addMesh(new THREE.SphereGeometry(0.3, 24, 16), pinDotM, 0, 1.25, 0.55, pin);
    bobbers.push({ obj: pin, y0: pin.position.y });

    return {
      shadow: 30,
      exterior: { pos: [22, 13, 33], target: [0, 3.6, 3] },
      fittings: { pos: [19, 24, 25], target: [0, 5.4, -0.5] },
      distance: [10, 75],
      // Floor picker: where the camera looks for each floor (after the lift).
      floors: [
        { id: 'gf', label: 'Ground', group: gf, target: [0, S + 1, 0.5] },
        { id: 'ff', label: 'First', group: ff, target: [0, H + FF_LIFT + S + 1, 0.5] },
      ],
      hideWithFloor: [roof],   // hidden whenever a single floor is picked
    };
  }

  function buildCondo(root) {
    const UW = 9, UD = 10, FH = 3.2, FLOORS = 10, SEL = 5, T = 0.15;

    const aboveBand = fadeMat(COL.wall, 0.03);
    const aboveGlass = fadeMat(COL.glass, 0.02, { roughness: 0.1, metalness: 0.3 });
    const band = fadeMat(COL.wall, 0.22, { map: plasterTex });
    const glass = fadeMat(COL.glass, 0.07, { roughness: 0.1, metalness: 0.3 });
    const selGlass = fadeMat(COL.accent, 0, { roughness: 0.15, metalness: 0.25 });
    const slabM = solidMat(COL.slab);

    // Podium: paving, lawns, trees, a drop-off road and a few parked cars.
    box(3 * UW + 16, 0.05, UD + 16, solidMat(COL.paving, 1), 0, 0, 0, root);
    const lawnM = solidMat(COL.grass, 1);
    for (const x of [-18, 18]) box(6, 0.09, UD + 10, lawnM, x, 0, 0, root);
    box(3 * UW - 2, 0.09, 3.2, lawnM, 0, 0, -UD / 2 - 3.6, root);
    for (const [x, z] of [[-17.5, 5.5], [-18.2, -3], [-17.5, -9], [17.5, 6], [18.2, -3.5], [17.5, -9.5], [-8, -9.6], [8, -9.6]]) {
      tree(x, z, 1.25 + rand() * 0.4, root);
    }
    const roadZ = UD / 2 + 8 + 3.6;
    box(200, 0.02, 7.2, solidMat(COL.road, 0.95), 0, 0, roadZ, root);
    const dashM = solidMat('#efece4', 0.8);
    for (let x = -80; x <= 80; x += 4.5) box(2.2, 0.025, 0.14, dashM, x, 0, roadZ, root);
    [[-12, 0], [-6.6, 2], [3.2, 4], [8.6, 1]].forEach(([x, c]) => car(x, UD / 2 + 5.4, c, root, Math.PI / 2));
    contactShadow(3 * UW + 3, UD + 3, 0, 0.06, 0, root, 0.45);

    const below = new THREE.Group();
    const above = new THREE.Group();
    root.add(below, above);
    lift(above, 15);

    for (let f = 0; f < FLOORS; f++) {
      const y = f * FH;
      const isAbove = f > SEL;
      const g = isAbove ? above : below;
      const slab = f === SEL ? slabM : (isAbove ? aboveBand : band);
      box(3 * UW + 0.6, 0.3, UD + 0.6, slab, 0, y, 0, g, { edges: f === SEL });
      for (const u of [-1, 0, 1]) {
        if (f === SEL && u === 0) continue;
        box(UW - 0.3, FH - 0.3, UD - 0.3, isAbove ? aboveGlass : glass, u * UW, y + 0.3, 0, g);
        box(0.3, FH - 0.3, 0.3, isAbove ? aboveBand : band, u * UW - UW / 2, y + 0.3, UD / 2, g);
      }
    }
    box(3 * UW + 0.6, 1.0, UD + 0.6, aboveBand, 0, FLOORS * FH, 0, above);

    // The selected unit: terracotta glass outside, a full interior inside.
    const y0 = SEL * FH + 0.3, H = FH - 0.3;
    box(UW - 0.3, H, UD - 0.3, selGlass, 0, y0, 0, below);

    const u = new THREE.Group();
    u.position.y = y0;
    below.add(u);
    const wallM = fadeMat(COL.wall, 0.1);
    const partM = fadeMat(COL.wall, 0.16);
    const xL = -UW / 2 + T, xR = UW / 2 - T, zB = -UD / 2 + T, zF = UD / 2 - T;
    box(UW - 0.3, H, T, wallM, 0, 0, zB - T / 2, u, { edges: true });
    box(T, H, UD - 0.3, wallM, xL - T / 2, 0, 0, u, { edges: true });
    box(T, H, UD - 0.3, wallM, xR + T / 2, 0, 0, u, { edges: true });

    // Rooms: master (front-left), bathroom, bedroom 2 (back-left),
    // kitchen (back-right), living + dining (front-right).
    for (const [z0, z1] of [[zB, -2.6], [-1.8, 1.4], [2.2, zF]]) {
      box(T, H, z1 - z0, partM, -1.5, 0, (z0 + z1) / 2, u, { edges: true });
    }
    box(-1.5 - xL, H, T, partM, (xL - 1.5) / 2, 0, 0, u, { edges: true });
    box(-1.5 - xL, H, T, partM, (xL - 1.5) / 2, 0, -1.6, u, { edges: true });

    tiles('TIL-FLR', xR + 1.5, zF + 1.0, (xR - 1.5) / 2, 0, (zF - 1.0) / 2, u);
    kitchen(1.5, xR, zB, xR - 0.3, 2.2, 0, u);
    wardrobe('WRD-MST', 'x', 2.4, 2.3, 0.6, -2.95, 0, T / 2 + 0.3, -1, u);
    bed(1.8, -2.95, 0, 2.8, u);
    bed(1.0, -3.5, 0, -3.6, u);
    toilet(-3.9, 0, -1.0, u);
    basin(-2.2, 0, -1.3, u);
    sofa(2.4, 0, 3.6, u);
    table(0.4, 0, -0.4, u);
    pendant(0.4, -0.4, H, u);
    pendant(2.4, 2.4, H, u);

    // Balcony
    box(4.5, 0.15, 1.5, slabM, 1.8, y0 - 0.15, UD / 2 + 0.75, below);
    box(4.5, 1.0, 0.04, fadeMat('#9fb3bf', 0.2, { roughness: 0.2 }), 1.8, y0, UD / 2 + 1.48, below);

    const yc = SEL * FH;
    return {   // the unit is on one level, so no floor picker
      shadow: 40,
      exterior: { pos: [44, 25, 64], target: [0, 15, 0] },
      fittings: { pos: [12, yc + 13, 15.5], target: [0, yc + 0.5, 0.3] },
      distance: [10, 120],
    };
  }

  // ---- shadows sized to the scene ---------------------------------------
  const sc = sun.shadow.camera;
  sc.left = sc.bottom = -poses.shadow;
  sc.right = sc.top = poses.shadow;
  sc.near = 1;
  sc.far = 160;
  sun.position.set(-26, 46, 30);
  sun.target.position.set(0, 0, 0);
  controls.minDistance = poses.distance[0];
  controls.maxDistance = poses.distance[1];

  // ---- views and transitions -------------------------------------------
  let t = 0;          // 0 = exterior, 1 = fittings
  let mode = 'exterior';
  let floor = 'all';  // which floor the Fittings view shows
  let tween = null;
  const CLOSE_MIN = 6;       // how near the camera may get in the Fittings view
  const LOOK_DOWN = 0.75;    // close-ups look down at ~43 degrees

  function apply(v) {
    const e = v < 0.5 ? 4 * v * v * v : 1 - Math.pow(-2 * v + 2, 3) / 2;
    for (const f of fades) {
      const o = f.solid + (f.xray - f.solid) * e;
      f.mat.opacity = o;
      if (!f.line) {
        const tr = o < 0.995;
        if (tr !== f.mat.transparent) { f.mat.transparent = tr; f.mat.needsUpdate = true; }
        f.mat.depthWrite = o > 0.5;
        for (const m of f.meshes) m.castShadow = o > 0.5;
      }
      f.mat.visible = o > 0.01;
    }
    for (const l of lifts) l.obj.position.y = l.y0 + l.dy * e;
  }

  function pose(name) {
    const p = poses[name];
    return { pos: new THREE.Vector3(...p.pos), target: new THREE.Vector3(...p.target) };
  }

  /** Camera `dist` from target, on the current compass heading, looking down. */
  function closeUp(target, dist) {
    // Heading of where the camera is going (or is), so a new flight doesn't swing round.
    const from = tween ? tween.p1 : camera.position, at = tween ? tween.q1 : controls.target;
    const dir = from.clone().sub(at).setY(0);
    if (dir.lengthSq() < 1e-6) dir.set(1, 0, 1);
    dir.normalize().multiplyScalar(Math.cos(LOOK_DOWN)).setY(Math.sin(LOOK_DOWN));
    return { pos: target.clone().addScaledVector(dir, dist), target };
  }

  /** Fly the camera to a pose; walls fade in or out to match the current mode. */
  function flyTo(to, { animate = true, dur = 1100 } = {}) {
    const t1 = mode === 'fittings' ? 1 : 0;
    if (!animate || reducedMotion) {
      tween = null;
      t = t1;
      apply(t);
      camera.position.copy(to.pos);
      controls.target.copy(to.target);
      settle();
      return;
    }
    tween = {
      start: performance.now(), dur, t0: t, t1,
      p0: camera.position.clone(), q0: controls.target.clone(),
      p1: to.pos, q1: to.target,
    };
    controls.enabled = false;
  }
  /** After a flight: hand the camera back to the user. */
  function settle() {
    // Only zoom right in when the walls are see-through.
    controls.minDistance = mode === 'fittings' ? CLOSE_MIN : poses.distance[0];
    controls.enabled = true;
    controls.update();
  }

  function setMode(next, { animate = true } = {}) {
    if (next !== 'exterior' && next !== 'fittings') return;
    mode = next;
    try { sessionStorage.setItem(storeKey, next); } catch (_) { /* storage blocked */ }
    el.dataset.view = next;
    el.querySelectorAll('[data-view-btn]').forEach(b => {
      b.setAttribute('aria-pressed', String(b.dataset.viewBtn === next));
    });
    controls.autoRotate = next === 'exterior' && !reducedMotion;
    if (next === 'exterior') { clearHighlight(true); showFloor('all'); }
    flyTo(pose(next), { animate });
  }

  // ---- hover + highlight ----------------------------------------------
  const tip = document.createElement('div');
  tip.className = 'house-tip';
  tip.hidden = true;
  el.appendChild(tip);

  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  let hovered = null, pinned = null;

  function setGlow(fid, on) {
    for (const m of [fitMats.get(fid), lookMats.get(fid)]) {
      if (m) m.emissiveIntensity = (m.userData.glow0 || 0) + (on ? 0.55 : 0);   // lights keep their own glow
    }
  }
  function showTip(fid, x, y) {
    const f = info.get(fid);
    if (!f) return;
    const st = statusOf(f.advice);
    const last = colorBy === 'choice'
      ? (f.eligibility === 'fixed'
        ? '<span class="tip-advice">Always included</span>'
        : `<span class="tip-advice choice-${choices.get(fid) || 'keep'}"><i aria-hidden="true"></i>`
          + `Your choice: ${CHOICE[choices.get(fid) || 'keep'].label}`
          + `${choiceDetail.get(fid) ? ' to ' + esc(choiceDetail.get(fid)) : ''}</span>`)
      : `<span class="tip-advice ${st}"><i aria-hidden="true">${STATUS[st].icon}</i>${esc(f.advice)}</span>`;
    tip.innerHTML = `<strong>${esc(f.name)}</strong>`
      + `<span>${Math.round(f.rate * 100)}% of owners removed it (${f.removed} of ${f.owners})</span>`
      + last;
    tip.hidden = false;
    const r = el.getBoundingClientRect();
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.min(Math.max(8, x + 14), r.width - w - 8) + 'px';
    tip.style.top = Math.min(Math.max(8, y - h - 12), r.height - h - 8) + 'px';
  }
  function highlight(fid) {
    if (hovered && hovered !== fid && hovered !== pinned) setGlow(hovered, false);
    hovered = fid;
    if (fid) setGlow(fid, true);
  }
  function clearHighlight(includePinned = false) {
    if (hovered && hovered !== pinned) setGlow(hovered, false);
    hovered = null;
    if (includePinned && pinned) { setGlow(pinned, false); pinned = null; }
    if (!pinned) tip.hidden = true;
  }
  function centreOnScreen(fid) {
    const b = new THREE.Box3();
    fitMeshes.filter(m => m.userData.fid === fid && shown(m)).forEach(m => b.expandByObject(m));
    if (b.isEmpty()) return null;
    const c = b.getCenter(new THREE.Vector3()).project(camera);
    const r = el.getBoundingClientRect();
    return { x: (c.x + 1) / 2 * r.width, y: (1 - c.y) / 2 * r.height };
  }

  // ---- floors: one at a time in the Fittings view ------------------------
  const floors = poses.floors || [];
  const floorBtns = [];
  const floorBox = el.querySelector('[data-floor-picker]');
  if (floorBox && floors.length > 1) {
    const seg = floorBox.querySelector('.seg') || floorBox;
    for (const f of [{ id: 'all', label: 'All' }, ...floors]) {
      const b = document.createElement('button');
      b.type = 'button';
      b.textContent = f.label;
      b.dataset.floor = f.id;
      b.setAttribute('aria-pressed', String(f.id === 'all'));
      b.addEventListener('click', () => setFloor(f.id));
      seg.append(b);
      floorBtns.push(b);
    }
    floorBox.hidden = false;
  }

  /** The id of the floor an object is on, or null. */
  function floorOf(obj) {
    for (let o = obj; o; o = o.parent) {
      const f = floors.find(x => x.group === o);
      if (f) return f.id;
    }
    return null;
  }
  /** False if the object or anything it sits in is hidden (e.g. another floor). */
  function shown(obj) {
    for (let o = obj; o; o = o.parent) if (!o.visible) return false;
    return true;
  }
  /** Show one floor (or 'all') without moving the camera. */
  function showFloor(id) {
    floor = floors.some(f => f.id === id) ? id : 'all';
    for (const f of floors) f.group.visible = floor === 'all' || f.id === floor;
    for (const g of poses.hideWithFloor || []) g.visible = floor === 'all';
    floorBtns.forEach(b => b.setAttribute('aria-pressed', String(b.dataset.floor === floor)));
    if (pinned && !fitMeshes.some(m => m.userData.fid === pinned && shown(m))) clearHighlight(true);
  }
  /** Pick a floor (or 'all') and zoom in on it. */
  function setFloor(id) {
    if (floors.length < 2) return;
    if (mode !== 'fittings') setMode('fittings');
    showFloor(id);
    const f = floors.find(x => x.id === floor);
    flyTo(f ? closeUp(new THREE.Vector3(...f.target), 24) : pose('fittings'), { dur: 900 });
  }

  /** Bounding box of meshes once the Fittings view has lifted the floors apart. */
  function liftedBox(meshes) {
    scene.updateMatrixWorld();
    const box = new THREE.Box3(), b = new THREE.Box3(), shift = new THREE.Vector3();
    for (const m of meshes) {
      shift.set(0, 0, 0);
      for (const l of lifts) {
        for (let o = m; o; o = o.parent) {
          if (o === l.obj) { shift.y += l.y0 + l.dy - l.obj.position.y; break; }
        }
      }
      box.union(b.setFromObject(m).translate(shift));
    }
    return box;
  }

  /** Pin a fitting, show its floor and zoom in on it. */
  function focus(fid) {
    if (!info.has(fid)) return;
    if (pinned && pinned !== fid) setGlow(pinned, false);
    pinned = fid;
    setGlow(fid, true);
    if (mode !== 'fittings') setMode('fittings');
    let meshes = fitMeshes.filter(m => m.userData.fid === fid && m.visible);   // not hidden variants
    if (floors.length > 1) {
      // Stay on this floor if the fitting is here, else go to the first floor that has it.
      const on = meshes.map(floorOf);
      showFloor(on.includes(floor) ? floor : on.find(Boolean));
      if (floor !== 'all') meshes = meshes.filter(m => floorOf(m) === floor);
    }
    const box = liftedBox(meshes);
    if (box.isEmpty()) return;
    const size = box.getSize(new THREE.Vector3()).length();
    flyTo(closeUp(box.getCenter(new THREE.Vector3()), THREE.MathUtils.clamp(size * 1.3 + 5, 8, 24)),
          { dur: 900 });
  }

  const ray = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  function pick(ev) {
    const r = renderer.domElement.getBoundingClientRect();
    ndc.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hit = ray.intersectObjects(fitMeshes, false).find(h => shown(h.object));
    return { fid: hit ? hit.object.userData.fid : null, x: ev.clientX - r.left, y: ev.clientY - r.top };
  }
  renderer.domElement.addEventListener('pointermove', ev => {
    if (mode !== 'fittings' || tween || ev.pointerType === 'touch') return;
    const { fid, x, y } = pick(ev);
    renderer.domElement.style.cursor = fid ? 'pointer' : '';
    if (fid) { highlight(fid); showTip(fid, x, y); } else clearHighlight();
  });
  renderer.domElement.addEventListener('pointerleave', () => clearHighlight());
  // Click / tap pins a fitting's details; clicking empty space unpins.
  let downAt = null;
  renderer.domElement.addEventListener('pointerdown', ev => { downAt = [ev.clientX, ev.clientY]; });
  renderer.domElement.addEventListener('pointerup', ev => {
    if (mode !== 'fittings' || tween || !downAt) return;
    const moved = Math.hypot(ev.clientX - downAt[0], ev.clientY - downAt[1]) > 6; // a drag, not a tap
    downAt = null;
    if (moved) return;
    const { fid } = pick(ev);
    if (fid) { hovered = null; focus(fid); if (onPick) onPick(fid); } else clearHighlight(true);
  });
  el.querySelectorAll('[data-view-btn]').forEach(b => {
    b.addEventListener('click', () => setMode(b.dataset.viewBtn));
  });

  // ---- sizing + render loop ------------------------------------------
  function resize() {
    const w = canvasHost.clientWidth, h = canvasHost.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    // Pull back a little on narrow screens so the whole home fits.
    camera.fov = w < 640 ? 44 : 32;
    // Keep the home clear of the info card: shift the picture right on wide
    // screens (card bottom-left), up on phones (card across the bottom).
    if (w < 640) camera.setViewOffset(w, h, 0, h * 0.13, w, h);
    else camera.setViewOffset(w, h, -w * 0.13, 0, w, h);
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(canvasHost);
  resize();

  let onScreen = true;
  new IntersectionObserver(([e]) => { onScreen = e.isIntersecting; }).observe(el);

  let stored = initialMode;
  if (!stored) {
    try { stored = sessionStorage.getItem(storeKey); } catch (_) { /* storage blocked */ }
  }
  setMode(stored === 'fittings' ? 'fittings' : 'exterior', { animate: false });

  // ---- upgrade finishes (buyer view) ----------------------------------
  const finishes = new Map();   // "fid|upgrade_id" -> {mat, halo, pool}
  const cycling = [];           // colours that drift warm -> cool (smart lights)
  /** The materials for one fitting in one upgrade finish (made once, then reused). */
  function finishFor(fid, id, look) {
    const key = fid + '|' + id;
    if (finishes.has(key)) return finishes.get(key);
    const mat = new THREE.MeshStandardMaterial({
      color: look.color || '#ffffff', roughness: look.roughness ?? 0.6, metalness: look.metalness ?? 0,
      emissive: look.glow || look.color || '#ffffff', emissiveIntensity: look.glow ? 1.2 : 0,
    });
    mat.userData.glow0 = mat.emissiveIntensity;
    if (look.paint) {
      let repeat = look.repeat || [1, 1];
      if (look.tile) {   // floors: one canvas covers look.tile metres
        const p = fitMeshes.find(m => m.userData.fid === fid).geometry.parameters;
        repeat = [p.width / look.tile[0], p.depth / look.tile[1]];
      }
      mat.map = canvasTex(256, look.paint, repeat);
    }
    const out = { mat };
    if (look.glow) {
      const glow = { map: softGlowTex(), color: look.glow, transparent: true, depthWrite: false };
      out.halo = new THREE.SpriteMaterial({ ...glow, blending: THREE.AdditiveBlending });
      out.pool = new THREE.MeshBasicMaterial({ ...glow, opacity: 0.55 });
    }
    if (look.cycle) {
      const [from, to] = look.cycle.map(c => new THREE.Color(c));
      cycling.push({ c: mat.emissive, from, to }, { c: out.halo.color, from, to }, { c: out.pool.color, from, to });
    }
    finishes.set(key, out);
    return out;
  }
  const outlineMat = new THREE.LineBasicMaterial({ color: CHOICE.upgrade.color });
  /** Terracotta edges on an upgraded fitting, so a realistic finish still reads as "your upgrade". */
  function outline(m, on) {
    if (on && !m.userData.outline) {
      m.userData.outline = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry, 30), outlineMat);
      m.add(m.userData.outline);
    }
    if (m.userData.outline) m.userData.outline.visible = on;
  }

  /**
   * Buyer view: show what will be installed for this fitting. For an upgrade,
   * detail is the option's name and upgradeId picks its finish from LOOKS.
   */
  function setChoice(fid, choice, detail = '', upgradeId = '') {
    const m = fitMats.get(fid);
    if (!m || !CHOICE[choice]) return;
    setGlow(fid, false);   // so the finish being swapped out doesn't keep a hover glow
    choices.set(fid, choice);
    choiceDetail.set(fid, choice === 'upgrade' ? detail : '');
    const look = choice === 'upgrade' ? LOOKS[upgradeId] : null;
    const finish = look ? finishFor(fid, upgradeId, look) : null;
    lookMats.set(fid, finish && finish.mat);

    const c = CHOICE[choice].color;
    // Tiles keep their texture: tinted terracotta for an upgrade with no LOOKS finish.
    if (m.map) m.color.set(choice === 'upgrade' ? c : '#ffffff');
    else m.color.set(c);
    m.emissive.set(c);
    const ghost = choice === 'opt_out';
    m.transparent = ghost;
    m.opacity = ghost ? 0.2 : 1;
    m.depthWrite = !ghost;
    m.needsUpdate = true;

    const variant = (look && look.variant) || 'standard';
    for (const x of fitMeshes) {
      if (x.userData.fid !== fid) continue;
      x.visible = (x.userData.variant || 'standard') === variant;
      if (x.userData.ownMat) continue;
      x.material = finish ? finish.mat : m;
      x.castShadow = !ghost && !m.map && !look?.glow;
      outline(x, choice === 'upgrade');
    }
    for (const d of decor) {
      if (d.fid !== fid) continue;
      d.obj.visible = d.obj.userData.variant === variant;
      if (finish && finish[d.kind]) d.obj.material = finish[d.kind];
    }
    if (pinned === fid || hovered === fid) setGlow(fid, true);
  }

  renderer.setAnimationLoop(now => {
    if (!onScreen) return;
    if (tween) {
      const p = Math.min(1, (now - tween.start) / tween.dur);
      const e = p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
      t = tween.t0 + (tween.t1 - tween.t0) * p;
      apply(t);
      camera.position.lerpVectors(tween.p0, tween.p1, e);
      controls.target.lerpVectors(tween.q0, tween.q1, e);
      // Not controls.update(): it would clamp the zoom mid-flight.
      camera.lookAt(controls.target);
      if (p >= 1) { tween = null; settle(); }
    } else {
      controls.update();
    }
    if (!reducedMotion) for (const b of bobbers) b.obj.position.y = b.y0 + Math.sin(now / 600) * 0.22;
    if (cycling.length && !reducedMotion) {   // smart lights drift between warm and cool white
      const k = (Math.sin(now / 1500) + 1) / 2;
      for (const x of cycling) x.c.lerpColors(x.from, x.to, k);
    }
    renderer.render(scene, camera);
    if (pinned && hovered !== pinned && !tween) {
      const c = centreOnScreen(pinned);
      if (c) showTip(pinned, c.x, c.y);
    }
  });

  el.classList.add('is-ready');
  return {
    setMode, setFloor, focus, setChoice,
    floors: floors.map(({ id, label }) => ({ id, label })),
    highlight: fid => { if (mode === 'fittings') highlight(fid); },
    clear: () => clearHighlight(),
  };
}
