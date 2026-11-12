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
 *   or a tile opens its card (scene-card.js), a template the server drew, and
 *   frames it with its links while everything else fades.
 *   The links are thin tubes bundled per domain (each rises from its office to a
 *   point above its domain's sector, then falls to its tile), the domains stand
 *   apart on tinted ground, and small dots flow along the not protected links
 *   unless motion is reduced. The names of the clients and the domains stand over
 *   the scene in an aria-hidden overlay: the tables carry the same facts.
 * Status is shape and colour together, never colour alone, and every word is in the
 * DOM (the detail line, the legend, the tables, the cards, the name overlay):
 * nothing is drawn as text inside the canvas.
 *
 * Each of these leaves the tables intact and says so in the stage:
 * - no WebGL 2: the note the server rendered stays, no import happens;
 * - the data cannot be read (a session that ended, a refused client, a failure): a
 *   note says what happened and what to do;
 * - a lost graphics context: drawing stops, the note says so, drawing resumes when
 *   the browser restores the context;
 * - prefers-reduced-motion: the wall never turns by itself and every move is
 *   immediate; otherwise it turns slowly until the person touches it.
 * Frames are drawn only when something changed, the wall is turning or dots flow
 * (at most about 30 a second for the flow alone), and never while the page is
 * hidden or the stage is out of view. Leaving the page disposes every geometry,
 * material, texture, the environment map, the name overlay and the renderer;
 * root.revrookExplorer exposes dispose,
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

// The finish of the companies ring: domain sectors a step apart on two quiet tints
// (never a status colour), links as thin tubes, dots and a glow in the not
// protected red.
const SECTOR_TINT = [0x323856, 0x2b3c46];
const TUBE_RADIUS = 0.016;
const TUBE_SEGMENTS = 20;
const TUBE_SIDES = 4;
const FLOW_DOTS = 2; // per not protected link
const FLOW_SPEED = 0.3; // of a link per second
const FLOW_FRAME_MS = 30; // the flow alone draws about 30 frames a second
const FLOW_COLOR = 0xffd6d1;
const FOCUS_MS = 600;
const FOCUS_PITCH = 0.82;
const FOCUS_EDGE = 0.8;
// A label hides when it covers this share of a label already placed.
const LABEL_OVERLAP = 0.1;

const SOURCE_RADIUS = 2.4;
const CONTROL_RADIUS = 5.3;
const FLOOR_RADIUS = 6.6;
const SECTOR_GAP = 0.07;
const COMPANY_GAP = 0.14;
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
      domainName: row.getAttribute("data-domain-name") || "",
      label: row.getAttribute("data-label") || "not-checked",
      href: row.getAttribute("data-href") || "",
      pairs: items.map((item) => ({ client: "client:" + item.getAttribute("data-client"), label: item.getAttribute("data-label") || "" })),
    };
  });
  // The domains in the order of the table, each with the name its sector shows.
  const domains = [];
  controls.forEach((control) => {
    if (!domains.some((domain) => domain.code === control.domain)) {
      domains.push({ code: control.domain, name: control.domainName || control.domain });
    }
  });
  return { companies: true, clients, controls, domains, sources: [] };
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
  const names = new Map(data.domains.map((domain) => [domain.code, domain.name]));
  // The companies ring sets its domains clearly apart; the wall keeps its own gap.
  const gap = data.companies ? COMPANY_GAP : SECTOR_GAP;
  const byDomain = new Map(codes.map((code) => [code, []]));
  for (const control of data.controls) {
    if (!byDomain.has(control.domain)) {
      codes.push(control.domain);
      byDomain.set(control.domain, []);
    }
    byDomain.get(control.domain).push(control);
  }
  const total = data.controls.length;
  const per = total ? (2 * Math.PI - gap * codes.length) / total : 0;
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
    sectors.push({ code, name: names.get(code) || code, start, length: members.length * per, index });
    angle += gap;
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

