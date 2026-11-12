/*
 * revrook scenes (docs/design-system.md, Scenes). One ES module for every scene of
 * the interface outside the Evidence Explorer: the rookery skyline of Home and the
 * domain keep of a client overview. Same origin, no eval, nothing from outside:
 * three.js r186 is vendored in /static/vendor/three (hashes in PINNED.json) and is
 * imported only on a page that carries a scene and only after the browser has
 * shown it offers WebGL 2, so every other page never downloads the library.
 *
 * A scene reads its facts from the page itself: the data attributes the template
 * renders on the rings and bars from the same view model, so the scene and the
 * page can never disagree and no request is made. The rings and the bars stay the
 * record; the scene is one way of looking at them. Depth means the same thing in
 * every scene: height is a measure, footprint is weight, status is shape and
 * colour together, and every word is in the DOM (the detail line, the cards, the
 * tables): nothing is written inside the scene.
 *
 * Each of these leaves the page as the server drew it:
 * - no script, or no WebGL 2: the stage stays hidden, no empty box, no import;
 * - the scene library cannot be loaded: a note says so, the stage stays small;
 * - the browser refuses a WebGL context when a scene is shown (WebGL switched off
 *   or unavailable after the first check, THE-1414): the half-built canvas goes,
 *   a note in the stage says so and the button can try again;
 * - a lost graphics context: drawing stops, the note says so, drawing resumes
 *   when the browser restores the context;
 * - prefers-reduced-motion: every move is immediate, nothing turns by itself;
 *   nothing turns by itself in any case, the scenes move on a person's action.
 * Frames are drawn only when something changed, never while the page is hidden
 * or the stage is out of view. Leaving the page disposes every geometry, material
 * and the renderer; each stage exposes revrookScene (dispose, mount, info) so a
 * test can cycle a scene and read the renderer's counts. A person can hide the
 * scenes with the button under a stage; the choice is kept in this browser only.
 */

// The office model is imported with the version of this script (the `v` query of
// its own address): a cache in front of the site keeps a static file for hours,
// so an unversioned import served the previous buildings after a deploy.
const OFFICE_URL = "./office.js" + new URL(import.meta.url).search;
let officeBuilding = null;
let streetKit = null;

const THREE_URL = "/static/vendor/three/three.module.js";
const HIDE_KEY = "rv-scenes";

// The stage colours: the brand charcoal of the stylesheet as the ground, the
// dark-theme status values on it (each reaches 4.5 to 1 on that ground), the
// dark-theme link colour for a mark.
const GROUND = 0x2d2f3a;
const GROUND_SOFT = 0x343746;
const LINE = 0x4d5261;
const ACCENT = 0x8b97f2;
const PICKED = 0xffffff;
const STATUS_COLOR = {
  protected: 0x4fbf7a,
  "needs-attention": 0xe0a93c,
  "not-protected": 0xff8a80,
  "not-checked": 0xaab0bd,
};
// The roof light of an office says its band in the status colours: green for a
// strong or a good client, amber for a fair one, red for a weak or a critical one.
const BAND_RING = {
  strong: STATUS_COLOR.protected,
  good: STATUS_COLOR.protected,
  fair: STATUS_COLOR["needs-attention"],
  weak: STATUS_COLOR["not-protected"],
  critical: STATUS_COLOR["not-protected"],
};
const LAYERS = ["protected", "needs-attention", "not-protected", "not-checked"];

const TURN_STEP = Math.PI / 8;
const TWEEN_MS = 350;
const MIN_PITCH = 0.12;
const MAX_PITCH = 1.2;
const DIM = 0.22;

const WORDS = {
  loading: "Preparing the scene.",
  noModule: "The scene library could not be loaded. Reload the page; the cards and the bars show the same facts.",
  lost: "The browser paused its drawing (the graphics context was lost). It resumes by itself when it can; the page is unchanged.",
  closed: "The 3D view is off. The cards and the bars show the same facts.",
  noWebGL: "This browser could not start the 3D view: WebGL is switched off or unavailable. The cards and the bars show the same facts.",
  footprints: "Every client is an empty lot: nothing is imported yet. Import an export and its office rises here.",
};

// The ground of a stage: the colour the stylesheet gives it (--rv-scene-ground,
// the charcoal of the keep band on Home, THE-1313), or the brand charcoal.
function groundOf(node) {
  const value = getComputedStyle(node).getPropertyValue("--rv-scene-ground").trim();
  return /^#[0-9a-f]{6}$/i.test(value) ? parseInt(value.slice(1), 16) : GROUND;
}

function words(node, text) {
  if (node) {
    node.textContent = text;
  }
}

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value));
}

function easeOut(t) {
  return 1 - (1 - t) * (1 - t);
}

function number(element, name) {
  const value = Number(element.getAttribute("data-" + name));
  return Number.isFinite(value) ? value : 0;
}

