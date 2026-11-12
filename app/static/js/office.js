/*
 * The office buildings of the revrook scenes. Shared by the street of Home
 * (scenes.js: one office per client) and the Evidence Explorer
 * (evidence-explorer.js: one office per client on the companies ring, one block
 * per export on a client's wall).
 *
 * office(THREE, models, spec) stands a client's office: a model of Kenney's City
 * Kit (CC0) picked by its score, read from this site by loadModels below, or,
 * when that model failed to load (and for an empty lot), the office modelled in
 * code by officeBuilding: a lobby of dark glass, a body of floors with a window
 * facade drawn into small canvases, floor slabs, a parapet, a plant room on the
 * roof and a light strip round the roof edge. Nothing is loaded from outside.
 *
 * office and officeBuilding return { group, materials, top }. spec:
 *   width, depth  the footprint, in scene units
 *   floors        how many floors stand above the lobby (1 or more)
 *   state         "built" (a finished building), "frame" (the same building in
 *                 scaffolding: too little evidence for a score) or "lot" (an
 *                 empty plot)
 *   strip         the colour of the roof light (a number, 0xRRGGBB)
 *   red           how many windows of the front are lit red (0 to 12)
 *   seed          a whole number: the same seed lights the same windows (and
 *                 picks the same model of a band)
 *   score         0 to 100, the band of the model (office only)
 * Every material carries userData.base (its own opacity), so a caller can dim a
 * building and bring it back. The caller disposes geometries, materials and maps;
 * a model's geometry and colormap are shared by every office of the page, so
 * disposing them frees their copies on the graphics card only and the next mount
 * uploads them again from the copy loadModels keeps.
 */

const FLOOR = 0.2;
const LOBBY = 0.24;
const WALL = "#c7cad3";
const WALL_DARK = "#9da2b0";
const GLASS = "#273246";
const LIT = "#ffd89a";
const RED = "#ff6b5e";