// A soft white spot drawn into a small canvas: the glow of a not protected tile and
// the flowing dots, tinted by their materials and added to the light behind them.
function glowTexture(THREE) {
  const art = document.createElement("canvas");
  art.width = 64;
  art.height = 64;
  const pen = art.getContext("2d");
  const fill = pen.createRadialGradient(32, 32, 0, 32, 32, 32);
  fill.addColorStop(0, "rgba(255, 255, 255, 1)");
  fill.addColorStop(0.3, "rgba(255, 255, 255, 0.5)");
  fill.addColorStop(1, "rgba(255, 255, 255, 0)");
  pen.fillStyle = fill;
  pen.fillRect(0, 0, 64, 64);
  return new THREE.CanvasTexture(art);
}

// The light the materials reflect, built in code instead of read from a file: a
// dim room with a few bright panels, blurred once into a small environment map.
// The room is freed at once; the caller disposes the map it returns.
function environmentMap(THREE, renderer) {
  const room = new THREE.Scene();
  const box = new THREE.BoxGeometry(1, 1, 1);
  const made = [];
  const add = (color, strength, position, scale, side = THREE.FrontSide) => {
    const material = new THREE.MeshBasicMaterial({ color, side });
    material.color.multiplyScalar(strength);
    made.push(material);
    const mesh = new THREE.Mesh(box, material);
    mesh.position.set(...position);
    mesh.scale.set(...scale);
    room.add(mesh);
  };
  add(GROUND, 1, [0, 0, 0], [24, 24, 24], THREE.BackSide);
  add(0xffffff, 3, [0, 10, 0], [10, 0.2, 10]);
  add(0xfff1dc, 2.2, [-10, 4, 3], [0.2, 5, 9]);
  add(BEAM, 1.6, [9, 3, -7], [0.2, 4, 7]);
  const pmrem = new THREE.PMREMGenerator(renderer);
  const target = pmrem.fromScene(room, 0.04);
  pmrem.dispose();
  box.dispose();
  made.forEach((material) => material.dispose());
  return target;
}

