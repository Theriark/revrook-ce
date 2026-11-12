/*
 * revrook Evidence Explorer, a Development preview (docs/evidence-explorer-preview.md).
 * An ES module loaded by its page alone. Same origin, no eval, nothing from outside:
 * three.js r186 is vendored in /static/vendor/three (hashes in PINNED.json) and is
 * imported only after the browser has shown it offers WebGL 2, so a browser without
 * it never downloads the library.
 *
 * The tables of the page are the record. This script adds one way of looking at
 * them, in one of two views:
 * - the evidence wall of one client (?client_id=N, its data read as JSON): an office
 *   block per evidence source on an inner ring, a tile per control on an outer ring
 *   grouped by domain, a beam from a source to each control that reads it;
 * - the companies ring (the page without a client, read from the page itself: the
 *   rows of its tables and the lists of its card templates): an office per client
 *   on the inner ring, every control on the outer ring in the worst status it has
 *   at any client, and a link from every client to every control in the status of
 *   that pair, shown or hidden per status by the filter buttons. Choosing an office
 *   or a tile opens its card (scene-card.js), a template the server drew.
 * Status is shape and colour together, never colour alone, and every word is in the
 * DOM (the detail line, the legend, the tables, the cards): nothing is written
 * inside the scene.
 *
 * Each of these leaves the tables intact and says so in the stage:
 * - no WebGL 2: the note the server rendered stays, no import happens;
 * - the data cannot be read (a session that ended, a refused client, a failure): a
 *   note says what happened and what to do;
 * - a lost graphics context: drawing stops, the note says so, drawing resumes when
 *   the browser restores the context;
 * - prefers-reduced-motion: the wall never turns by itself and every move is
 *   immediate; otherwise it turns slowly until the person touches it.
 * Frames are drawn only when something changed or the wall is turning, and never
 * while the page is hidden or the stage is out of view. Leaving the page disposes
 * every geometry, material and the renderer; root.revrookExplorer exposes dispose,
 * mount and info so a test can cycle the scene and read the renderer's counts.
 */

// The office model is imported with the version of this script (the `v` query of
// its own address), so a cache in front of the site never serves an older one.
const OFFICE_URL = "./office.js" + new URL(import.meta.url).search;
const CARD_URL = "./scene-card.js" + new URL(import.meta.url).search;
let officeBuilding = null;
let sceneCard = null;

const THREE_URL = "/static/vendor/three/three.module.js";

// The stage colours: the brand charcoal of the stylesheet as the ground, the
// dark-theme status values on it (each reaches 4.5 to 1 on that ground), the stone
// of the brand for a current pillar and the dark-theme link colour for a beam.
const GROUND = 0x2d2f3a;
const SECTOR_EVEN = 0x272a34;
const SECTOR_ODD = 0x343746;
const LINE = 0x4d5261;
const STONE = 0xd9d6cf;
const BEAM = 0x8b97f2;
const PICKED = 0xffffff;
const STATUS_COLOR = {
  protected: 0x4fbf7a,
  "needs-attention": 0xe0a93c,
  "not-protected": 0xff8a80,
  "not-checked": 0xaab0bd,
  "not-applicable": 0x8a8f98,
};
const PILLAR_SCALE = { protected: 1, "needs-attention": 0.55, "not-protected": 0.35 };
// The roof light of a client's office says its band, as on Home's street.
const BAND_LIGHT = {
  strong: STATUS_COLOR.protected,
  good: STATUS_COLOR.protected,
  fair: STATUS_COLOR["needs-attention"],
  weak: STATUS_COLOR["not-protected"],
  critical: STATUS_COLOR["not-protected"],
};
// The links of the companies ring, per status: faint until a node is chosen, lit
// when one of their ends is, dimmed when another node is. Not applicable has none.
const LINK_OPACITY = { faint: 0.22, lit: 0.95, dim: 0.05 };
const LINKED = ["protected", "needs-attention", "not-protected", "not-checked"];
const LABEL_WORDS = {
  "not-protected": "not protected",
  "needs-attention": "needs attention",
  "not-checked": "not checked",
  protected: "protected",
  "not-applicable": "not applicable",
};

const SOURCE_RADIUS = 2.4;
const CONTROL_RADIUS = 5.3;
const FLOOR_RADIUS = 6.6;
const SECTOR_GAP = 0.07;
const TURN_STEP = Math.PI / 6;
const AUTO_TURN = 0.08; // radians per second
const TWEEN_MS = 350;
const MIN_PITCH = 0.2;
const MAX_PITCH = 1.25;
const MIN_DISTANCE = 7;
const MAX_DISTANCE = 21;
const HOME = { yaw: -Math.PI / 4, pitch: 0.72, distance: 15 };
// The edge the home view keeps inside the stage: the outer corners of the tiles.
const FIT_RADIUS = CONTROL_RADIUS + 0.35;
const FIT_EDGE = 0.94;
const DIM = 0.18;
const BEAM_OPACITY = 0.12;