// The address a node opens is read from the page, so only a path of this site is
// accepted: one leading slash, no scheme, no host, no control character. Anything
// else leaves the node without an address; the card or the bar keeps its own link.
function pathOf(element) {
  const value = element.getAttribute("data-href") || "";
  if (!/^\/(?![/\\])[\x21-\x7e]*$/.test(value)) {
    return "";
  }
  return value;
}

function supportsWebGL2() {
  const probe = document.createElement("canvas");
  let context = null;
  try {
    context = probe.getContext("webgl2");
  } catch (error) {
    context = null;
  }
  if (!context) {
    return false;
  }
  const lose = context.getExtension("WEBGL_lose_context");
  if (lose) {
    lose.loseContext();
  }
  return true;
}

// The scenes start hidden: the cards and the bars carry the facts, and the 3D view
// is drawn (and three.js loaded) only once a person asks for it in this browser.
function scenesHidden() {
  try {
    return window.localStorage.getItem(HIDE_KEY) !== "on";
  } catch (error) {
    return true;
  }
}

function rememberHidden(off) {
  try {
    if (off) {
      window.localStorage.removeItem(HIDE_KEY);
    } else {
      window.localStorage.setItem(HIDE_KEY, "on");
    }
  } catch (error) {
    // A browser that refuses storage keeps the choice for this page only.
  }
}

function nodeOf(object) {
  let current = object;
  while (current) {
    if (current.userData && current.userData.node) {
      return current.userData.node;
    }
    current = current.parent;
  }
  return null;
}

function disposeObject(object) {
  if (object.geometry) {
    object.geometry.dispose();
  }
  if (object.material) {
    const materials = Array.isArray(object.material) ? object.material : [object.material];
    materials.forEach((material) => {
      if (material.map) {
        material.map.dispose();
      }
      material.dispose();
    });
  }
}

// --- the readers: what each scene is made of, read from the page -----------------

// The rookery skyline: one rook per client card of Home. Its height is the score,
// a client whose evidence is too thin is a wire rook (the dashed ring of its card),
// a client without evidence is a footprint, and a notch at its foot stands for
// every control that needs work.
function readRookery(list) {
  const items = Array.from(list.querySelectorAll("[data-client]"));
  return items.map((element, index) => {
    const band = (element.getAttribute("data-band") || "").toLowerCase();
    const insufficient = element.getAttribute("data-insufficient") === "true";
    const evidence = number(element, "evidence") > 0;
    const score = clamp(number(element, "score"), 0, 100);
    const needsWork = number(element, "needs-work");
    const size = Math.max(0, number(element, "size"));
    const name = element.getAttribute("data-name") || "";
    const scoreText = element.getAttribute("data-score-text") || String(score);
    let said = name + ": ";
    if (!evidence) {
      said += "no evidence imported yet.";
    } else if (insufficient) {
      said += "insufficient evidence, lower bound " + scoreText + ".";
    } else {
      said += "score " + scoreText + ", " + (element.getAttribute("data-band") || "") + ".";
    }
    if (evidence) {
      said += " " + needsWork + (needsWork === 1 ? " control needs" : " controls need") + " work.";
    }
    if (size > 0) {
      said += " " + size + (size === 1 ? " person or device." : " people or devices.");
    }
    return {
      id: "client:" + element.getAttribute("data-client"),
      index,
      element,
      href: pathOf(element),
      label: said,
      kind: "rook",
      // An office per client: as many floors as its score allows (2 to 12), as
      // wide as the company (one person is the narrowest, 500 or more the widest,
      // on a log scale so a big client does not hide the others).
      floors: evidence ? 2 + Math.round((score / 100) * 10) : 0,
      width: 0.45 + 0.5 * clamp(Math.log10(size + 1) / Math.log10(501), 0, 1),
      strip: evidence ? BAND_RING[band] || STATUS_COLOR["not-checked"] : LINE,
      state: !evidence ? "lot" : insufficient ? "frame" : "built",
      footprint: !evidence,
      notches: Math.min(needsWork, 12),
      seed: number(element, "client") || index + 1,
    };
  });
}

// The domain keep: one block per domain of the coverage card. Its footprint is
// the weight of the domain in the score, its layers are the controls by status,
// bottom up: protected, needs attention, not protected, and not checked as wire.
function readKeep(list) {
  const items = Array.from(list.querySelectorAll("[data-code]"));
  const heaviest = Math.max(1, ...items.map((element) => number(element, "weight")));
  return items.map((element, index) => {
    const layers = LAYERS.map((key) => ({ key, count: number(element, "count-" + key) }));
    const total = layers.reduce((sum, layer) => sum + layer.count, 0);
    const protectedCount = layers[0].count;
    const name = element.getAttribute("data-name") || "";
    const said =
      name + ": " + protectedCount + " of " + total + " controls protected, weight " + number(element, "weight") + ", score " + (element.getAttribute("data-score") || "") + ".";
    return {
      id: "domain:" + element.getAttribute("data-code"),
      index,
      element,
      href: pathOf(element),
      label: said,
      kind: "block",
      side: 0.45 + 0.75 * Math.sqrt(number(element, "weight") / heaviest),
      layers,
    };
  });
}

