"""A scene that cannot get a WebGL context says so (THE-1414, F3 of THE-1413).

On Development with WebGL unavailable, pressing "Show the scene" did nothing
visible: three.js threw "Error creating WebGL context" inside the click handler
and the stage stayed closed. `mount` in app/static/js/scenes.js now catches it,
drops the half-built canvas, opens the stage and writes a short note in its
status line, and the button can try again. The test runs the module's own
`prepare` in Node.js against a small stand-in of the page and a renderer that
throws, and is skipped where Node.js is not installed.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.ui.brand import STATIC_DIR

SCRIPT_PATH = STATIC_DIR / "js/scenes.js"
SCRIPT = SCRIPT_PATH.read_text(encoding="utf-8")

PROBE = """
class Node {
  constructor(name) {
    this.name = name;
    this.hidden = false;
    this.textContent = "";
    this.attrs = {};
    this.classes = new Set();
    this.children = [];
    this.handlers = {};
    this.parent = null;
    const node = this;
    this.classList = {
      add: (c) => node.classes.add(c),
      remove: (c) => node.classes.delete(c),
      toggle: (c, on) => (on ? node.classes.add(c) : node.classes.delete(c)),
      contains: (c) => node.classes.has(c),
    };
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
  get firstChild() { return this.children[0] || null; }
  insertBefore(child) { child.parent = this; this.children.unshift(child); }
  remove() {
    if (this.parent) {
      this.parent.children = this.parent.children.filter((c) => c !== this);
      this.parent = null;
    }
  }
}
const store = {};
globalThis.window = {
  devicePixelRatio: 1,
  addEventListener() {},
  localStorage: {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
  },
};
globalThis.document = {
  querySelectorAll: () => [],
  createElement: (name) => new Node(name),
  getElementById: () => null,
};
let attempts = 0;
const THREE = {
  WebGLRenderer: class {
    constructor() {
      attempts += 1;
      throw new Error("Error creating WebGL context.");
    }
  },
};

function stageOf(closed) {
  const root = new Node("div");
  const parts = {
    ".rv-scene-state": new Node("div"),
    ".rv-scene-state-text": new Node("p"),
    ".rv-scene-tools": new Node("div"),
    ".rv-scene-toggle": new Node("button"),
    ".rv-scene-toggle-text": new Node("span"),
    ".rv-scene-stage": new Node("div"),
    ".rv-scene-detail": new Node("p"),
    ".rv-scene-hover": new Node("p"),
  };
  parts[".rv-scene-tools"].hidden = true;
  parts[".rv-scene-toggle"].hidden = true;
  parts[".rv-scene-state"].querySelector = (s) => parts[s] || null;
  parts[".rv-scene-toggle"].querySelector = (s) => parts[s] || null;
  parts[".rv-scene-detail"].id = "scene-detail";
  root.ownerDocument = document;
  root.attrs = {
    "data-scene": "rookery",
    "data-scene-for": "rooks",
    "data-scene-state": "loading",
  };
  root.querySelector = (s) => {
    if (s === ".rv-scene-stage canvas") {
      return parts[".rv-scene-stage"].children.find((c) => c.name === "canvas") || null;
    }
    return parts[s] || null;
  };
  if (closed) {
    store["rv-scenes"] = "off";
  } else {
    delete store["rv-scenes"];
  }
  return { root, parts };
}

function seen({ root, parts }) {
  const state = parts[".rv-scene-state"];
  return {
    sceneState: root.getAttribute("data-scene-state"),
    closed: root.classes.has("is-closed"),
    noteHidden: state.hidden,
    noteKind: state.getAttribute("data-kind"),
    note: parts[".rv-scene-state-text"].textContent,
    canvases: parts[".rv-scene-stage"].children.length,
    toolsHidden: parts[".rv-scene-tools"].hidden,
    toggleHidden: parts[".rv-scene-toggle"].hidden,
    toggle: parts[".rv-scene-toggle-text"].textContent,
    api: typeof root.revrookScene,
  };
}

const { prepare } = await import(%(url)s);
const out = {};
// Opened at once: the page loads with the scenes shown.
const open = stageOf(false);
await prepare(open.root, THREE, null);
out.open = seen(open);
// Closed earlier in this browser; the person presses "Show the scene".
const closed = stageOf(true);
await prepare(closed.root, THREE, null);
out.closedBefore = seen(closed);
for (const fn of closed.parts[".rv-scene-toggle"].handlers.click) {
  fn();
}
out.shown = seen(closed);
out.remembered = store["rv-scenes"] || null;
// Pressed again: it tries again and says the same, nothing thrown.
for (const fn of closed.parts[".rv-scene-toggle"].handlers.click) {
  fn();
}
out.again = seen(closed);
out.attempts = attempts;
console.log(JSON.stringify(out));
"""


def run_probe(tmp_path: Path) -> dict:
    probe = tmp_path / "probe.mjs"
    probe.write_text(
        PROBE % {"url": json.dumps(SCRIPT_PATH.resolve().as_uri())}, encoding="utf-8"
    )
    found = subprocess.run(
        ["node", str(probe)], capture_output=True, text=True, timeout=60, check=True
    )
    return json.loads(found.stdout)


def test_the_mount_catches_a_refused_context_and_names_it() -> None:
    mount = SCRIPT.split("  function mount() {", 1)[1].split("\n  }\n", 1)[0]
    assert "built = buildScene(THREE, root, options);" in mount
    assert "} catch (error) {" in mount
    assert 'options.setState("error", WORDS.noWebGL);' in mount
    # The browser without WebGL 2 at all keeps the old fallback: no stage at all.
    assert "if (!supportsWebGL2()) {\n    putAway(every);\n    return;\n  }" in SCRIPT


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_without_a_webgl_context_the_stage_says_so(tmp_path: Path) -> None:
    out = run_probe(tmp_path)
    note = "This browser could not start the 3D view"
    # Shown on load: the note of the refused context, not "the library could not
    # be loaded", and the page's scene handle is still wired.
    opened = out["open"]
    assert opened["sceneState"] == "error"
    assert opened["noteHidden"] is False and opened["noteKind"] == "error"
    assert opened["note"].startswith(note)
    assert opened["canvases"] == 0 and opened["toolsHidden"] is True
    assert opened["toggle"] == "Show the scene" and opened["toggleHidden"] is False
    assert opened["api"] == "object"
    # Closed before: the stage is closed with its button, as it was.
    before = out["closedBefore"]
    assert before["closed"] is True and before["sceneState"] == "disposed"
    assert before["note"] == "The scene is closed."
    # "Show the scene" now opens the stage on the note instead of doing nothing.
    shown = out["shown"]
    assert shown["closed"] is False
    assert shown["sceneState"] == "error" and shown["noteHidden"] is False
    assert shown["note"].startswith(note) and "WebGL" in shown["note"]
    assert shown["canvases"] == 0 and shown["toolsHidden"] is True
    assert shown["toggle"] == "Show the scene"
    assert out["remembered"] is None
    # A second press tries once more and leaves the same note; three tries in all.
    assert out["again"] == shown
    assert out["attempts"] == 3