// A small deterministic random series, so a building keeps its lit windows.
function series(seed) {
  let state = (seed * 2654435761) >>> 0 || 1;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

// The facade of one side: a wall with a window per bay on every floor.
function facade(THREE, columns, floors, random, red) {
  const bay = 16;
  const tall = 20;
  const art = document.createElement("canvas");
  art.width = columns * bay;
  art.height = floors * tall;
  const pen = art.getContext("2d");
  pen.fillStyle = WALL;
  pen.fillRect(0, 0, art.width, art.height);
  // The red windows (one per control that needs work) stand at places chosen by
  // the seeded series, the same places on every draw.
  const places = [];
  for (let k = 0; k < columns * floors; k += 1) {
    places.push(k);
  }
  for (let k = places.length - 1; k > 0; k -= 1) {
    const j = Math.floor(random() * (k + 1));
    [places[k], places[j]] = [places[j], places[k]];
  }
  const reds = new Set(places.slice(0, Math.min(red, places.length)));
  for (let row = 0; row < floors; row += 1) {
    // a darker band under every floor's windows: the spandrel
    pen.fillStyle = WALL_DARK;
    pen.fillRect(0, row * tall + tall - 4, art.width, 2);
    for (let col = 0; col < columns; col += 1) {
      let colour = GLASS;
      if (reds.has(row * columns + col)) {
        colour = RED;
      } else if (random() < 0.28) {
        colour = LIT;
      }
      pen.fillStyle = colour;
      pen.fillRect(col * bay + 3, row * tall + 3, bay - 6, tall - 9);
    }
  }
  const texture = new THREE.CanvasTexture(art);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

function remember(material, list) {
  material.userData.base = material.opacity;
  list.push(material);
  return material;
}

// Scaffolding on the street side (+z) and the right-hand side (+x) of a body
// `width` by `depth` that rises `body` from `base`: steel poles, a ledger at each
// of `levels` lifts and an amber board on each.
function scaffold(THREE, group, materials, width, depth, base, body, levels) {
  const steel = remember(new THREE.MeshStandardMaterial({ color: 0xc9cdd6, roughness: 0.45, metalness: 0.6, transparent: true }), materials);
  const board = remember(new THREE.MeshStandardMaterial({ color: 0xd99a3a, roughness: 0.7, transparent: true }), materials);
  const out = 0.07;
  const lift = body / levels;
  const pole = new THREE.BoxGeometry(0.018, body + 0.12, 0.018);
  const along = (length) => new THREE.BoxGeometry(length, 0.014, 0.014);
  // the street face (+z)
  const spanX = width + 2 * out;
  const columns = Math.max(2, Math.round(spanX / 0.17));
  for (let k = 0; k <= columns; k += 1) {
    const x = -spanX / 2 + (k * spanX) / columns;
    const mesh = new THREE.Mesh(pole, steel);
    mesh.position.set(x, base + body / 2 + 0.06, depth / 2 + out);
    mesh.castShadow = true;
    group.add(mesh);
  }
  // the right-hand face (+x)
  const spanZ = depth + out;
  const rows = Math.max(2, Math.round(spanZ / 0.17));
  for (let k = 0; k < rows; k += 1) {
    const z = -depth / 2 + (k * spanZ) / rows;
    const mesh = new THREE.Mesh(pole, steel);
    mesh.position.set(width / 2 + out, base + body / 2 + 0.06, z);
    mesh.castShadow = true;
    group.add(mesh);
  }
  const ledgerX = along(spanX);
  const ledgerZ = along(spanZ);
  ledgerZ.rotateY(Math.PI / 2);
  const plankX = new THREE.BoxGeometry(spanX, 0.012, 0.06);
  const plankZ = new THREE.BoxGeometry(0.06, 0.012, spanZ);
  for (let k = 1; k <= levels; k += 1) {
    const y = base + k * lift;
    const front = new THREE.Mesh(ledgerX, steel);
    front.position.set(0, y, depth / 2 + out);
    const right = new THREE.Mesh(ledgerZ, steel);
    right.position.set(width / 2 + out, y, depth / 2 + out / 2 - spanZ / 2);
    const walk = new THREE.Mesh(plankX, board);
    walk.position.set(0, y - 0.012, depth / 2 + out / 2 + 0.005);
    walk.castShadow = true;
    const walkSide = new THREE.Mesh(plankZ, board);
    walkSide.position.set(width / 2 + out / 2 + 0.005, y - 0.012, depth / 2 + out / 2 - spanZ / 2);
    group.add(front, right, walk, walkSide);
  }
}

// The light strip of the building's colour round a roof `width` by `depth` at `roofY`.
function roofLight(THREE, group, materials, strip, width, depth, roofY) {
  const light = new THREE.MeshStandardMaterial({
    color: strip,
    emissive: strip,
    emissiveIntensity: 0.9,
    roughness: 0.4,
    transparent: true,
  });
  light.userData.emissive = strip;
  light.userData.emissiveIntensity = 0.9;
  remember(light, materials);
  [
    [width + 0.03, 0.025, 0, depth / 2 + 0.005],
    [width + 0.03, 0.025, 0, -depth / 2 - 0.005],
    [0.025, depth + 0.03, width / 2 + 0.005, 0],
    [0.025, depth + 0.03, -width / 2 - 0.005, 0],
  ].forEach(([sx, sz, x, z]) => {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(sx, 0.025, sz), light);
    mesh.position.set(x, roofY - 0.015, z);
    group.add(mesh);
  });
}

export function officeBuilding(THREE, spec) {
  const group = new THREE.Group();
  const materials = [];
  const width = spec.width;
  const depth = spec.depth;
  const strip = spec.strip;

  // The lot: a pavement slab every building stands on, edged in its colour.
  const lot = new THREE.Mesh(
    new THREE.BoxGeometry(width + 0.24, 0.04, depth + 0.24),
    remember(new THREE.MeshStandardMaterial({ color: 0x5b6070, roughness: 0.9, transparent: true }), materials)
  );
  lot.position.y = 0.02;
  lot.receiveShadow = true;
  group.add(lot);

  if (spec.state === "lot") {
    // An empty plot: a dashed fence of short posts where the building will stand.
    const post = new THREE.BoxGeometry(0.03, 0.12, 0.03);
    const fence = remember(new THREE.MeshStandardMaterial({ color: strip, roughness: 0.6, transparent: true }), materials);
    const half = { x: width / 2, z: depth / 2 };
    for (let k = 0; k <= 8; k += 1) {
      const t = k / 8;
      [
        [-half.x + t * width, -half.z],
        [-half.x + t * width, half.z],
        [-half.x, -half.z + t * depth],
        [half.x, -half.z + t * depth],
      ].forEach(([x, z]) => {
        const mesh = new THREE.Mesh(post, fence);
        mesh.position.set(x, 0.1, z);
        group.add(mesh);
      });
    }
    return { group, materials, top: 0.3 };
  }

  const floors = Math.max(1, Math.round(spec.floors));
  const body = floors * FLOOR;
  const top = LOBBY + body;

  // The lobby: dark glass a little inside the line of the floors above.
  const lobby = new THREE.Mesh(
    new THREE.BoxGeometry(width - 0.06, LOBBY, depth - 0.06),
    remember(
      new THREE.MeshStandardMaterial({
        color: 0x1d2433,
        roughness: 0.15,
        metalness: 0.4,
        emissive: 0xffd89a,
        emissiveIntensity: 0.08,
        transparent: true,
      }),
      materials
    )
  );
  lobby.position.y = 0.04 + LOBBY / 2;
  lobby.castShadow = true;
  group.add(lobby);

  // The building itself: the facade drawn on its four sides, plain on the roof.
  // A client with too little evidence for a score is the same finished building
  // (its red windows still count the controls that need work) in scaffolding.
  const random = series(spec.seed || 1);
  const front = facade(THREE, Math.max(2, Math.round(width / 0.11)), floors, random, Math.min(spec.red || 0, 12));
  const side = facade(THREE, Math.max(2, Math.round(depth / 0.11)), floors, random, 0);
  const plain = remember(new THREE.MeshStandardMaterial({ color: 0xb4b8c3, roughness: 0.8, transparent: true }), materials);
  const wall = (map) =>
    remember(
      new THREE.MeshStandardMaterial({
        map,
        emissiveMap: map,
        emissive: 0xffffff,
        emissiveIntensity: 0.18,
        roughness: 0.55,
        metalness: 0.1,
        transparent: true,
      }),
      materials
    );
  const frontWall = wall(front);
  const sideWall = wall(side);
  // keep the glow of the windows when the building is chosen and let go
  [frontWall, sideWall].forEach((material) => {
    material.userData.emissive = 0xffffff;
    material.userData.emissiveIntensity = 0.18;
  });
  const tower = new THREE.Mesh(new THREE.BoxGeometry(width, body, depth), [
    sideWall,
    sideWall,
    plain,
    plain,
    frontWall,
    frontWall,
  ]);
  tower.position.y = 0.04 + LOBBY + body / 2;
  tower.castShadow = true;
  tower.receiveShadow = true;
  group.add(tower);

  if (spec.state === "frame") {
    scaffold(THREE, group, materials, width, depth, 0.04 + LOBBY, body, floors);
  }

  // The roof: a parapet, a plant room and the light strip of the building's colour.
  const roofY = 0.04 + top;
  const parapet = remember(new THREE.MeshStandardMaterial({ color: 0x8f94a3, roughness: 0.8, transparent: true }), materials);
  const lip = 0.03;
  [
    [width + 0.02, lip, 0, depth / 2],
    [width + 0.02, lip, 0, -depth / 2],
    [lip, depth, width / 2, 0],
    [lip, depth, -width / 2, 0],
  ].forEach(([sx, sz, x, z]) => {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(sx, 0.06, sz), parapet);
    mesh.position.set(x, roofY + 0.03, z);
    mesh.castShadow = true;
    group.add(mesh);
  });
  const plant = new THREE.Mesh(new THREE.BoxGeometry(width * 0.35, 0.08, depth * 0.35), parapet);
  plant.position.set(-width * 0.15, roofY + 0.04, -depth * 0.1);
  plant.castShadow = true;
  group.add(plant);
  roofLight(THREE, group, materials, strip, width, depth, roofY);
  return { group, materials, top: roofY + 0.12 };
}