const READERS = { rookery: readRookery, keep: readKeep };

// --- the builders: a group of meshes per node, one material per node ------------

function buildOffice(THREE, entry, x, z) {
  const built = officeBuilding(THREE, {
    width: entry.width,
    depth: 0.62,
    floors: entry.floors,
    state: entry.state,
    strip: entry.strip,
    red: entry.notches,
    seed: entry.seed,
  });
  built.group.userData.node = entry.id;
  built.group.position.set(x, 0, z);
  return built;
}

function buildBlock(THREE, entry, x, z) {
  const group = new THREE.Group();
  group.userData.node = entry.id;
  const materials = [];
  const plinth = new THREE.Mesh(
    new THREE.BoxGeometry(entry.side + 0.24, 0.08, entry.side + 0.24),
    new THREE.MeshStandardMaterial({ color: GROUND_SOFT, roughness: 1, transparent: true })
  );
  materials.push(plinth.material);
  plinth.position.y = 0.04;
  group.add(plinth);
  let y = 0.08;
  const step = 0.16;
  entry.layers.forEach((layer) => {
    if (layer.count <= 0) {
      return;
    }
    const height = layer.count * step;
    const glass = layer.key === "not-checked";
    const material = new THREE.MeshStandardMaterial({
      color: STATUS_COLOR[layer.key],
      roughness: glass ? 0.2 : 0.55,
      metalness: 0.05,
      transparent: true,
      opacity: glass ? 0.32 : 1,
      depthWrite: !glass,
    });
    material.userData.base = material.opacity;
    materials.push(material);
    const geometry = new THREE.BoxGeometry(entry.side, height - 0.02, entry.side);
    const slab = new THREE.Mesh(geometry, material);
    slab.position.y = y + height / 2;
    slab.castShadow = !glass;
    slab.receiveShadow = true;
    group.add(slab);
    if (glass) {
      const edge = new THREE.LineBasicMaterial({ color: STATUS_COLOR[layer.key], transparent: true, opacity: 0.7 });
      edge.userData.base = 0.7;
      materials.push(edge);
      const outline = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), edge);
      outline.position.copy(slab.position);
      group.add(outline);
    }
    y += height;
  });
  group.position.set(x, 0, z);
  return { group, materials, top: y + 0.2 };
}

// Where every node stands: a row along a shallow arc, two rows when there are many
// (more than six blocks, more than eight rooks), so a row never runs so wide that
// every node is small, and the nearest never hides the one behind it.
function rowOf(count, limit) {
  return count > limit ? Math.ceil(count / 2) : count;
}

function place(count, spacing, limit) {
  const perRow = rowOf(count, limit);
  const positions = [];
  for (let k = 0; k < count; k += 1) {
    const row = Math.floor(k / perRow);
    const column = k % perRow;
    const inRow = Math.min(perRow, count - row * perRow);
    const x = (column - (inRow - 1) / 2) * spacing;
    const z = row * -1.9 + Math.abs(x) * 0.08;
    positions.push({ x, z });
  }
  return positions;
}

// The home distance that keeps every corner of every node inside the stage
// (THE-1188). The camera orbits `target` at `yaw` and `pitch` and looks at it
// with a vertical field of `fov` degrees and the stage's `aspect`; for each
// corner the distance is found at which it sits exactly on the edge of the view
// (in its width and in its height), and the largest wins, so nothing is cut,
// whatever the shape of the stage. `margin` keeps a little air round the edge
// (0.88 leaves six percent on each side) and `floor` stops a lone node filling
// the stage. The earlier estimate fitted the width of the front row and the
// tallest node but not the depth of a second row seen from above, so at 768px
// the front blocks of a client's keep ran off the foot of the stage. Pure, so a
// test can run it without a browser.
export function framingDistance(corners, view, target, fov, aspect, margin = 0.88, floor = 4.5) {
  const tall = Math.tan(((fov / 2) * Math.PI) / 180) * margin;
  const wide = tall * aspect;
  // The camera's own axes: back (from the target to the camera), right and up.
  const cp = Math.cos(view.pitch);
  const sp = Math.sin(view.pitch);
  const cy = Math.cos(view.yaw);
  const sy = Math.sin(view.yaw);
  const back = { x: cp * sy, y: sp, z: cp * cy };
  const right = { x: cy, y: 0, z: -sy };
  const up = { x: -sp * sy, y: cp, z: -sp * cy };
  let distance = floor;
  corners.forEach((corner) => {
    const v = { x: corner.x - target.x, y: corner.y - target.y, z: corner.z - target.z };
    const along = v.x * back.x + v.y * back.y + v.z * back.z;
    const across = Math.abs(v.x * right.x + v.z * right.z);
    const high = Math.abs(v.x * up.x + v.y * up.y + v.z * up.z);
    distance = Math.max(distance, across / wide + along, high / tall + along);
  });
  return distance;
}