const WORDS = {
  loading: "Preparing the scene.",
  noWebgl:
    "This browser offers no WebGL 2, so the scene is not drawn. The tables below show the same facts.",
  noModule:
    "The scene library could not be loaded. Reload the page; the tables below show the same facts.",
  session: "Your session has ended. Reload the page and sign in again.",
  lost: "The browser paused its drawing (the graphics context was lost). It resumes by itself when it can; the tables below are unchanged.",
  empty: "There is nothing to draw yet: this client has no evidence source and no control.",
  closed: "The 3D view is off. The tables below show the same facts.",
  off: "The 3D view is off. The tables below show the same facts; Show the 3D view draws them as a wall.",
};

// The choice of the scenes of every page (app/static/js/scenes.js, HIDE_KEY).
const SCENES_KEY = "rv-scenes";

function scenesShown() {
  try {
    return window.localStorage.getItem(SCENES_KEY) === "on";
  } catch (error) {
    return false;
  }
}

function rememberShown(on) {
  try {
    if (on) {
      window.localStorage.setItem(SCENES_KEY, "on");
    } else {
      window.localStorage.removeItem(SCENES_KEY);
    }
  } catch (error) {
    // A browser that refuses storage keeps the choice for this page only.
  }
}

function words(node, text) {
  if (node) {
    node.textContent = text;
  }
}

function dateWords(iso) {
  return iso ? iso.slice(0, 10) : "never";
}

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value));
}