// --- the Kenney City Kit models ----------------------------------------------------
//
// The offices, road tiles, lamps and trees are models of Kenney's City Kit
// (www.kenney.nl, CC0; app/static/models/kenney, LICENSES-CONTENT.md). Each is a
// binary glTF (GLB) of one mesh with positions, normals, texture coordinates and
// indices, and one material whose colour is the kit's colormap.png beside it: the
// reader below reads exactly that and refuses anything else, so a file it cannot
// read is a model that failed to load, and its offices are built in code above.
// Every file is fetched once per page, only when a scene is shown, with the
// version of the scripts (the `v` query) like every other module of the scenes.

const KIT = {
  "building-c": "commercial",
  "building-a": "commercial",
  "building-h": "commercial",
  "building-f": "commercial",
  "building-skyscraper-a": "commercial",
  "building-skyscraper-c": "commercial",
  "building-skyscraper-e": "commercial",
  "road-straight": "roads",
  "road-crossroad": "roads",
  "light-square": "roads",
  "tree-large": "suburban",
  "tree-small": "suburban",
};
// The office of a score: below 25, 25 to 50, 50 to 75, 75 to 90, 90 and over. Two
// models share a band and the seed picks one, so a client keeps its building.
const BANDS = [
  [25, ["building-c"]],
  [50, ["building-a", "building-h"]],
  [75, ["building-f"]],
  [90, ["building-skyscraper-a"]],
  [Infinity, ["building-skyscraper-c", "building-skyscraper-e"]],
];
// The models a street needs besides its offices.
export const STREET = ["road-straight", "road-crossroad", "light-square", "tree-large", "tree-small"];
// One unit of the kit is a city plot; the scenes stand an office a little smaller.
const MODEL_SCALE = 0.75;
// The colormap a step darker and cooler, so the models sit calmly on the dark stage.
const TINT = 0xb4b9c6;
const VERSION = new URL(import.meta.url).search;
const GLB_MAGIC = 0x46546c67;
const CHUNK_JSON = 0x4e4f534a;
const CHUNK_BIN = 0x004e4942;
const ARRAYS = { 5121: Uint8Array, 5123: Uint16Array, 5125: Uint32Array, 5126: Float32Array };
const SIZES = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4 };
const ATTRIBUTES = { POSITION: "position", NORMAL: "normal", TEXCOORD_0: "uv" };
const files = new Map();

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value));
}