// Many tubes as one geometry: their positions and indices joined, and a colour per
// vertex whose alpha is the opacity of the link it belongs to (set by paint()).
// Each tube is freed once copied.
function mergeTubes(THREE, tubes) {
  let vertices = 0;
  let indices = 0;
  tubes.forEach((tube) => {
    vertices += tube.attributes.position.count;
    indices += tube.index.count;
  });
  const position = new Float32Array(vertices * 3);
  const index = new Uint32Array(indices);
  let v = 0;
  let i = 0;
  tubes.forEach((tube) => {
    position.set(tube.attributes.position.array, v * 3);
    tube.index.array.forEach((value, k) => {
      index[i + k] = value + v;
    });
    v += tube.attributes.position.count;
    i += tube.index.count;
    tube.dispose();
  });
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(position, 3));
  geometry.setAttribute("color", new THREE.BufferAttribute(new Float32Array(vertices * 4).fill(1), 4));
  geometry.setIndex(new THREE.BufferAttribute(index, 1));
  return geometry;
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
  // r186 draws soft shadows with PCF and the shadow radius (PCFSoftShadowMap is
  // gone). Nothing in the scene moves, so the shadow map is drawn once, not on
  // every frame; a restored context draws it again.
  renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.shadowMap.autoUpdate = false;
  renderer.shadowMap.needsUpdate = true;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(36, 16 / 9, 0.1, 60);
  const center = new THREE.Vector3(0, 0.4, 0);
  const target = center.clone();
  const home = { yaw: HOME.yaw, pitch: HOME.pitch, distance: HOME.distance };
  const view = { yaw: home.yaw, pitch: home.pitch, distance: home.distance };

  // The companies ring reflects a room built in code and fades into the ground at
  // its far rim; the wall keeps its plain light.
  let environment = companies ? environmentMap(THREE, renderer) : null;
  if (environment) {
    scene.environment = environment.texture;
    scene.environmentIntensity = 0.55;
    scene.fog = new THREE.Fog(GROUND, 14, 34);
  }
  scene.add(new THREE.HemisphereLight(0xffffff, GROUND, companies ? 1 : 1.4));
  const sun = new THREE.DirectionalLight(0xfff4e6, 2.2);
  sun.position.set(5, 11, 4);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  sun.shadow.radius = 3;
  sun.shadow.bias = -0.0005;
  sun.shadow.normalBias = 0.02;
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
  // The companies ring widens each band outwards, where its domain's name stands,
  // and tints it so a domain reads as one group.
  plan.sectors.forEach((sector) => {
    if (sector.length <= 0) {
      return;
    }
    const tint = companies ? SECTOR_TINT[sector.index % 2] : sector.index % 2 ? SECTOR_ODD : SECTOR_EVEN;
    const band = new THREE.Mesh(
      new THREE.RingGeometry(CONTROL_RADIUS - 0.55, CONTROL_RADIUS + (companies ? 1.05 : 0.55), 24, 1, -sector.start - sector.length, sector.length),
      new THREE.MeshStandardMaterial({ color: tint, roughness: 1 })
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

  const glow = companies ? glowTexture(THREE) : null;

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
    entry.materials = [material];
    // On the companies ring a not protected tile glows softly: an additive sprite
    // that dims with its tile and is never picked.
    if (glow && label === "not-protected") {
      const shine = new THREE.SpriteMaterial({
        map: glow,
        color,
        transparent: true,
        opacity: 0.35,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        fog: true,
      });
      shine.userData.base = shine.opacity;
      const sprite = new THREE.Sprite(shine);
      sprite.scale.set(0.95, 0.95, 1);
      sprite.position.y = 0.14;
      sprite.raycast = () => {};
      group.add(sprite);
      entry.materials.push(shine);
    }
    group.position.set(CONTROL_RADIUS * Math.cos(entry.angle), 0, CONTROL_RADIUS * Math.sin(entry.angle));
    group.rotation.y = -entry.angle;
    entry.group = group;
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

  // The links of the companies ring: a thin tube from the roof of every client to
  // every control, in the status of that pair. Each rises to the hub of its
  // control's domain, a point above that sector, and falls from there to its tile,
  // so the links of a domain travel together. The tubes of a status are one mesh
  // (one draw for all of them); the alpha of each link's vertices says whether it
  // is faint, lit, dimmed or gone, and a status filtered out hides its mesh.
  const tallest = Math.max(0.5, ...plan.sources.concat(plan.clients).map((entry) => entry.top.y));
  const hubs = new Map(
    (companies ? plan.sectors : []).map((sector) => {
      const angle = sector.start + sector.length / 2;
      const radius = innerRadius + (CONTROL_RADIUS - innerRadius) * 0.62;
      return [sector.code, new THREE.Vector3(radius * Math.cos(angle), Math.max(1.2, tallest * 0.6 + 0.6), radius * Math.sin(angle))];
    })
  );
  const links = [];
  const bundles = {};
  const tubes = {};
  plan.controls.forEach((entry) => {
    (entry.control.pairs || []).forEach((pair) => {
      const office = entries.get(pair.client);
      if (LINKED.indexOf(pair.label) < 0 || !office) {
        return;
      }
      const curve = new THREE.CatmullRomCurve3([office.top, hubs.get(entry.control.domain), entry.top], false, "centripetal");
      const tube = new THREE.TubeGeometry(curve, TUBE_SEGMENTS, TUBE_RADIUS, TUBE_SIDES, false);
      const count = tube.attributes.position.count;
      tubes[pair.label] = tubes[pair.label] || [];
      links.push({
        ends: [office.id, entry.id],
        label: pair.label,
        // Every tube has as many vertices, so a link's place follows from its rank.
        start: tubes[pair.label].length * count,
        count,
        alpha: 1,
        // The path the dots of a not protected link follow, client to control.
        path: pair.label === "not-protected" ? curve.getSpacedPoints(32) : null,
        phase: (links.length * 0.618) % 1,
      });
      tubes[pair.label].push(tube);
    });
  });
  Object.keys(tubes).forEach((key) => {
    const geometry = mergeTubes(THREE, tubes[key]);
    const mesh = new THREE.Mesh(
      geometry,
      new THREE.MeshBasicMaterial({ color: STATUS_COLOR[key], vertexColors: true, transparent: true, depthWrite: false })
    );
    scene.add(mesh);
    bundles[key] = { mesh, alpha: geometry.attributes.color };
  });

  // The flow: small bright dots along the not protected links, client to control,
  // only while that filter shows them and motion is not reduced.
  const flowLinks = links.filter((link) => link.path);
  let flow = null;
  if (flowLinks.length) {
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(flowLinks.length * FLOW_DOTS * 3), 3));
    const points = new THREE.Points(
      geometry,
      new THREE.PointsMaterial({
        color: FLOW_COLOR,
        map: glow,
        size: 0.26,
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      })
    );
    points.frustumCulled = false;
    points.visible = false;
    scene.add(points);
    flow = { points, active: [] };
  }
  const filters = Array.from(page.querySelectorAll(".rv-explorer-filter"));
  let shown = new Set();

  function applyFilters() {
    shown = new Set(filters.filter((button) => button.getAttribute("aria-pressed") === "true").map((button) => button.getAttribute("data-status")));
    Object.keys(bundles).forEach((key) => {
      bundles[key].mesh.visible = shown.has(key);
    });
  }

  function setAlpha(link, alpha) {
    if (link.alpha === alpha) {
      return;
    }
    link.alpha = alpha;
    const bundle = bundles[link.label];
    for (let k = link.start; k < link.start + link.count; k += 1) {
      bundle.alpha.array[k * 4 + 3] = alpha;
    }
    bundle.alpha.needsUpdate = true;
  }

  function flowing() {
    return Boolean(flow && flow.active.length) && !options.reducedMotion;
  }

  // The dots at time `now`: FLOW_DOTS per active link, evenly spaced along it.
  function moveFlow(now) {
    if (!flow) {
      return;
    }
    flow.points.visible = flowing();
    if (!flow.points.visible) {
      return;
    }
    const position = flow.points.geometry.attributes.position;
    let n = 0;
    flow.active.forEach((link) => {
      for (let k = 0; k < FLOW_DOTS; k += 1) {
        const along = (((now / 1000) * FLOW_SPEED + link.phase + k / FLOW_DOTS) % 1) * (link.path.length - 1);
        const at = Math.floor(along);
        const a = link.path[at];
        const b = link.path[Math.min(at + 1, link.path.length - 1)];
        const t = along - at;
        position.setXYZ(n, a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t, a.z + (b.z - a.z) * t);
        n += 1;
      }
    });
    position.needsUpdate = true;
    flow.points.geometry.setDrawRange(0, n);
  }

  // The names over the companies ring: an overlay of plain elements inside the
  // stage (aria-hidden: the tables say the same), a client's name and score over
  // its roof and a domain's name on the floor of its sector, moved to where the
  // camera sees them on every frame drawn. Its background is the vignette of the
  // rim.
  const labels = [];
  let overlay = null;
  if (companies) {
    overlay = document.createElement("div");
    overlay.className = "rv-explorer-labels";
    overlay.setAttribute("aria-hidden", "true");
    const label = (anchor, kind, name, extra, id) => {
      const element = document.createElement("span");
      element.className = "rv-explorer-label " + kind;
      const strong = document.createElement("span");
      strong.className = "rv-explorer-label-name";
      strong.textContent = name;
      element.appendChild(strong);
      if (extra) {
        const small = document.createElement("span");
        small.className = "rv-explorer-label-extra";
        small.textContent = extra;
        element.appendChild(small);
      }
      overlay.appendChild(element);
      labels.push({ element, anchor, id, domain: kind === "is-domain", width: 0, height: 0 });
    };
    plan.clients.forEach((entry) => {
      const client = entry.client;
      const score = !client.evidence ? "no evidence" : client.insufficient ? "at least " + client.scoreText : client.scoreText;
      label(entry.top.clone().setY(entry.top.y + 0.2), "is-client", client.name, score, entry.id);
    });
    plan.sectors.forEach((sector) => {
      const angle = sector.start + sector.length / 2;
      const radius = CONTROL_RADIUS + 0.8;
      label(new THREE.Vector3(radius * Math.cos(angle), 0, radius * Math.sin(angle)), "is-domain", sector.name, "", "");
    });
    canvas.after(overlay);
  }

  // Each label at its point, unless it is behind the camera or would cover much of
  // one already placed: the chosen one first, then the clients nearest first, then
  // the domains. Sizes are measured once (and again after a resize).
  const projected = new THREE.Vector3();
  let measured = false;

  function measureLabels() {
    if (!measured) {
      labels.forEach((item) => {
        item.width = item.element.offsetWidth;
        item.height = item.element.offsetHeight;
      });
      measured = labels.every((item) => item.width > 0);
    }
  }

  // The middle of the ring on the stage, in pixels.
  function ringMiddle(width, height) {
    projected.set(0, 0, 0).project(camera);
    return { x: ((projected.x + 1) / 2) * width, y: ((1 - projected.y) / 2) * height };
  }

  // Where a label stands on the stage before it is kept inside it: a client's chip
  // just over its point, a domain's name leaning away from the middle of the ring,
  // off its tiles. Also used to fit the home view, so every name has room.
  function labelBox(item, width, height, middle) {
    projected.copy(item.anchor).project(camera);
    let x = ((projected.x + 1) / 2) * width;
    let y = ((1 - projected.y) / 2) * height;
    if (item.domain) {
      const out = Math.hypot(x - middle.x, y - middle.y) || 1;
      x += ((x - middle.x) / out) * (item.width / 2);
      y += ((y - middle.y) / out) * (item.height / 2) + item.height / 2;
    }
    return { left: x - item.width / 2, top: y - item.height, z: projected.z };
  }

  function placeLabels() {
    if (!overlay) {
      return;
    }
    const width = stage.clientWidth;
    const height = stage.clientHeight;
    measureLabels();
    const middle = ringMiddle(width, height);
    labels.forEach((item) => {
      const box = labelBox(item, width, height, middle);
      item.behind = box.z > 1 || box.z < -1;
      item.depth = box.z;
      item.left = clamp(box.left, 4, Math.max(4, width - item.width - 4));
      item.top = clamp(box.top, 4, Math.max(4, height - item.height - 4));
    });
    const focus = selected || hovered;
    const order = labels.slice().sort((a, b) => (b.id === focus) - (a.id === focus) || a.domain - b.domain || a.depth - b.depth);
    const placed = [];
    order.forEach((item) => {
      const crowded = placed.some((other) => {
        const across = Math.min(item.left + item.width, other.left + other.width) - Math.max(item.left, other.left);
        const down = Math.min(item.top + item.height, other.top + other.height) - Math.max(item.top, other.top);
        return across > 0 && down > 0 && across * down > LABEL_OVERLAP * Math.min(item.width * item.height, other.width * other.height);
      });
      const show = !item.behind && !crowded;
      item.element.classList.toggle("is-hidden", !show);
      if (show) {
        placed.push(item);
        item.element.style.transform = "translate(" + Math.round(item.left) + "px, " + Math.round(item.top) + "px)";
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
  let lastDraw = 0;
  let tween = null;
  let selected = null;
  let hovered = null;
  // Whether the camera has left the whole ring to frame a chosen node.
  let focused = false;

  function placeCamera() {
    const flat = Math.cos(view.pitch) * view.distance;
    camera.position.set(
      target.x + flat * Math.sin(view.yaw),
      target.y + Math.sin(view.pitch) * view.distance,
      target.z + flat * Math.cos(view.yaw)
    );
    camera.lookAt(target);
    if (scene.fog) {
      // The far rim fades into the ground wherever the camera stands.
      scene.fog.near = view.distance;
      scene.fog.far = view.distance + 20;
    }
  }

  function render(now) {
    placeCamera();
    moveFlow(now);
    renderer.render(scene, camera);
    if (card) {
      card.place(camera);
    }
    placeLabels();
  }

  function live() {
    return !hidden && inView && !lost;
  }

  function turning() {
    return autoTurn && live();
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
      const t = clamp((now - tween.start) / tween.ms, 0, 1);
      const eased = easeOut(t);
      view.yaw = tween.from.yaw + (tween.to.yaw - tween.from.yaw) * eased;
      view.pitch = tween.from.pitch + (tween.to.pitch - tween.from.pitch) * eased;
      view.distance = tween.from.distance + (tween.to.distance - tween.from.distance) * eased;
      target.lerpVectors(tween.from.target, tween.to.target, eased);
      needsRender = true;
      if (t >= 1) {
        tween = null;
      }
    }
    // The flow alone draws about 30 frames a second.
    if (flowing() && live() && now - lastDraw >= FLOW_FRAME_MS) {
      needsRender = true;
    }
    if (needsRender && !lost) {
      render(now);
      lastDraw = now;
      needsRender = false;
    }
    if (turning() || tween || (flowing() && live())) {
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
  // turn does not matter). The companies ring also keeps the hubs of its links, its
  // outer ground bands, the rim of its floor and every name inside the view, and
  // is lifted so it stands in the middle of the stage. A view a person moved
  // closer or away keeps its own.
  const probes = Array.from(hubs.values());
  for (let k = 0; k < 32; k += 1) {
    const a = (k / 32) * 2 * Math.PI;
    probes.push(new THREE.Vector3(FIT_RADIUS * Math.cos(a), 0, FIT_RADIUS * Math.sin(a)));
    probes.push(new THREE.Vector3(innerRadius * Math.cos(a), tallest, innerRadius * Math.sin(a)));
    if (companies) {
      probes.push(new THREE.Vector3(FLOOR_RADIUS * Math.cos(a), 0, FLOOR_RADIUS * Math.sin(a)));
    }
  }
  const LABEL_EDGE = 6;

  // The top and the bottom of what `points` and the names cover, in the height of
  // the view (-1 at the foot of the stage, 1 at its head).
  function extent(points, named) {
    camera.updateMatrixWorld();
    const point = new THREE.Vector3();
    const span = { low: Infinity, high: -Infinity, wide: 0 };
    points.forEach((probe) => {
      point.copy(probe).project(camera);
      span.low = Math.min(span.low, point.y);
      span.high = Math.max(span.high, point.y);
      span.wide = Math.max(span.wide, Math.abs(point.x));
    });
    if (named) {
      const width = Math.max(stage.clientWidth, 1);
      const height = Math.max(stage.clientHeight, 1);
      const middle = ringMiddle(width, height);
      labels.forEach((item) => {
        const box = labelBox(item, width, height, middle);
        span.high = Math.max(span.high, 1 - (2 * (box.top - LABEL_EDGE)) / height);
        span.low = Math.min(span.low, 1 - (2 * (box.top + item.height + LABEL_EDGE)) / height);
        // Sideways a name counts whole, unless the names cannot all fit beside the
        // ring (a phone): then only its point counts and placeLabels keeps it in.
        if (named === "boxes") {
          span.wide = Math.max(span.wide, (2 * (width / 2 - box.left + LABEL_EDGE)) / width, (2 * (box.left + item.width + LABEL_EDGE - width / 2)) / width);
        } else {
          span.wide = Math.max(span.wide, Math.abs(projected.copy(item.anchor).project(camera).x));
        }
      });
    }
    return span;
  }

  // The least distance at which every point (and with `pose.named` every name)
  // stands inside `edge` of the stage, seen from `pose` (its yaw, pitch and the
  // point the camera looks at). With `pose.lift` the height of that point is
  // chosen too, so what is seen stands in the middle of the stage; it is written
  // back to `pose.target`.
  function fitDistance(points, pose, edge) {
    const kept = { yaw: view.yaw, pitch: view.pitch, distance: view.distance };
    const keptTarget = target.clone();
    target.copy(pose.target);
    if (pose.named) {
      measureLabels();
    }
    const middleAt = (height) => {
      target.y = height;
      placeCamera();
      const span = extent(points, pose.named);
      return (span.low + span.high) / 2;
    };
    let distance = MIN_DISTANCE;
    for (; distance < MAX_DISTANCE * 2; distance *= 1.03) {
      Object.assign(view, { yaw: pose.yaw, pitch: pose.pitch, distance });
      if (pose.lift) {
        // The middle moves almost evenly with the height: two secant steps.
        let low = pose.target.y - 1;
        let high = pose.target.y;
        for (let step = 0; step < 2; step += 1) {
          const a = middleAt(low);
          const b = middleAt(high);
          const next = Math.abs(b - a) < 1e-6 ? high : high - (b * (high - low)) / (b - a);
          low = high;
          high = next;
        }
        target.y = high;
      }
      placeCamera();
      const span = extent(points, pose.named);
      if (span.wide <= edge && span.high <= edge && span.low >= -edge) {
        break;
      }
    }
    if (pose.lift) {
      pose.target.y = target.y;
    }
    Object.assign(view, kept);
    target.copy(keptTarget);
    placeCamera();
    return distance;
  }

  function resize() {
    const width = Math.max(stage.clientWidth, 1);
    const height = Math.max(stage.clientHeight, 1);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    const atHome = !focused && Math.abs(view.distance - home.distance) < 0.001 && target.equals(center);
    measured = false;
    const pose = { yaw: home.yaw, pitch: home.pitch, target: center, lift: companies, named: companies ? "boxes" : false };
    home.distance = fitDistance(probes, pose, FIT_EDGE);
    if (companies && home.distance >= MAX_DISTANCE * 2) {
      // The names cannot all fit beside the ring (a phone): fit their points instead.
      pose.named = "anchors";
      home.distance = fitDistance(probes, pose, FIT_EDGE);
    }
    if (atHome) {
      view.distance = home.distance;
      target.copy(center);
    }
    invalidate();
  }

  // Selection and hover: the materials of the chosen node and its links come
  // forward, everything else steps back; the tables mirror the choice. A link a
  // filter hides brings nothing forward.
  function related(id) {
    const found = new Set([id]);
    beams.forEach((beam) => {
      if (beam.userData.ends.indexOf(id) >= 0) {
        beam.userData.ends.forEach((end) => found.add(end));
      }
    });
    links.forEach((link) => {
      if (shown.has(link.label) && link.ends.indexOf(id) >= 0) {
        link.ends.forEach((end) => found.add(end));
      }
    });
    return found;
  }

  // A chosen node fades everything it is not linked to and shows only its own
  // links; a hovered one dims the rest. The flow follows the links that show.
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
      beam.material.color.setHex(on ? PICKED : BEAM);
      beam.material.opacity = !focus ? BEAM_OPACITY : on ? 0.95 : 0.08;
    });
    links.forEach((link) => {
      const on = focus && link.ends.indexOf(focus) >= 0;
      setAlpha(link, !focus ? LINK_OPACITY.faint : on ? LINK_OPACITY.lit : selected ? 0 : LINK_OPACITY.dim);
    });
    if (flow) {
      flow.active = shown.has("not-protected") ? flowLinks.filter((link) => !selected || link.ends.indexOf(selected) >= 0) : [];
    }
    labels.forEach((item) => {
      item.element.classList.toggle("is-chosen", Boolean(focus) && item.id === focus);
      item.element.classList.toggle("is-faded", Boolean(keep) && !item.domain && !keep.has(item.id));
    });
    invalidate();
  }

  // The camera glides to `pose` (any of yaw, pitch, distance and target), the
  // shorter way round; under reduced motion it is there at once.
  function glide(pose, ms) {
    autoTurn = false;
    syncMotionButton();
    const to = {
      yaw: pose.yaw === undefined ? view.yaw : view.yaw + Math.atan2(Math.sin(pose.yaw - view.yaw), Math.cos(pose.yaw - view.yaw)),
      pitch: pose.pitch === undefined ? view.pitch : pose.pitch,
      distance: pose.distance === undefined ? view.distance : pose.distance,
      target: pose.target ? pose.target.clone() : target.clone(),
    };
    if (options.reducedMotion) {
      tween = null;
      Object.assign(view, { yaw: to.yaw, pitch: to.pitch, distance: to.distance });
      target.copy(to.target);
      invalidate();
      return;
    }
    tween = { from: { yaw: view.yaw, pitch: view.pitch, distance: view.distance, target: target.clone() }, to, start: performance.now(), ms };
    schedule();
  }

  // Focus on the companies ring: the camera faces the chosen node and frames it
  // with the nodes its shown links reach; no choice glides back to the whole ring.
  function frameChoice(entry) {
    if (!entry) {
      if (focused) {
        focused = false;
        glide({ pitch: home.pitch, distance: home.distance, target: center }, FOCUS_MS);
      }
      return;
    }
    const points = [];
    const middle = new THREE.Vector3();
    const near = related(entry.id);
    near.forEach((id) => {
      const other = entries.get(id);
      points.push(other.top, other.group.position);
      middle.add(other.top);
    });
    middle.divideScalar(near.size).lerp(center, 0.35).setY(center.y);
    const pose = { yaw: Math.PI / 2 - entry.angle, pitch: FOCUS_PITCH, target: middle };
    pose.distance = Math.min(fitDistance(points, pose, FOCUS_EDGE), home.distance);
    focused = true;
    glide(pose, FOCUS_MS);
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
    if (companies) {
      frameChoice(entry);
    } else if (entry && face) {
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
    glide({ yaw }, TWEEN_MS);
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
    focused = false;
    target.copy(center);
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
      // A glide under way ends where it was going; the flow stops at the next frame.
      if (tween) {
        Object.assign(view, { yaw: tween.to.yaw, pitch: tween.to.pitch, distance: tween.to.distance });
        target.copy(tween.to.target);
        tween = null;
      }
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
      // The shadow map and the environment map were drawn into the lost context.
      renderer.shadowMap.needsUpdate = true;
      if (environment) {
        environment.dispose();
        environment = environmentMap(THREE, renderer);
        scene.environment = environment.texture;
      }
      measured = false;
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
    // Every geometry, material and map in the scene (the merged links, the flow,
    // the glow sprites and their canvas texture among them), then the environment
    // map, which no object holds, and the name overlay.
    scene.traverse(disposeObject);
    scene.clear();
    if (glow) {
      glow.dispose();
    }
    if (environment) {
      environment.dispose();
      environment = null;
      scene.environment = null;
    }
    if (overlay) {
      overlay.remove();
      overlay = null;
      labels.length = 0;
    }
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
      links: links.length,
      labels: labels.length,
      flowing: flowing() && live(),
      dots: flow && flow.points.visible ? flow.points.geometry.drawRange.count : 0,
      geometries: renderer.info.memory.geometries,
      textures: renderer.info.memory.textures,
      programs: renderer.info.programs ? renderer.info.programs.length : 0,
      // Frames drawn so far: a test reads it twice to see that an idle scene draws none.
      frames: renderer.info.render.frame,
      // How far the ring (its floor rim, bands, roofs, hubs) and its names reach
      // in the view as it stands, -1 to 1: inside the stage when within those;
      // with the names whole, and with only their points sideways.
      extent: extent(probes, companies ? "boxes" : false),
      reach: extent(probes, companies ? "anchors" : false),
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