function easeOut(t) {
  return 1 - (1 - t) * (1 - t);
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

async function loadData(url) {
  const response = await fetch(url, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  const type = response.headers.get("content-type") || "";
  if (response.redirected) {
    throw new Error(WORDS.session);
  }
  if (type.indexOf("application/json") < 0) {
    throw new Error("The data could not be read (status " + response.status + "). Reload the page; the tables below show the same facts.");
  }
  const body = await response.json();
  if (!response.ok) {
    // Only the plain sentence of a refusal is shown; any other shape gets the status.
    const said =
      typeof body.detail === "string" && body.detail
        ? body.detail
        : "The data could not be read (status " + response.status + ").";
    throw new Error(said + " Choose another client or reload the page; the tables below show the same facts.");
  }
  return body;
}

// The companies ring, read from the page: the rows of its two tables and the
// clients listed on each control card (the server drew them all, so nothing is
// fetched and no client is read twice).
function readCompanies(page) {
  const number = (row, name) => Number(row.getAttribute("data-" + name)) || 0;
  const clients = Array.from(page.querySelectorAll("#explorer-companies tr[data-node]")).map((row) => ({
    id: row.getAttribute("data-node") || "",
    name: row.getAttribute("data-name") || "",
    band: row.getAttribute("data-band") || "",
    scoreText: row.getAttribute("data-score-text") || "",
    score: clamp(number(row, "score"), 0, 100),
    evidence: number(row, "evidence") > 0,
    insufficient: row.getAttribute("data-insufficient") === "true",
    needsWork: number(row, "needs-work"),
    size: Math.max(0, number(row, "size")),
    href: row.getAttribute("data-href") || "",
  }));
  const controls = Array.from(page.querySelectorAll("#explorer-controls tr[data-node]")).map((row) => {
    const id = (row.getAttribute("data-node") || "").replace(/^control:/, "");
    const template = page.getElementById("control-card-" + id);
    const items = template && template.content ? Array.from(template.content.querySelectorAll("[data-client]")) : [];
    return {
      control_id: id,
      title: row.getAttribute("data-title") || "",
      domain: row.getAttribute("data-domain") || "",
      label: row.getAttribute("data-label") || "not-checked",
      href: row.getAttribute("data-href") || "",
      pairs: items.map((item) => ({ client: "client:" + item.getAttribute("data-client"), label: item.getAttribute("data-label") || "" })),
    };
  });
  return { companies: true, clients, controls, domains: [], sources: [] };
}

// Where every pillar, office and tile stands: the sources (or the clients) evenly
// on the inner ring, the controls on the outer ring in the order of the tables,
// each domain its own arc.
function layout(data) {
  const sources = data.sources.map((source, index) => {
    const angle = -Math.PI / 2 + (index * 2 * Math.PI) / Math.max(data.sources.length, 1);
    const fed = source.controls.length;
    const missing = source.state === "not-checked";
    const scale = PILLAR_SCALE[source.state] || 1;
    const height = missing ? 0.06 : Math.min(0.5 + 0.22 * fed, 2.6) * scale;
    return { id: "source:" + source.code, source, angle, height, missing };
  });
  const clients = (data.clients || []).map((client, index) => ({
    id: client.id,
    client,
    href: client.href,
    card: "client-card-" + client.id.replace(/^client:/, ""),
    angle: -Math.PI / 2 + (index * 2 * Math.PI) / Math.max(data.clients.length, 1),
  }));
  const codes = data.domains.map((domain) => domain.code);
  const byDomain = new Map(codes.map((code) => [code, []]));
  for (const control of data.controls) {
    if (!byDomain.has(control.domain)) {
      codes.push(control.domain);
      byDomain.set(control.domain, []);
    }
    byDomain.get(control.domain).push(control);
  }
  const total = data.controls.length;
  const per = total ? (2 * Math.PI - SECTOR_GAP * codes.length) / total : 0;
  const controls = [];
  const sectors = [];
  let angle = -Math.PI / 2;
  codes.forEach((code, index) => {
    const members = byDomain.get(code);
    const start = angle;
    members.forEach((control, position) => {
      controls.push({
        id: "control:" + control.control_id,
        control,
        href: control.href,
        card: data.companies ? "control-card-" + control.control_id : "",
        angle: start + (position + 0.5) * per,
      });
    });
    angle = start + members.length * per;
    sectors.push({ code, start, length: members.length * per, index });
    angle += SECTOR_GAP;
  });
  return { sources, clients, controls, sectors };
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

function describe(entry, data) {
  if (entry.client) {
    const client = entry.client;
    let said = client.name + ": ";
    if (!client.evidence) {
      return said + "no evidence imported yet.";
    }
    said += client.insufficient ? "insufficient evidence, lower bound " + client.scoreText + "." : "score " + client.scoreText + ", " + client.band + ".";
    return said + " " + client.needsWork + (client.needsWork === 1 ? " control needs" : " controls need") + " work.";
  }
  if (data.companies) {
    const control = entry.control;
    const counts = new Map();
    control.pairs.forEach((pair) => counts.set(pair.label, (counts.get(pair.label) || 0) + 1));
    const parts = Object.keys(LABEL_WORDS)
      .filter((key) => counts.get(key))
      .map((key) => LABEL_WORDS[key] + " at " + counts.get(key));
    const where = parts.length ? parts.join(", ") + " of " + control.pairs.length + (control.pairs.length === 1 ? " client" : " clients") : "no client read today";
    return control.control_id + " " + control.title.replace(/\.$/, "") + ", " + control.domain + ": " + where + ".";
  }
  if (entry.source) {
    const source = entry.source;
    const fed = source.controls.length;
    const list = fed ? " Feeds " + fed + (fed === 1 ? " control: " : " controls: ") + source.controls.join(", ") + "." : " No control reads it.";
    const newest = source.captured_at ? " Newest export " + dateWords(source.captured_at) + "." : " Never imported.";
    return source.name + ": " + source.state_text + "." + newest + list;
  }
  const control = entry.control;
  const names = new Map(data.sources.map((source) => [source.code, source.name]));
  const reads = control.sources.length
    ? " Reads " + control.sources.map((code) => names.get(code) || code).join(", ") + "."
    : " Manual evidence, no export.";
  const when = control.evidence_at ? " (" + dateWords(control.evidence_at) + ")" : "";
  return (
    control.control_id + " " + control.title.replace(/\.$/, "") + ", " + control.domain + ": " + control.label_text + ". Evidence " + control.evidence_state.toLowerCase() + when + "." + reads
  );
}

// The wall itself: built from the data once, drawn on demand, disposed whole.
function buildWall(THREE, root, data, options) {
  // The tables are on the page below the card, not inside it.
  const page = root.ownerDocument;
  const stage = root.querySelector("#explorer-stage");
  const detail = root.querySelector("#explorer-detail");
  const hover = root.querySelector("#explorer-hover");
  const tools = root.querySelector("#explorer-tools");
  const motionButton = root.querySelector("#explorer-motion");
  const controller = new AbortController();
  const signal = controller.signal;
  const companies = Boolean(data.companies);
  const plan = layout(data);
  // The order Left and Right step through in the companies ring: clients, then
  // controls.
  const entries = new Map();
  plan.sources.forEach((entry) => entries.set(entry.id, entry));
  plan.clients.forEach((entry) => entries.set(entry.id, entry));
  plan.controls.forEach((entry) => entries.set(entry.id, entry));
  // The inner ring of the companies grows with the clients (a step of 0.8 each),
  // never past the edge of the outer ring.
  const innerRadius = companies ? clamp((plan.clients.length * 0.8) / (2 * Math.PI), SOURCE_RADIUS, CONTROL_RADIUS - 1.3) : SOURCE_RADIUS;
  const idle = companies
    ? "Nothing selected. Choose an office or a tile, or Show in scene on a row below."
    : "Nothing selected. Choose a block or a tile, or Show in scene on a row below.";

  const canvas = document.createElement("canvas");
  // A focusable stage that answers keys is an application, not a still image.
  canvas.tabIndex = 0;
  canvas.setAttribute("role", "application");
  canvas.setAttribute("aria-roledescription", "scene");
  canvas.setAttribute(
    "aria-label",
    companies
      ? "The companies ring: " + plan.clients.length + " clients and " + plan.controls.length + " controls. Left and Right choose a client or a control, Enter opens it, Escape closes its card, the brackets turn the ring, plus and minus move closer and away, Home resets the view. The tables below carry the same facts."
      : "The evidence wall of " + data.client_name + ": " + data.sources.length + " evidence sources and " + data.controls.length + " controls. Left and Right turn it, plus and minus move closer and away, Home resets the view. The tables below carry the same facts."
  );
  canvas.setAttribute("aria-describedby", "explorer-detail");
  stage.insertBefore(canvas, stage.firstChild);

  const renderer = new THREE.WebGLRenderer({
    canvas,
    antialias: true,
    alpha: false,
    powerPreference: "low-power",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(GROUND, 1);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(36, 16 / 9, 0.1, 60);
  const target = new THREE.Vector3(0, 0.4, 0);
  const home = { yaw: HOME.yaw, pitch: HOME.pitch, distance: HOME.distance };
  const view = { yaw: home.yaw, pitch: home.pitch, distance: home.distance };

  scene.add(new THREE.HemisphereLight(0xffffff, GROUND, 1.4));
  const sun = new THREE.DirectionalLight(0xfff4e6, 2.2);
  sun.position.set(5, 11, 4);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  sun.shadow.radius = 4;
  sun.shadow.bias = -0.0008;
  sun.shadow.camera.left = -FLOOR_RADIUS;
  sun.shadow.camera.right = FLOOR_RADIUS;
  sun.shadow.camera.top = FLOOR_RADIUS;
  sun.shadow.camera.bottom = -FLOOR_RADIUS;
  sun.shadow.camera.near = 1;
  sun.shadow.camera.far = 40;
  scene.add(sun);
  const rim = new THREE.DirectionalLight(BEAM, 0.7);
  rim.position.set(-6, 5, -8);
  scene.add(rim);

  // The ground: a disc, the sector of each domain a step lighter or darker than the
  // next, a band for the sources, and two thin rings as the edges of the wall.
  const floor = new THREE.Mesh(
    new THREE.CircleGeometry(FLOOR_RADIUS, 72),
    new THREE.MeshStandardMaterial({ color: GROUND, roughness: 1 })
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -0.02;
  floor.receiveShadow = true;
  scene.add(floor);
  plan.sectors.forEach((sector) => {
    if (sector.length <= 0) {
      return;
    }
    const band = new THREE.Mesh(
      new THREE.RingGeometry(CONTROL_RADIUS - 0.55, CONTROL_RADIUS + 0.55, 24, 1, -sector.start - sector.length, sector.length),
      new THREE.MeshStandardMaterial({ color: sector.index % 2 ? SECTOR_ODD : SECTOR_EVEN, roughness: 1 })
    );
    band.rotation.x = -Math.PI / 2;
    band.position.y = -0.01;
    band.receiveShadow = true;
    scene.add(band);
  });
  const inner = new THREE.Mesh(
    new THREE.RingGeometry(innerRadius - 0.5, innerRadius + 0.5, 64),
    new THREE.MeshStandardMaterial({ color: SECTOR_EVEN, roughness: 1 })
  );
  inner.rotation.x = -Math.PI / 2;
  inner.position.y = -0.01;
  scene.add(inner);
  [innerRadius + 0.55, CONTROL_RADIUS - 0.62].forEach((radius) => {
    const points = [];
    for (let step = 0; step < 96; step += 1) {
      const a = (step / 96) * 2 * Math.PI;
      points.push(new THREE.Vector3(radius * Math.cos(a), 0.005, radius * Math.sin(a)));
    }
    const ring = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(points), new THREE.LineBasicMaterial({ color: LINE }));
    scene.add(ring);
  });

  // The pillars: an office block per export (office.js), as many floors as the
  // controls it feeds, full for a current export, low for a stale or expired one,
  // its roof light the state of the export; a source never imported is an empty
  // lot. Every material of a node is dimmed together.
  const pickables = [];
  const groups = new Map();
  plan.sources.forEach((entry, index) => {
    const strip = entry.source.state === "protected" ? STATUS_COLOR.protected : STATUS_COLOR[entry.source.state] || STONE;
    const built = officeBuilding(THREE, {
      width: 0.5,
      depth: 0.5,
      floors: Math.max(1, Math.round((entry.height - 0.24) / 0.2)),
      state: entry.missing ? "lot" : "built",
      strip,
      red: 0,
      seed: index + 7,
    });
    const group = built.group;
    group.userData.node = entry.id;
    group.position.set(SOURCE_RADIUS * Math.cos(entry.angle), 0, SOURCE_RADIUS * Math.sin(entry.angle));
    group.rotation.y = -entry.angle - Math.PI / 2;
    entry.group = group;
    entry.materials = built.materials;
    entry.top = new THREE.Vector3(group.position.x, built.top, group.position.z);
    scene.add(group);
    pickables.push(group);
    groups.set(entry.id, group);
  });

  // The offices of the companies ring: one per client, as on Home's street: as
  // many floors as its score allows, as wide as the company, its roof light the
  // band; in scaffolding with too little evidence for a score, an empty lot with
  // none, a red window per control that needs work. A crowded ring narrows every
  // office alike.
  const room = Math.min(1, ((2 * Math.PI * innerRadius) / Math.max(plan.clients.length, 1)) * 0.8 / 0.95);
  plan.clients.forEach((entry, index) => {
    const client = entry.client;
    const wide = 0.45 + 0.5 * clamp(Math.log10(client.size + 1) / Math.log10(501), 0, 1);
    const built = officeBuilding(THREE, {
      width: wide * room,
      depth: 0.62 * room,
      floors: client.evidence ? 2 + Math.round((client.score / 100) * 10) : 0,
      state: !client.evidence ? "lot" : client.insufficient ? "frame" : "built",
      strip: client.evidence ? BAND_LIGHT[client.band.toLowerCase()] || STATUS_COLOR["not-checked"] : LINE,
      red: Math.min(client.needsWork, 12),
      seed: index + 7,
    });
    const group = built.group;
    group.userData.node = entry.id;
    group.position.set(innerRadius * Math.cos(entry.angle), 0, innerRadius * Math.sin(entry.angle));
    group.rotation.y = -entry.angle - Math.PI / 2;
    entry.group = group;
    entry.materials = built.materials;
    entry.top = new THREE.Vector3(group.position.x, built.top, group.position.z);
    scene.add(group);
    pickables.push(group);
    groups.set(entry.id, group);
  });

  // The tiles: a flat tile for Protected, a ring on it for Needs attention, a cross
  // cut through it for Not protected, an outline for Not checked, a small disc for
  // Not applicable.
  plan.controls.forEach((entry) => {
    const label = entry.control.label;
    const color = STATUS_COLOR[label] || STATUS_COLOR["not-checked"];
    const glass = label === "not-checked";
    const material = new THREE.MeshStandardMaterial({
      color,
      roughness: glass ? 0.2 : 0.5,
      metalness: 0.05,
      transparent: true,
      opacity: glass ? 0.35 : 1,
      depthWrite: !glass,
    });
    material.userData.base = material.opacity;
    const group = new THREE.Group();
    group.userData.node = entry.id;
    if (label === "not-applicable") {
      const disc = new THREE.Mesh(new THREE.CylinderGeometry(0.13, 0.13, 0.05, 20), material);
      disc.position.y = 0.025;
      group.add(disc);
    } else {
      const shape = new THREE.BoxGeometry(0.46, 0.12, 0.46);
      const tile = new THREE.Mesh(shape, material);
      tile.position.y = 0.06;
      tile.castShadow = label !== "not-checked";
      tile.receiveShadow = true;
      group.add(tile);
      if (label === "not-checked") {
        const outline = new THREE.LineSegments(
          new THREE.EdgesGeometry(shape),
          new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.8 })
        );
        outline.position.y = 0.06;
        group.add(outline);
      }
    }
    if (label === "needs-attention") {
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.16, 0.035, 10, 32), material);
      ring.rotation.x = Math.PI / 2;
      ring.position.y = 0.15;
      group.add(ring);
    }
    if (label === "not-protected") {
      [Math.PI / 4, -Math.PI / 4].forEach((turn) => {
        const bar = new THREE.Mesh(new THREE.BoxGeometry(0.56, 0.08, 0.07), material);
        bar.rotation.y = turn;
        bar.position.y = 0.16;
        group.add(bar);
      });
    }
    group.position.set(CONTROL_RADIUS * Math.cos(entry.angle), 0, CONTROL_RADIUS * Math.sin(entry.angle));
    group.rotation.y = -entry.angle;
    entry.group = group;
    entry.materials = [material];
    entry.top = new THREE.Vector3(group.position.x, 0.14, group.position.z);
    scene.add(group);
    pickables.push(group);
    groups.set(entry.id, group);
  });

  // The beams: one curve per link, from the top of the pillar to the tile.
  const beams = [];
  plan.sources.forEach((entry) => {
    entry.source.controls.forEach((controlId) => {
      const other = entries.get("control:" + controlId);
      if (!other) {
        return;
      }
      const middle = entry.top.clone().add(other.top).multiplyScalar(0.5);
      middle.y = Math.max(entry.top.y, 1) + 0.7;
      const curve = new THREE.QuadraticBezierCurve3(entry.top, middle, other.top);
      const material = new THREE.LineBasicMaterial({ color: BEAM, transparent: true, opacity: BEAM_OPACITY });
      const beam = new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(24)), material);
      beam.userData.ends = [entry.id, other.id];
      scene.add(beam);
      beams.push(beam);
    });
  });

  // The links of the companies ring: a low arc from the roof of every client to
  // every control, in the status of that pair. Three materials per status are
  // shared by all its links (faint, lit, dimmed); a status filtered out is hidden.
  // shortcut: one Line per pair (51 per client); merge them per status if a
  // portfolio of hundreds of clients ever makes the ring slow.
  const looks = {};
  (companies ? LINKED : []).forEach((key) => {
    const made = (opacity) => new THREE.LineBasicMaterial({ color: STATUS_COLOR[key], transparent: true, opacity });
    looks[key] = { faint: made(LINK_OPACITY.faint), lit: made(LINK_OPACITY.lit), dim: made(LINK_OPACITY.dim) };
  });
  plan.controls.forEach((entry) => {
    (entry.control.pairs || []).forEach((pair) => {
      const office = entries.get(pair.client);
      if (!looks[pair.label] || !office) {
        return;
      }
      const middle = office.top.clone().add(entry.top).multiplyScalar(0.5);
      middle.y = Math.max(office.top.y, 1) + 0.5;
      const curve = new THREE.QuadraticBezierCurve3(office.top, middle, entry.top);
      const link = new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(16)), looks[pair.label].faint);
      link.userData.ends = [office.id, entry.id];
      link.userData.label = pair.label;
      scene.add(link);
      beams.push(link);
    });
  });
  const filters = Array.from(page.querySelectorAll(".rv-explorer-filter"));

  function applyFilters() {
    const shown = new Set(filters.filter((button) => button.getAttribute("aria-pressed") === "true").map((button) => button.getAttribute("data-status")));
    beams.forEach((beam) => {
      if (beam.userData.label) {
        beam.visible = shown.has(beam.userData.label);
      }
    });
  }

  // Drawing on demand.
  let rafId = 0;
  let needsRender = true;
  let lost = false;
  let hidden = document.hidden;
  let inView = true;
  let autoTurn = !options.reducedMotion;
  let lastFrame = 0;
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
    if (card) {
      card.place(camera);
    }
  }

  function turning() {
    return autoTurn && !hidden && inView && !lost;
  }

  function frame(now) {
    rafId = 0;
    const dt = lastFrame ? Math.min((now - lastFrame) / 1000, 0.1) : 0;
    lastFrame = now;
    if (turning()) {
      view.yaw += AUTO_TURN * dt;
      needsRender = true;
    }
    if (tween) {
      const t = clamp((now - tween.start) / TWEEN_MS, 0, 1);
      view.yaw = tween.from + (tween.to - tween.from) * easeOut(t);
      needsRender = true;
      if (t >= 1) {
        tween = null;
      }
    }
    if (needsRender && !lost) {
      render();
      needsRender = false;
    }
    if (turning() || tween) {
      schedule();
    } else {
      lastFrame = 0;
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

  // The home distance that fits the whole ring to the stage as it is shaped now:
  // the outer corners of the tiles and the roofs of the inner ring stay inside the
  // view with a little air, whichever way the ring has turned (it is round, so the
  // turn does not matter). A view a person moved closer or away keeps its own.
  const tallest = Math.max(0.5, ...plan.sources.concat(plan.clients).map((entry) => entry.top.y));
  const probes = [];
  for (let k = 0; k < 32; k += 1) {
    const a = (k / 32) * 2 * Math.PI;
    probes.push(new THREE.Vector3(FIT_RADIUS * Math.cos(a), 0, FIT_RADIUS * Math.sin(a)));
    probes.push(new THREE.Vector3(innerRadius * Math.cos(a), tallest, innerRadius * Math.sin(a)));
  }

  function fitDistance() {
    const kept = { yaw: view.yaw, pitch: view.pitch, distance: view.distance };
    const point = new THREE.Vector3();
    let distance = MIN_DISTANCE;
    for (; distance < MAX_DISTANCE * 2; distance *= 1.03) {
      Object.assign(view, { yaw: home.yaw, pitch: home.pitch, distance });
      placeCamera();
      camera.updateMatrixWorld();
      const inside = probes.every((probe) => {
        point.copy(probe).project(camera);
        return Math.abs(point.x) <= FIT_EDGE && Math.abs(point.y) <= FIT_EDGE;
      });
      if (inside) {
        break;
      }
    }
    Object.assign(view, kept);
    return distance;
  }

  function resize() {
    const width = Math.max(stage.clientWidth, 1);
    const height = Math.max(stage.clientHeight, 1);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    const atHome = Math.abs(view.distance - home.distance) < 0.001;
    home.distance = fitDistance();
    if (atHome) {
      view.distance = home.distance;
    }
    invalidate();
  }

  // Selection and hover: the materials of the chosen node and its beams come
  // forward, everything else steps back; the tables mirror the choice. A link a
  // filter hides brings nothing forward.
  function related(id) {
    const found = new Set([id]);
    beams.forEach((beam) => {
      if (beam.visible && beam.userData.ends.indexOf(id) >= 0) {
        beam.userData.ends.forEach((end) => found.add(end));
      }
    });
    return found;
  }

  function paint() {
    const focus = selected || hovered;
    const keep = focus ? related(focus) : null;
    entries.forEach((entry, id) => {
      const own = focus === id;
      entry.materials.forEach((material) => {
        const base = material.userData.base === undefined ? 1 : material.userData.base;
        material.opacity = !keep || keep.has(id) ? base : base * DIM;
        if (material.emissive) {
          material.emissive.setHex(own ? PICKED : material.userData.emissive || 0x000000);
          material.emissiveIntensity = own ? 0.35 : material.userData.emissiveIntensity || 0;
        }
      });
    });
    beams.forEach((beam) => {
      const on = focus && beam.userData.ends.indexOf(focus) >= 0;
      if (beam.userData.label) {
        const look = looks[beam.userData.label];
        beam.material = !focus ? look.faint : on ? look.lit : look.dim;
        return;
      }
      beam.material.color.setHex(on ? PICKED : BEAM);
      beam.material.opacity = !focus ? BEAM_OPACITY : on ? 0.95 : 0.08;
    });
    invalidate();
  }

  function markRows() {
    page.querySelectorAll("tr[data-node]").forEach((row) => {
      row.setAttribute("data-selected", row.getAttribute("data-node") === selected ? "true" : "false");
    });
    page.querySelectorAll(".rv-explorer-pick").forEach((button) => {
      button.setAttribute("aria-pressed", button.getAttribute("data-node") === selected ? "true" : "false");
    });
  }

  // The card of the chosen office or tile of the companies ring (scene-card.js);
  // the evidence wall has none. A press on the buttons under the stage (a filter,
  // a turn) leaves it open.
  const card = companies
    ? sceneCard({
        page,
        stage,
        canvas,
        signal,
        keep: tools,
        onKey,
        onClose: (refocus) => (refocus ? leave() : select(null, false)),
      })
    : null;

  // Closing the card with Escape or its button gives the canvas the focus back.
  function leave() {
    select(null, false);
    canvas.focus();
  }

  function select(id, face, keyed = false) {
    selected = entries.has(id) ? id : null;
    const entry = selected ? entries.get(selected) : null;
    words(detail, entry ? describe(entry, data) + (companies && entry.href ? " Press Enter to open it." : "") : idle);
    markRows();
    if (card && entry && entry.card) {
      card.open(entry.card, entry.top, camera, keyed);
    } else if (card) {
      card.close();
    }
    if (entry && face) {
      turnTo(Math.PI / 2 - entry.angle);
    }
    paint();
  }

  function setHover(id) {
    hovered = entries.has(id) ? id : null;
    words(hover, hovered ? describe(entries.get(hovered), data) : "");
    canvas.style.cursor = hovered ? "pointer" : "";
    paint();
  }

  function turnTo(yaw) {
    autoTurn = false;
    syncMotionButton();
    if (options.reducedMotion) {
      view.yaw = yaw;
      invalidate();
      return;
    }
    tween = { from: view.yaw, to: yaw, start: performance.now() };
    schedule();
  }

  function turnBy(delta) {
    turnTo(view.yaw + delta);
  }

  function zoomBy(factor) {
    view.distance = clamp(view.distance * factor, MIN_DISTANCE, Math.max(MAX_DISTANCE, home.distance * 1.3));
    invalidate();
  }

  function reset() {
    tween = null;
    view.yaw = home.yaw;
    view.pitch = home.pitch;
    view.distance = home.distance;
    autoTurn = !options.reducedMotion;
    syncMotionButton();
    select(null, false);
    invalidate();
  }

  // Left and Right of the companies ring: the next client, then the next control.
  function step(delta) {
    const ids = Array.from(entries.keys());
    if (!ids.length) {
      return;
    }
    const at = selected ? ids.indexOf(selected) : -1;
    const next = at < 0 ? (delta > 0 ? 0 : ids.length - 1) : (at + delta + ids.length) % ids.length;
    select(ids[next], true, true);
  }

  function open() {
    const entry = selected ? entries.get(selected) : null;
    if (entry && entry.href) {
      window.location.assign(entry.href);
    }
  }

  function syncMotionButton() {
    if (motionButton) {
      motionButton.setAttribute("aria-pressed", autoTurn ? "true" : "false");
    }
  }

  // Pointer: a drag turns and tilts the wall, a short press picks a node.
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
          autoTurn = false;
          syncMotionButton();
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
          select(pick(event), false);
        }
        press = null;
      }
    },
    { signal }
  );
  canvas.addEventListener(
    "pointercancel",
    () => {
      press = null;
    },
    { signal }
  );
  canvas.addEventListener(
    "pointerleave",
    () => {
      setHover(null);
    },
    { signal }
  );
  // The wall turns with Left and Right; the companies ring chooses with them, opens
  // the choice with Enter and turns with the brackets.
  function onKey(event) {
    const keys = {
      ArrowLeft: () => turnBy(-TURN_STEP),
      ArrowRight: () => turnBy(TURN_STEP),
      "+": () => zoomBy(0.85),
      "=": () => zoomBy(0.85),
      "-": () => zoomBy(1.18),
      Home: () => reset(),
      Escape: () => select(null, false),
    };
    if (companies) {
      Object.assign(keys, {
        ArrowLeft: () => step(-1),
        ArrowRight: () => step(1),
        "[": () => turnBy(-TURN_STEP),
        "]": () => turnBy(TURN_STEP),
        Enter: () => open(),
        Escape: () => leave(),
      });
    }
    const action = keys[event.key];
    if (action) {
      event.preventDefault();
      action();
    }
  }
  canvas.addEventListener("keydown", onKey, { signal });

  // The buttons under the stage and the rows of the tables.
  const buttons = {
    "#explorer-turn-left": () => turnBy(-TURN_STEP),
    "#explorer-turn-right": () => turnBy(TURN_STEP),
    "#explorer-reset": () => reset(),
  };
  Object.keys(buttons).forEach((selector) => {
    const button = root.querySelector(selector);
    if (button) {
      button.addEventListener("click", buttons[selector], { signal });
    }
  });
  filters.forEach((button) => {
    button.addEventListener(
      "click",
      () => {
        button.setAttribute("aria-pressed", button.getAttribute("aria-pressed") === "true" ? "false" : "true");
        applyFilters();
        paint();
      },
      { signal }
    );
  });
  if (motionButton) {
    motionButton.addEventListener(
      "click",
      () => {
        autoTurn = !options.reducedMotion && !autoTurn;
        syncMotionButton();
        schedule();
      },
      { signal }
    );
  }

  // The reduced-motion preference can change while the page is open: the wall then
  // stops (or may turn again) and the button follows.
  function applyMotion() {
    if (options.reducedMotion) {
      autoTurn = false;
      tween = null;
    }
    if (motionButton) {
      motionButton.hidden = options.reducedMotion;
    }
    syncMotionButton();
    invalidate();
  }
  page.querySelectorAll(".rv-explorer-pick").forEach((button) => {
    button.hidden = false;
    button.addEventListener(
      "click",
      () => {
        const id = button.getAttribute("data-node");
        select(selected === id ? null : id, true);
        canvas.focus({ preventScroll: true });
      },
      { signal }
    );
  });

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
  // default clear colour, black, so the wall's ground is set again (THE-1401).
  canvas.addEventListener(
    "webglcontextrestored",
    () => {
      lost = false;
      options.hideState();
      renderer.setClearColor(GROUND, 1);
      invalidate();
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

  function dispose() {
    controller.abort();
    watcher.disconnect();
    sizer.disconnect();
    if (rafId) {
      window.cancelAnimationFrame(rafId);
      rafId = 0;
    }
    if (card) {
      card.close();
    }
    // A link material that no link wears right now is not in the scene.
    Object.values(looks).forEach((look) => Object.values(look).forEach((material) => material.dispose()));
    scene.traverse(disposeObject);
    scene.clear();
    renderer.dispose();
    renderer.forceContextLoss();
    canvas.remove();
    page.querySelectorAll(".rv-explorer-pick").forEach((button) => {
      button.hidden = true;
      button.setAttribute("aria-pressed", "false");
    });
    page.querySelectorAll("tr[data-node]").forEach((row) => row.removeAttribute("data-selected"));
    if (tools) {
      tools.hidden = true;
    }
  }

  function info() {
    return {
      nodes: entries.size,
      beams: beams.length,
      geometries: renderer.info.memory.geometries,
      textures: renderer.info.memory.textures,
      programs: renderer.info.programs ? renderer.info.programs.length : 0,
      lost,
      turning: turning(),
    };
  }

  if (tools) {
    tools.hidden = false;
  }
  applyMotion();
  applyFilters();
  resize();
  paint();
  return { dispose, info, select, reset, applyMotion };
}

async function main() {
  const root = document.getElementById("explorer");
  if (!root) {
    return;
  }
  const state = root.querySelector("#explorer-state");
  const stateText = state ? state.querySelector(".rv-explorer-state-text") : null;
  const url = root.getAttribute("data-explorer-url");
  const companies = root.getAttribute("data-explorer-view") === "companies";
  const motionQuery = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;

  function setState(kind, message) {
    if (!state) {
      return;
    }
    state.hidden = false;
    state.classList.toggle("is-loading", kind === "loading");
    state.setAttribute("data-kind", kind);
    words(stateText, message);
  }

  function hideState() {
    if (state) {
      state.hidden = true;
      state.classList.remove("is-loading");
      state.removeAttribute("data-kind");
    }
  }

  if ((!url && !companies) || !supportsWebGL2()) {
    setState("note", WORDS.noWebgl);
    root.setAttribute("data-explorer", "no-webgl");
    return;
  }
  // The 3D view starts hidden, as the scenes of the other pages do, and shares
  // their choice in this browser; the tables below are the record either way.
  const toggle = root.querySelector("#explorer-toggle");
  let started = false;
  if (toggle) {
    toggle.hidden = false;
    toggle.addEventListener("click", () => {
      const api = root.revrookExplorer;
      if (api && api.info()) {
        api.dispose();
        rememberShown(false);
        words(toggle, "Show the 3D view");
        return;
      }
      rememberShown(true);
      words(toggle, "Hide the 3D view");
      if (api) {
        api.mount();
      } else if (!started) {
        started = true;
        start();
      }
    });
  }
  if (!scenesShown()) {
    setState("note", WORDS.off);
    root.setAttribute("data-explorer", "off");
    return;
  }
  started = true;
  if (toggle) {
    words(toggle, "Hide the 3D view");
  }
  await start();

  async function start() {
  setState("loading", WORDS.loading);
  root.setAttribute("data-explorer", "loading");

  let data;
  let THREE;
  try {
    data = companies ? readCompanies(document) : await loadData(url);
  } catch (error) {
    setState("error", error && error.message ? error.message : WORDS.session);
    root.setAttribute("data-explorer", "error");
    return;
  }
  if (!data.sources.length && !data.controls.length) {
    setState("note", WORDS.empty);
    root.setAttribute("data-explorer", "empty");
    return;
  }
  try {
    THREE = await import(THREE_URL);
    ({ officeBuilding } = await import(OFFICE_URL));
    if (companies) {
      ({ sceneCard } = await import(CARD_URL));
    }
  } catch (error) {
    setState("error", WORDS.noModule);
    root.setAttribute("data-explorer", "error");
    return;
  }

  let wall = null;
  const options = { reducedMotion: Boolean(motionQuery && motionQuery.matches), setState, hideState };
  if (motionQuery) {
    motionQuery.addEventListener("change", (event) => {
      options.reducedMotion = event.matches;
      if (wall) {
        wall.applyMotion();
      }
    });
  }

  function mount() {
    if (wall) {
      return wall;
    }
    wall = buildWall(THREE, root, data, options);
    hideState();
    root.setAttribute("data-explorer", "ready");
    return wall;
  }

  function dispose() {
    if (wall) {
      wall.dispose();
      wall = null;
      setState("note", WORDS.closed);
      root.setAttribute("data-explorer", "disposed");
    }
  }

  try {
    mount();
  } catch (error) {
    setState("error", WORDS.noModule);
    root.setAttribute("data-explorer", "error");
    return;
  }

  root.revrookExplorer = {
    mount,
    dispose,
    info: () => (wall ? wall.info() : null),
    select: (id) => (wall ? wall.select(id, true) : undefined),
    get reducedMotion() {
      return options.reducedMotion;
    },
  };
  // Leaving the page frees the graphics context; a page the browser keeps in its
  // back-forward cache draws the wall again when it is shown.
  window.addEventListener("pagehide", dispose);
  window.addEventListener("pageshow", (event) => {
    if (event.persisted && scenesShown()) {
      mount();
    }
  });
  }
}

main();