export function officeModel(score, seed) {
  const names = BANDS.find(([below]) => score < below)[1];
  return names[Math.abs(Math.round(seed)) % names.length];
}

// A file of this site, addressed from this module with the scripts' version, read
// once per page: the promise is kept, so a second scene (or a second mount) reuses it.
function once(path, base, read) {
  const url = new URL(path, base);
  url.search = VERSION;
  if (!files.has(url.href)) {
    files.set(url.href, read(url.href));
  }
  return files.get(url.href);
}

function refuse(url, what) {
  throw new Error(url + ": " + what);
}

async function readModel(THREE, url) {
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) {
    refuse(url, "status " + response.status);
  }
  const data = await response.arrayBuffer();
  const head = new DataView(data);
  if (data.byteLength < 28 || head.getUint32(0, true) !== GLB_MAGIC || head.getUint32(4, true) !== 2 || head.getUint32(16, true) !== CHUNK_JSON) {
    refuse(url, "not a glTF 2 binary");
  }
  const jsonLength = head.getUint32(12, true);
  const json = JSON.parse(new TextDecoder().decode(new Uint8Array(data, 20, jsonLength)));
  const binAt = 20 + jsonLength;
  if (data.byteLength < binAt + 8 || head.getUint32(binAt + 4, true) !== CHUNK_BIN) {
    refuse(url, "no binary chunk");
  }
  const bin = data.slice(binAt + 8, binAt + 8 + head.getUint32(binAt, true));
  // One node holding the one mesh, no transform, one triangle list, no required
  // extension: what every model of the kit is (tests/test_scenes.py checks them).
  const nodes = json.nodes || [];
  const meshes = json.meshes || [];
  const primitive = meshes.length === 1 && meshes[0].primitives.length === 1 ? meshes[0].primitives[0] : null;
  if (
    !primitive ||
    nodes.length !== 1 ||
    nodes[0].mesh !== 0 ||
    Object.keys(nodes[0]).some((key) => key !== "mesh" && key !== "name") ||
    (primitive.mode !== undefined && primitive.mode !== 4) ||
    (json.extensionsRequired || []).length
  ) {
    refuse(url, "a model this reader does not read");
  }
  const read = (index) => {
    const accessor = json.accessors[index];
    const view = json.bufferViews[accessor.bufferView];
    const Kind = ARRAYS[accessor.componentType];
    const size = SIZES[accessor.type];
    if (!Kind || !size || accessor.sparse || (view.byteStride && view.byteStride !== size * Kind.BYTES_PER_ELEMENT)) {
      refuse(url, "an accessor this reader does not read");
    }
    const start = (view.byteOffset || 0) + (accessor.byteOffset || 0);
    const end = start + accessor.count * size * Kind.BYTES_PER_ELEMENT;
    if (end > bin.byteLength) {
      refuse(url, "an accessor outside its buffer");
    }
    return new THREE.BufferAttribute(new Kind(bin.slice(start, end)), size, Boolean(accessor.normalized));
  };
  const geometry = new THREE.BufferGeometry();
  Object.keys(ATTRIBUTES).forEach((name) => {
    if (primitive.attributes[name] === undefined) {
      refuse(url, "no " + name);
    }
    geometry.setAttribute(ATTRIBUTES[name], read(primitive.attributes[name]));
  });
  geometry.setIndex(read(primitive.indices));
  geometry.computeBoundingBox();
  const material = (json.materials || [])[primitive.material] || {};
  const colour = (material.pbrMetallicRoughness || {}).baseColorTexture;
  const image = colour ? json.images[json.textures[colour.index].source] : null;
  // The texture is a file beside the model (Textures/colormap.png), never an address.
  if (!image || !/^[\w-]+(\/[\w-]+)*\.png$/.test(image.uri || "")) {
    refuse(url, "no colormap beside it");
  }
  const texture = await once(image.uri, url, (address) =>
    new THREE.TextureLoader().loadAsync(address).then((map) => {
      map.flipY = false;
      map.colorSpace = THREE.SRGBColorSpace;
      return map;
    })
  );
  return { geometry, texture, box: geometry.boundingBox };
}