// The eight corners of a box (THREE.Box3 or anything with min and max).
function cornersOf(box, into) {
  [box.min.x, box.max.x].forEach((x) => {
    [box.min.y, box.max.y].forEach((y) => {
      [box.min.z, box.max.z].forEach((z) => {
        into.push({ x, y, z });
      });
    });
  });
  return into;
}

// --- one scene: built from the page once, drawn on demand, disposed whole -------

function buildScene(THREE, root, options) {
  const page = root.ownerDocument;
  const stage = root.querySelector(".rv-scene-stage");
  const detail = root.querySelector(".rv-scene-detail");
  const hover = root.querySelector(".rv-scene-hover");
  const kind = root.getAttribute("data-scene");
  const list = page.getElementById(root.getAttribute("data-scene-for") || "");
  const entries = list ? READERS[kind](list) : [];
  // What the detail line says while nothing is chosen: the hint of the page, or,
  // when every client is only a footprint, what to do so a rook stands here.
  const idle = entries.length && entries.every((entry) => entry.footprint) ? WORDS.footprints : root.getAttribute("data-scene-hint") || "";
  const controller = new AbortController();
  const signal = controller.signal;

  const canvas = document.createElement("canvas");
  canvas.tabIndex = 0;
  canvas.setAttribute("role", "application");
  canvas.setAttribute("aria-roledescription", "scene");
  canvas.setAttribute("aria-label", root.getAttribute("data-scene-label") || "Scene");
  canvas.setAttribute("aria-describedby", detail ? detail.id : "");
  stage.insertBefore(canvas, stage.firstChild);

  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: false,
    powerPreference: "low-power",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const ground = groundOf(root);
  renderer.setClearColor(ground, 1);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 21 / 9, 0.1, 80);
  const spacing = kind === "keep" ? 1.7 : 1.35;
  const limit = kind === "keep" ? 6 : 8;
  const spots = place(entries.length, spacing, limit);
  const rows = entries.length > limit ? 2 : 1;
  const span = Math.max(3, (Math.max(1, rowOf(entries.length, limit)) - 1) * spacing + 2);
  const tallest = entries.reduce((top, entry) => {
    const own = entry.kind === "rook" ? 0.28 + entry.floors * 0.2 : entry.layers.reduce((sum, layer) => sum + layer.count * 0.16, 0);
    return Math.max(top, own);
  }, 0.5);
  const home = { yaw: 0.35, pitch: 0.55, distance: span * 1.15 + 3 };
  const target = new THREE.Vector3(0, Math.min(0.6, 0.25 + tallest / 2), rows > 1 ? -0.9 : 0);
  const view = { yaw: home.yaw, pitch: home.pitch, distance: home.distance };

  // The home distance fits every node to the stage at the home view: the nearest
  // distance at which no corner of any node (its plinth, its layers, its wire top)
  // falls outside the view, for the shape the stage has now (framingDistance).
  const corners = [];
  function fitDistance() {
    return framingDistance(corners, home, target, camera.fov, camera.aspect);
  }

  const sky = new THREE.HemisphereLight(0xffffff, ground, 1.5);
  scene.add(sky);
  const sun = new THREE.DirectionalLight(0xfff4e6, 2.1);
  sun.position.set(4, 9, 6);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  sun.shadow.radius = 4;
  sun.shadow.bias = -0.0008;
  const reach = span * 0.9 + 2;
  sun.shadow.camera.left = -reach;
  sun.shadow.camera.right = reach;
  sun.shadow.camera.top = reach;
  sun.shadow.camera.bottom = -reach;
  sun.shadow.camera.near = 1;
  sun.shadow.camera.far = 30;
  scene.add(sun);
  // Depth: a cool rim light from behind the yard picks out the battlements, and
  // the far side of the yard fades into the ground colour.
  const rim = new THREE.DirectionalLight(ACCENT, 0.9);
  rim.position.set(-5, 4, -8);
  scene.add(rim);
  scene.fog = new THREE.Fog(ground, home.distance * 0.9, home.distance * 2.4);

  // The ground: a wide disc, and a thin ring as the edge of the yard.
  const floor = new THREE.Mesh(
    new THREE.CircleGeometry(span * 0.9 + 1.5, 72),
    new THREE.MeshStandardMaterial({ color: ground, roughness: 1 })
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -0.02;
  floor.receiveShadow = true;
  scene.add(floor);
  // The rookery is a street: a road in front of the offices, a pavement, trees
  // and street lamps between the buildings, and a second street behind when the
  // clients take two rows.
  if (kind === "rookery") {
    const kit = streetKit(THREE);
    const long = Math.max(5, (Math.max(1, rowOf(entries.length, limit)) - 1) * spacing + 3.4);
    const road = new THREE.MeshStandardMaterial({ color: 0x24262d, roughness: 0.95 });
    const pavement = new THREE.MeshStandardMaterial({ color: 0x4c5160, roughness: 0.9 });
    const paint = new THREE.MeshStandardMaterial({ color: 0xe8e2cf, roughness: 0.6 });
    const fronts = rows > 1 ? [0, -1.9] : [0];
    const grass = new THREE.MeshStandardMaterial({ color: 0x34473b, roughness: 1 });
    fronts.forEach((front) => {
      // The block the offices stand on: a lawn behind the pavement, with trees.
      const block = new THREE.Mesh(new THREE.BoxGeometry(long, 0.02, 1.05), grass);
      block.position.set(0, 0.01, front - 0.15);
      block.receiveShadow = true;
      scene.add(block);
      for (let x = -long / 2 + 0.3; x < long / 2; x += 0.55) {
        scene.add(kit.tree(x, front - 0.58, 0.75 + ((Math.round(x * 10) % 3) + 3) % 3 * 0.12));
      }
      const walk = new THREE.Mesh(new THREE.BoxGeometry(long, 0.03, 0.34), pavement);
      walk.position.set(0, 0.015, front + 0.55);
      walk.receiveShadow = true;
      scene.add(walk);
      const lane = new THREE.Mesh(new THREE.BoxGeometry(long, 0.01, 0.62), road);
      lane.position.set(0, 0.005, front + 1.03);
      lane.receiveShadow = true;
      scene.add(lane);
      for (let x = -long / 2 + 0.2; x < long / 2; x += 0.42) {
        const dash = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.012, 0.025), paint);
        dash.position.set(x + 0.1, 0.012, front + 1.03);
        scene.add(dash);
      }
      // Trees and lamps stand between the offices, never in front of one.
      const row = spots.filter((spot) => Math.abs(spot.z - front) < 1).map((spot) => spot.x);
      const gaps = row.length ? [row[0] - spacing / 2, ...row.map((x) => x + spacing / 2)] : [0];
      gaps.forEach((x, k) => {
        scene.add(k % 2 ? kit.streetLamp(x, front + 0.62) : kit.tree(x, front + 0.5, 0.9 + (k % 3) * 0.1));
      });
    });
  }

  const pickables = [];
  const nodes = new Map();
  entries.forEach((entry, index) => {
    const spot = spots[index];
    const built = entry.kind === "rook" ? buildOffice(THREE, entry, spot.x, spot.z) : buildBlock(THREE, entry, spot.x, spot.z);
    scene.add(built.group);
    pickables.push(built.group);
    nodes.set(entry.id, { entry, group: built.group, materials: built.materials });
  });
  const bounds = new THREE.Box3();
  nodes.forEach((node) => {
    cornersOf(bounds.setFromObject(node.group), corners);
  });

  let rafId = 0;
  let needsRender = true;
  let lost = false;
  let hidden = document.hidden;
  let inView = true;
  let tween = null;
  let selected = null;
  let hovered = null;

  function placeCamera() {
    const flat = Math.cos(view.pitch) * view.distance;
    camera.position.set(
      target.x + flat * Math.sin(view.yaw),
      target.y + Math.sin(view.pitch) * view.distance,
      target.z + flat * Math.cos(view.yaw)
    );
    camera.lookAt(target);
  }

  function render() {
    placeCamera();
    renderer.render(scene, camera);
  }

  function frame(now) {
    rafId = 0;
    if (tween) {
      const t = clamp((now - tween.start) / TWEEN_MS, 0, 1);
      view.yaw = tween.from + (tween.to - tween.from) * easeOut(t);
      needsRender = true;
      if (t >= 1) {
        tween = null;
      }
    }
    if (needsRender && !lost && !hidden && inView) {
      render();
      needsRender = false;
    }
    if (tween) {
      schedule();
    }
  }

  function schedule() {
    if (!rafId && !lost) {
      rafId = window.requestAnimationFrame(frame);
    }
  }

  function invalidate() {
    needsRender = true;
    schedule();
  }

  function resize() {
    const width = Math.max(stage.clientWidth, 1);
    const height = Math.max(stage.clientHeight, 1);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    // A stage of another shape fits the row again; a view a person moved closer
    // or further away keeps its own distance.
    const atHome = Math.abs(view.distance - home.distance) < 0.001;
    home.distance = fitDistance();
    scene.fog.near = home.distance * 0.9;
    scene.fog.far = home.distance * 2.4;
    if (atHome) {
      view.distance = home.distance;
    }
    invalidate();
  }

  // Selection and hover: the chosen node comes forward and the rest step back;
  // the card or the bar of the node on the page is marked the same way.
  function paint() {
    const focus = selected || hovered;
    nodes.forEach((node, id) => {
      const own = focus === id;
      node.materials.forEach((material) => {
        const base = material.userData.base === undefined ? 1 : material.userData.base;
        material.opacity = !focus || own ? base : base * DIM;
        if (material.emissive) {
          material.emissive.setHex(own ? PICKED : material.userData.emissive || 0x000000);
          material.emissiveIntensity = own ? 0.22 : material.userData.emissiveIntensity || 0;
        }
      });
    });
    invalidate();
  }

  function markPage() {
    nodes.forEach((node, id) => {
      node.entry.element.setAttribute("data-selected", id === selected ? "true" : "false");
    });
  }

  function select(id, face) {
    selected = nodes.has(id) ? id : null;
    const node = selected ? nodes.get(selected) : null;
    words(detail, node ? node.entry.label + (node.entry.href ? " Press Enter to open it." : "") : idle);
    markPage();
    if (node && face) {
      // The yard leans a little towards the chosen node and no further: a turn to
      // face it squarely would line the row up behind it and hide the others.
      const lean = Math.atan2(node.group.position.x - target.x, Math.max(home.distance, 1));
      turnTo(home.yaw + clamp(lean, -TURN_STEP, TURN_STEP));
    }
    paint();
  }

  function setHover(id) {
    hovered = nodes.has(id) ? id : null;
    words(hover, hovered ? nodes.get(hovered).entry.label : "");
    canvas.style.cursor = hovered ? "pointer" : "";
    paint();
  }

  function turnTo(yaw) {
    if (options.reducedMotion) {
      view.yaw = yaw;
      tween = null;
      invalidate();
      return;
    }
    tween = { from: view.yaw, to: yaw, start: performance.now() };
    schedule();
  }

  function turnBy(delta) {
    turnTo((tween ? tween.to : view.yaw) + delta);
  }

  function zoomBy(factor) {
    view.distance = clamp(view.distance * factor, home.distance * 0.45, home.distance * 1.6);
    invalidate();
  }

  function reset() {
    tween = null;
    view.yaw = home.yaw;
    view.pitch = home.pitch;
    view.distance = home.distance;
    select(null, false);
    invalidate();
  }

  function step(delta) {
    const ids = entries.map((entry) => entry.id);
    if (!ids.length) {
      return;
    }
    const at = selected ? ids.indexOf(selected) : -1;
    const next = at < 0 ? (delta > 0 ? 0 : ids.length - 1) : (at + delta + ids.length) % ids.length;
    select(ids[next], true);
  }

  function open() {
    const node = selected ? nodes.get(selected) : null;
    if (node && node.entry.href) {
      window.location.assign(node.entry.href);
    }
  }

  // Pointer: a drag turns and tilts the yard, a short press picks a node.
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  let press = null;

  function pick(event) {
    const box = canvas.getBoundingClientRect();
    pointer.x = ((event.clientX - box.left) / box.width) * 2 - 1;
    pointer.y = -((event.clientY - box.top) / box.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    const hits = raycaster.intersectObjects(pickables, true);
    return hits.length ? nodeOf(hits[0].object) : null;
  }

  canvas.addEventListener(
    "pointerdown",
    (event) => {
      if (event.button !== 0 && event.pointerType === "mouse") {
        return;
      }
      press = { x: event.clientX, y: event.clientY, moved: false, id: event.pointerId };
      canvas.setPointerCapture(event.pointerId);
    },
    { signal }
  );
  canvas.addEventListener(
    "pointermove",
    (event) => {
      if (press && press.id === event.pointerId) {
        const dx = event.clientX - press.x;
        const dy = event.clientY - press.y;
        if (press.moved || Math.abs(dx) + Math.abs(dy) > 4) {
          press.moved = true;
          tween = null;
          view.yaw -= dx * 0.006;
          view.pitch = clamp(view.pitch + dy * 0.004, MIN_PITCH, MAX_PITCH);
          press.x = event.clientX;
          press.y = event.clientY;
          invalidate();
        }
        return;
      }
      if (event.pointerType === "mouse") {
        setHover(pick(event));
      }
    },
    { signal }
  );
  canvas.addEventListener(
    "pointerup",
    (event) => {
      if (press && press.id === event.pointerId) {
        if (!press.moved) {
          const id = pick(event);
          select(selected === id ? null : id, false);
        }
        press = null;
      }
    },
    { signal }
  );
  canvas.addEventListener("pointercancel", () => { press = null; }, { signal });
  canvas.addEventListener("pointerleave", () => setHover(null), { signal });
  canvas.addEventListener(
    "keydown",
    (event) => {
      const keys = {
        ArrowLeft: () => step(-1),
        ArrowRight: () => step(1),
        "[": () => turnBy(-TURN_STEP),
        "]": () => turnBy(TURN_STEP),
        "+": () => zoomBy(0.85),
        "=": () => zoomBy(0.85),
        "-": () => zoomBy(1.18),
        Home: () => reset(),
        Enter: () => open(),
        Escape: () => select(null, false),
      };
      const action = keys[event.key];
      if (action) {
        event.preventDefault();
        action();
      }
    },
    { signal }
  );

  // The buttons under the stage.
  const buttons = {
    ".rv-scene-turn-left": () => turnBy(-TURN_STEP),
    ".rv-scene-turn-right": () => turnBy(TURN_STEP),
    ".rv-scene-reset": () => reset(),
  };
  Object.keys(buttons).forEach((selector) => {
    const button = root.querySelector(selector);
    if (button) {
      button.addEventListener("click", buttons[selector], { signal });
    }
  });
  // Pointing at a card or a bar of the page lights its node in the scene.
  if (list) {
    list.addEventListener(
      "pointerover",
      (event) => {
        const item = event.target.closest ? event.target.closest("[data-client], [data-code]") : null;
        const found = entries.find((entry) => entry.element === item);
        setHover(found ? found.id : null);
      },
      { signal }
    );
    list.addEventListener("pointerleave", () => setHover(null), { signal });
  }

  // Context loss, visibility, view and size.
  canvas.addEventListener(
    "webglcontextlost",
    (event) => {
      event.preventDefault();
      lost = true;
      if (rafId) {
        window.cancelAnimationFrame(rafId);
        rafId = 0;
      }
      options.setState("note", WORDS.lost);
    },
    { signal }
  );
  // A restored context is a new one: three.js rebuilds its state on it with the
  // default clear colour, black, so the sky stood black over the redrawn yard
  // (THE-1401). Its listener runs first (it was added with the renderer); this
  // one gives the stage its ground again from the stylesheet, which also redraws.
  canvas.addEventListener(
    "webglcontextrestored",
    () => {
      lost = false;
      options.hideState();
      applyGround();
    },
    { signal }
  );
  document.addEventListener(
    "visibilitychange",
    () => {
      hidden = document.hidden;
      if (!hidden) {
        invalidate();
      }
    },
    { signal }
  );
  const watcher = new IntersectionObserver((records) => {
    records.forEach((record) => {
      inView = record.isIntersecting;
    });
    if (inView) {
      invalidate();
    }
  });
  watcher.observe(stage);
  const sizer = new ResizeObserver(() => resize());
  sizer.observe(stage);

  // A theme switch changes the band in place (revrook.js sets data-theme; the
  // System theme follows the colour scheme of the device): the scene takes the
  // new ground for its clear colour, its fog, its sky light and its floor.
  function applyGround() {
    const next = groundOf(root);
    renderer.setClearColor(next, 1);
    scene.fog.color.setHex(next);
    sky.groundColor.setHex(next);
    floor.material.color.setHex(next);
    invalidate();
  }
  const themeWatcher = new MutationObserver(applyGround);
  themeWatcher.observe(page.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  const schemeQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  if (schemeQuery) {
    schemeQuery.addEventListener("change", applyGround, { signal });
  }

  function dispose() {
    controller.abort();
    watcher.disconnect();
    sizer.disconnect();
    themeWatcher.disconnect();
    if (rafId) {
      window.cancelAnimationFrame(rafId);
      rafId = 0;
    }
    scene.traverse(disposeObject);
    scene.clear();
    renderer.dispose();
    renderer.forceContextLoss();
    canvas.remove();
    nodes.forEach((node) => node.entry.element.removeAttribute("data-selected"));
    words(hover, "");
  }

  function info() {
    return {
      nodes: nodes.size,
      geometries: renderer.info.memory.geometries,
      textures: renderer.info.memory.textures,
      programs: renderer.info.programs ? renderer.info.programs.length : 0,
      lost,
    };
  }

  function applyMotion() {
    if (options.reducedMotion && tween) {
      view.yaw = tween.to;
      tween = null;
    }
    invalidate();
  }

  resize();
  select(null, false);
  return { dispose, info, select, reset, applyMotion };
}

// --- the page: every stage, the shared options, the hide button ------------------

export async function prepare(root, THREE, motionQuery) {
  const state = root.querySelector(".rv-scene-state");
  const stateText = state ? state.querySelector(".rv-scene-state-text") : null;
  const tools = root.querySelector(".rv-scene-tools");
  const toggle = root.querySelector(".rv-scene-toggle");
  let built = null;
  const options = {
    reducedMotion: Boolean(motionQuery && motionQuery.matches),
    setState(kind, message) {
      if (state) {
        state.hidden = false;
        state.classList.toggle("is-loading", kind === "loading");
        state.setAttribute("data-kind", kind);
        words(stateText, message);
      }
    },
    hideState() {
      if (state) {
        state.hidden = true;
        state.classList.remove("is-loading");
        state.removeAttribute("data-kind");
      }
    },
  };

  // The button names the action it offers next, so it is not a pressed state as
  // well: one signal, the words.
  function syncToggle() {
    if (toggle) {
      words(toggle.querySelector(".rv-scene-toggle-text") || toggle, built ? "Hide the 3D view" : "Show the 3D view");
    }
  }

  function mount() {
    if (built) {
      return built;
    }
    try {
      built = buildScene(THREE, root, options);
    } catch (error) {
      // The renderer could not get a WebGL context: say so in the stage instead
      // of leaving the button doing nothing visible, and drop the empty canvas.
      const left = root.querySelector(".rv-scene-stage canvas");
      if (left) {
        left.remove();
      }
      built = null;
      root.classList.remove("is-closed");
      options.setState("error", WORDS.noWebGL);
      root.setAttribute("data-scene-state", "error");
      if (tools) {
        tools.hidden = true;
      }
      syncToggle();
      return null;
    }
    options.hideState();
    if (tools) {
      tools.hidden = false;
    }
    root.setAttribute("data-scene-state", "ready");
    root.classList.remove("is-closed");
    syncToggle();
    return built;
  }

  function dispose() {
    if (built) {
      built.dispose();
      built = null;
      options.setState("note", WORDS.closed);
      root.setAttribute("data-scene-state", "disposed");
      if (tools) {
        tools.hidden = true;
      }
      syncToggle();
    }
  }

  if (motionQuery) {
    motionQuery.addEventListener("change", (event) => {
      options.reducedMotion = event.matches;
      if (built) {
        built.applyMotion();
      }
    });
  }
  if (toggle) {
    toggle.hidden = false;
    toggle.addEventListener("click", () => {
      if (built) {
        dispose();
        root.classList.add("is-closed");
        rememberHidden(true);
      } else {
        rememberHidden(false);
        mount();
      }
    });
  }
  if (scenesHidden()) {
    options.setState("note", WORDS.closed);
    root.setAttribute("data-scene-state", "disposed");
    root.classList.add("is-closed");
    syncToggle();
  } else {
    mount();
  }
  root.revrookScene = {
    mount,
    dispose,
    info: () => (built ? built.info() : null),
    select: (id) => (built ? built.select(id, true) : undefined),
    get reducedMotion() {
      return options.reducedMotion;
    },
  };
  window.addEventListener("pagehide", dispose);
  window.addEventListener("pageshow", (event) => {
    if (event.persisted && !scenesHidden()) {
      mount();
    }
  });
}

// A stage with nothing to draw (a page without a client, a list without a bar) or
// a browser without WebGL 2 is marked unavailable: the stylesheet keeps it out of
// the page, also where it reserved the room before the script ran.
function putAway(roots) {
  roots.forEach((root) => {
    root.hidden = true;
    root.setAttribute("data-scene-state", "unavailable");
  });
}

function hasNodes(root) {
  const list = document.getElementById(root.getAttribute("data-scene-for") || "");
  return Boolean(list && list.querySelector("[data-client], [data-code]"));
}

async function main() {
  const every = Array.from(document.querySelectorAll("[data-scene]"));
  if (!every.length) {
    return;
  }
  if (!supportsWebGL2()) {
    putAway(every);
    return;
  }
  putAway(every.filter((root) => !hasNodes(root)));
  const roots = every.filter(hasNodes);
  if (!roots.length) {
    return;
  }
  if (scenesHidden()) {
    // Closed until asked: no library is loaded. One press opens every stage of the
    // page and is remembered; `prepare` then wires the button as usual.
    let asked = false;
    roots.forEach((root) => {
      root.hidden = false;
      root.classList.add("is-closed");
      root.setAttribute("data-scene-state", "disposed");
      words(root.querySelector(".rv-scene-state-text"), WORDS.closed);
      const toggle = root.querySelector(".rv-scene-toggle");
      if (!toggle) {
        return;
      }
      toggle.hidden = false;
      words(toggle.querySelector(".rv-scene-toggle-text") || toggle, "Show the 3D view");
      toggle.addEventListener("click", () => {
        if (asked) {
          return;
        }
        asked = true;
        rememberHidden(false);
        roots.forEach((each) => {
          const old = each.querySelector(".rv-scene-toggle");
          if (old) {
            // A fresh button for `prepare`, without this one-time listener.
            old.replaceWith(old.cloneNode(true));
          }
        });
        openStages(roots);
      }, { once: true });
    });
    return;
  }
  await openStages(roots);
}

async function openStages(roots) {
  // The stages are revealed before the library is asked for, so the page settles
  // once; a reader of the DOM sees the same cards and bars whatever happens next.
  roots.forEach((root) => {
    root.hidden = false;
    root.classList.remove("is-closed");
    root.setAttribute("data-scene-state", "loading");
    const text = root.querySelector(".rv-scene-state-text");
    words(text, WORDS.loading);
  });
  let THREE;
  try {
    THREE = await import(THREE_URL);
    ({ officeBuilding, streetKit } = await import(OFFICE_URL));
  } catch (error) {
    roots.forEach((root) => {
      root.setAttribute("data-scene-state", "error");
      words(root.querySelector(".rv-scene-state-text"), WORDS.noModule);
    });
    return;
  }
  const motionQuery = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  for (const root of roots) {
    try {
      await prepare(root, THREE, motionQuery);
    } catch (error) {
      root.setAttribute("data-scene-state", "error");
      words(root.querySelector(".rv-scene-state-text"), WORDS.noModule);
    }
  }
}

// Imported outside a browser (the test of framingDistance), the module only
// defines its functions.
if (typeof document !== "undefined") {
  main();
}
