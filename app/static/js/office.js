/*
 * The office building of the revrook scenes, modelled in code: a lobby of dark
 * glass, a body of floors with a window facade, floor slabs, a parapet, a plant
 * room on the roof and a light strip round the roof edge. Shared by the street of
 * Home (scenes.js: one building per client) and the Evidence Explorer
 * (evidence-explorer.js: one block per export). Nothing is loaded from outside: the
 * facades are drawn into small canvases.
 *
 * officeBuilding(THREE, spec) returns { group, materials, top }. spec:
 *   width, depth  the footprint, in scene units
 *   floors        how many floors stand above the lobby (1 or more)
 *   state         "built" (a finished building), "frame" (under construction:
 *                 slabs and columns behind glass) or "lot" (an empty plot)
 *   strip         the colour of the roof light (a number, 0xRRGGBB)
 *   red           how many windows of the front are lit red (0 to 12)
 *   seed          a whole number: the same seed lights the same windows
 * Every material carries userData.base (its own opacity), so a caller can dim a
 * building and bring it back. The caller disposes geometries, materials and maps.
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

  if (spec.state === "frame") {
    // Under construction: the floor slabs and four columns behind glass.
    const concrete = remember(new THREE.MeshStandardMaterial({ color: 0xb9bcc6, roughness: 0.8, transparent: true }), materials);
    const slab = new THREE.BoxGeometry(width, 0.035, depth);
    for (let k = 0; k <= floors; k += 1) {
      const mesh = new THREE.Mesh(slab, concrete);
      mesh.position.y = 0.04 + LOBBY + k * FLOOR;
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      group.add(mesh);
    }
    const column = new THREE.BoxGeometry(0.05, body, 0.05);
    [-1, 1].forEach((sx) => {
      [-1, 1].forEach((sz) => {
        const mesh = new THREE.Mesh(column, concrete);
        mesh.position.set(sx * (width / 2 - 0.04), 0.04 + LOBBY + body / 2, sz * (depth / 2 - 0.04));
        mesh.castShadow = true;
        group.add(mesh);
      });
    });
    const glass = remember(
      new THREE.MeshStandardMaterial({
        color: 0xbcd0f0,
        roughness: 0.05,
        metalness: 0.1,
        transparent: true,
        opacity: 0.22,
        depthWrite: false,
      }),
      materials
    );
    const shell = new THREE.Mesh(new THREE.BoxGeometry(width + 0.02, body, depth + 0.02), glass);
    shell.position.y = 0.04 + LOBBY + body / 2;
    group.add(shell);
  } else {
    // A finished building: the facade drawn on its four sides, plain on the roof.
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
  if (spec.state !== "frame") {
    const plant = new THREE.Mesh(new THREE.BoxGeometry(width * 0.35, 0.08, depth * 0.35), parapet);
    plant.position.set(-width * 0.15, roofY + 0.04, -depth * 0.1);
    plant.castShadow = true;
    group.add(plant);
  }
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
  return { group, materials, top: roofY + 0.12 };
}

// The street furniture of a scene: a tree and a street lamp, sharing materials.
export function streetKit(THREE) {
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
