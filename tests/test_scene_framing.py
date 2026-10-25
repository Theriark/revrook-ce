"""The home view of a scene keeps every node whole (docs/design-system.md, Scenes).

On Development at 768px the front blocks of a client's domain keep ran off the
foot of the stage (THE-1188): the estimate of the home distance fitted the width
of the front row and the tallest block, not the depth of the second row seen from
above. `framingDistance` in app/static/js/scenes.js now finds the distance at
which every corner of every node is inside the view. The geometry test runs the
module's own function in Node.js and is skipped where Node.js is not installed.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.ui.brand import STATIC_DIR

SCRIPT_PATH = STATIC_DIR / "js/scenes.js"
SCRIPT = SCRIPT_PATH.read_text(encoding="utf-8")
CSS = (STATIC_DIR / "css/scenes.css").read_text(encoding="utf-8")
MARGIN = 0.88
# The keeps and rookeries to frame: the layout of scenes.js (place, buildBlock,
# a plinth 0.24 wider than its block, 0.16 per control), the weights and the
# controls per domain of the seeded clients, and rows of one to twelve nodes. For
# each stage shape the script prints how far out the worst corner lies, as a share
# of the half view (1 is the edge), at the distance framingDistance gives.
PROBE = """
import { framingDistance } from %(url)s;
const layouts = [
  { weights: [22, 14, 10, 12, 16, 14, 12], counts: [8, 7, 5, 7, 6, 5, 8] },
  { weights: [20, 20, 20], counts: [9, 2, 6] },
  { weights: [30], counts: [12] },
  { weights: Array(12).fill(10), counts: Array(12).fill(4) },
];
const aspects = [21 / 9, 16 / 9, 16 / 10, 1.2, 3];
const fov = 32;
const home = { yaw: 0.35, pitch: 0.55 };
const out = [];
for (const layout of layouts) {
  const count = layout.weights.length;
  const perRow = count > 6 ? Math.ceil(count / 2) : count;
  const heaviest = Math.max(...layout.weights);
  const corners = [];
  let tallest = 0.5;
  layout.weights.forEach((weight, k) => {
    const row = Math.floor(k / perRow);
    const inRow = Math.min(perRow, count - row * perRow);
    const x = ((k %% perRow) - (inRow - 1) / 2) * 1.7;
    const z = row * -1.9 + Math.abs(x) * 0.08;
    const half = (0.45 + 0.75 * Math.sqrt(weight / heaviest) + 0.24) / 2;
    const top = 0.08 + layout.counts[k] * 0.16;
    tallest = Math.max(tallest, layout.counts[k] * 0.16);
    for (const cx of [x - half, x + half])
      for (const cy of [0, top])
        for (const cz of [z - half, z + half])
          corners.push({ x: cx, y: cy, z: cz });
  });
  const lift = Math.min(0.6, 0.25 + tallest / 2);
  const target = { x: 0, y: lift, z: count > 6 ? -0.9 : 0 };
  for (const aspect of aspects) {
    const d = framingDistance(corners, home, target, fov, aspect);
    const t = Math.tan(((fov / 2) * Math.PI) / 180);
    const cp = Math.cos(home.pitch), sp = Math.sin(home.pitch);
    const cy = Math.cos(home.yaw), sy = Math.sin(home.yaw);
    const back = [cp * sy, sp, cp * cy];
    const right = [cy, 0, -sy];
    const up = [-sp * sy, cp, -sp * cy];
    let worst = 0;
    let edge = Infinity;
    for (const c of corners) {
      const v = [c.x - target.x, c.y - target.y, c.z - target.z];
      const dot = (a) => v[0] * a[0] + v[1] * a[1] + v[2] * a[2];
      const depth = d - dot(back);
      const share = Math.max(
        Math.abs(dot(right)) / (t * aspect * depth),
        Math.abs(dot(up)) / (t * depth)
      );
      worst = Math.max(worst, share);
      edge = Math.min(edge, depth);
    }
    out.push({ count, aspect, distance: d, worst, nearest: edge });
  }
}
console.log(JSON.stringify(out));
"""


def test_the_home_view_is_fitted_from_the_corners_of_every_node() -> None:
    assert "export function framingDistance(" in SCRIPT
    assert "function cornersOf(box, into)" in SCRIPT
    assert "cornersOf(bounds.setFromObject(node.group), corners);" in SCRIPT
    fit = SCRIPT.split("function fitDistance() {", 1)[1].split("\n  }\n", 1)[0]
    assert "framingDistance(corners, home, target, camera.fov, camera.aspect)" in fit
    # The estimate from the width of the row and the tallest node is gone.
    assert "byHeight" not in SCRIPT and "byWidth" not in SCRIPT
    # The module only starts in a browser, so Node.js can import its functions.
    assert 'if (typeof document !== "undefined") {\n  main();\n}' in SCRIPT


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_no_corner_of_a_keep_or_a_rookery_leaves_the_stage(tmp_path: Path) -> None:
    probe = tmp_path / "probe.mjs"
    probe.write_text(
        PROBE % {"url": json.dumps(SCRIPT_PATH.resolve().as_uri())}, encoding="utf-8"
    )
    found = subprocess.run(
        ["node", str(probe)], capture_output=True, text=True, timeout=60, check=True
    )
    results = json.loads(found.stdout)
    assert len(results) == 20
    for item in results:
        # Inside the view with the margin, and every corner in front of the camera.
        assert item["worst"] <= MARGIN + 1e-9, item
        assert item["nearest"] > 0.5, item
        assert item["distance"] >= 4.5, item
    # The seeded keep of seven domains in the 21 by 9 stage: the old estimate put
    # it at 6.9, where a front corner lay at 1.37 of the half view (cut off).
    wide = [r for r in results if abs(r["aspect"] - 21 / 9) < 1e-9]
    seven = next(r for r in wide if r["count"] == 7)
    assert seven["distance"] > 6.9 * 1.3
    # The fit is tight: some corner sits on the margin, so nothing is far too small.
    tight = [r for r in results if r["distance"] > 4.5]
    assert all(r["worst"] > MARGIN - 1e-6 for r in tight)


def test_the_keep_has_a_taller_stage_than_the_rookery_from_600px() -> None:
    keep_stage = '.rv-scene[data-scene="keep"] .rv-scene-stage {'
    rule = f"@media (min-width: 600px) {{\n  {keep_stage}"
    assert rule in CSS
    keep = CSS.split(rule, 1)[1].split("}", 1)[0]
    assert "aspect-ratio: 16 / 9;" in keep
    # The rookery keeps its wide stage and a phone its squarer one.
    assert "aspect-ratio: 21 / 9;" in CSS and "aspect-ratio: 16 / 10;" in CSS