// The models of `names`, read (once per page) into a Map by name. A model that
// cannot be read is left out: its offices are built in code, its street pieces too.
export async function loadModels(THREE, names) {
  const models = new Map();
  await Promise.all(
    Array.from(new Set(names))
      .filter((name) => KIT[name])
      .map(async (name) => {
        try {
          models.set(name, await once("../models/kenney/" + KIT[name] + "/" + name + ".glb", import.meta.url, (url) => readModel(THREE, url)));
        } catch (error) {
          // The code-built office stands in; the scene is whole either way.
        }
      })
  );
  return models;
}

// An office from a model, with the same spec and answer as officeBuilding: the
// model of the score's band, as wide as the company (one scale for x and z, within
// a sensible range, never deeper than its plot allows), its front where a built
// office's front would be; scaffolding round it with too little evidence, the
// roof light round its top and a red panel on its street face per control that
// needs work. The geometry and the colormap are shared by the page; the materials
// are the office's own, so it dims alone.
function modelOffice(THREE, model, spec) {
  const group = new THREE.Group();
  const materials = [];
  const size = model.box.getSize(new THREE.Vector3());
  const middle = model.box.getCenter(new THREE.Vector3());
  const across = Math.min(MODEL_SCALE * clamp(spec.width / 0.75, 0.6, 1.3), (spec.depth + 0.3) / size.z);
  const width = size.x * across;
  const depth = size.z * across;
  const height = size.y * MODEL_SCALE;
  const plot = new THREE.Group();
  plot.position.z = Math.min(0, spec.depth / 2 - depth / 2);
  group.add(plot);

  const lot = new THREE.Mesh(
    new THREE.BoxGeometry(width + 0.24, 0.04, depth + 0.24),
    remember(new THREE.MeshStandardMaterial({ color: 0x5b6070, roughness: 0.9, transparent: true }), materials)
  );
  lot.position.y = 0.02;
  lot.receiveShadow = true;
  plot.add(lot);

  const skin = remember(new THREE.MeshStandardMaterial({ map: model.texture, color: TINT, roughness: 0.8, metalness: 0, transparent: true }), materials);
  // The kit's entrances face -z; turned round, the entrance faces the street (+z).
  const building = new THREE.Mesh(model.geometry, skin);
  building.scale.set(across, MODEL_SCALE, across);
  building.rotation.y = Math.PI;
  building.position.set(middle.x * across, 0.04 - model.box.min.y * MODEL_SCALE, middle.z * across);
  building.castShadow = true;
  building.receiveShadow = true;
  plot.add(building);

  if (spec.state === "frame") {
    const body = height - 0.1;
    scaffold(THREE, plot, materials, width, depth, 0.14, body, Math.max(1, Math.round(body / FLOOR)));
  }

  // The red panels: a grid on the street face, inside its edges and above the
  // ground floor; the seeded series picks the same cells on every draw.
  const red = Math.min(spec.red || 0, 12);
  if (red > 0) {
    const columns = Math.max(4, Math.round(width / 0.1));
    const rows = Math.max(3, Math.round(height / 0.18));
    const cellX = (width * 0.8) / columns;
    const cellY = (height * 0.72) / rows;
    const pane = new THREE.PlaneGeometry(cellX * 0.55, cellY * 0.45);
    const lit = remember(new THREE.MeshStandardMaterial({ color: RED, emissive: RED, emissiveIntensity: 0.9, roughness: 0.4, transparent: true }), materials);
    lit.userData.emissive = parseInt(RED.slice(1), 16);
    lit.userData.emissiveIntensity = 0.9;
    const random = series(spec.seed || 1);
    const places = Array.from({ length: columns * rows }, (unused, k) => k);
    for (let k = places.length - 1; k > 0; k -= 1) {
      const j = Math.floor(random() * (k + 1));
      [places[k], places[j]] = [places[j], places[k]];
    }
    places.slice(0, red).forEach((cell) => {
      const mesh = new THREE.Mesh(pane, lit);
      mesh.position.set(-width * 0.4 + ((cell % columns) + 0.5) * cellX, 0.04 + height * 0.2 + (Math.floor(cell / columns) + 0.5) * cellY, depth / 2 + 0.006);
      plot.add(mesh);
    });
  }

  roofLight(THREE, plot, materials, spec.strip, width, depth, 0.04 + height);
  return { group, materials, top: 0.04 + height + 0.12 };
}

// The office of a client: the model of its band from `models` (loadModels), or,
// for an empty lot or a model that failed to load, the office built in code.
export function office(THREE, models, spec) {
  const model = spec.state === "lot" ? null : models.get(officeModel(spec.score, spec.seed));
  return model ? modelOffice(THREE, model, spec) : officeBuilding(THREE, spec);
}

// The street furniture of a scene: a tree and a street lamp, sharing materials;
// from the models when they were read, built in code when not.
export function streetKit(THREE, models = new Map()) {
  const skins = new Map();
  // A piece of the kit standing at (x, lift, z), or null without its model.
  function piece(name, x, z, scale, turn, lift) {
    const model = models.get(name);
    if (!model) {
      return null;
    }
    if (!skins.has(name)) {
      skins.set(name, new THREE.MeshStandardMaterial({ map: model.texture, color: TINT, roughness: 0.85, metalness: 0 }));
    }
    const mesh = new THREE.Mesh(model.geometry, skins.get(name));
    mesh.scale.setScalar(scale);
    mesh.rotation.y = turn;
    mesh.position.set(x, lift - model.box.min.y * scale, z);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    return mesh;
  }
  // the pieces built in code, made only when a model is missing
  let built = null;
  const code = () => built || (built = codeKit(THREE));
  return {
    tree: (x, z, scale = 1) => piece(scale >= 0.9 ? "tree-large" : "tree-small", x, z, 0.6 * scale, 0, 0.02) || code().tree(x, z, scale),
    streetLamp: (x, z, turn = 0) => piece("light-square", x, z, 0.8, turn, 0.03) || code().streetLamp(x, z),
    // A road tile `size` wide centred at (x, z), or null without the model.
    road: (x, z, size, cross = false, turn = 0) => piece(cross ? "road-crossroad" : "road-straight", x, z, size, turn, 0),
  };
}

// The street furniture built in code, for a scene without the models.
function codeKit(THREE) {
  const trunk = new THREE.MeshStandardMaterial({ color: 0x6b5340, roughness: 0.9 });
  const leaves = new THREE.MeshStandardMaterial({ color: 0x4f7a55, roughness: 0.85 });
  const pole = new THREE.MeshStandardMaterial({ color: 0x3a3e4b, roughness: 0.5, metalness: 0.4 });
  const lamp = new THREE.MeshStandardMaterial({ color: 0xffe2a8, emissive: 0xffd27a, emissiveIntensity: 1.2 });
  const trunkShape = new THREE.CylinderGeometry(0.025, 0.035, 0.22, 8);
  const crown = new THREE.IcosahedronGeometry(0.15, 1);
  const poleShape = new THREE.CylinderGeometry(0.012, 0.016, 0.5, 8);
  const head = new THREE.SphereGeometry(0.035, 12, 8);
  function tree(x, z, scale = 1) {
    const group = new THREE.Group();
    const stem = new THREE.Mesh(trunkShape, trunk);
    stem.position.y = 0.11;
    stem.castShadow = true;
    const top = new THREE.Mesh(crown, leaves);
    top.position.y = 0.3;
    top.castShadow = true;
    group.add(stem, top);
    group.position.set(x, 0.02, z);
    group.scale.setScalar(scale);
    return group;
  }
  function streetLamp(x, z) {
    const group = new THREE.Group();
    const post = new THREE.Mesh(poleShape, pole);
    post.position.y = 0.25;
    post.castShadow = true;
    const bulb = new THREE.Mesh(head, lamp);
    bulb.position.y = 0.52;
    group.add(post, bulb);
    group.position.set(x, 0.02, z);
    return group;
  }
  return { tree, streetLamp };
}
