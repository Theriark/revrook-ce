# Evidence Explorer

A page at `/experiments/evidence-explorer`, in the Evidence group of the navigation,
that shows, for one client, which evidence exports feed which controls, and where the
evidence behind a status is stale or missing. It began as an experiment on the
Development installation to judge a scene drawn in the browser; after the founder
saw it, the same direction was taken to Home and the client overview
([design-system.md](design-system.md), Scenes), and the page is now an optional view
of the interface. It is not part of any report, it stores nothing, and it loads
nothing from outside the installation. The address keeps its first form so that no
link or bookmark breaks.

## What it shows

The page reads a client exactly as its checklist and its evidence page do: the
newest export of every source, run through the check engine (`app/posture.py`), and
the state of each export (`app/ui/viewmodels.py`, `source_rows`). A control is
linked to a source when its rule reads a column of that source's adapter
(`field_map` in `data/controls.yaml`); a manual-only control reads no export and has
no link. `app/ui/explorer_view.py` turns the two into one view model, and
`app/ui/explorer.py` serves it twice from the same object:

- as the page: a verdict band, the scene, and two tables (the sources with the
  state of their newest export and the controls they feed; the controls with their
  status today, their evidence and the exports they read);
- as JSON at `/experiments/evidence-explorer/data?client_id=N`, for the scene.

The tables are the record. The scene is one way of looking at them.

## The scene: the rookery wall

An inner ring of pillars, one per evidence source, each as tall as the number of
controls it feeds and crenellated like a rook; a current export is a full pillar in
the brand stone, a stale or expired one a low pillar in the status colour, a source
never imported only a footprint. An outer ring of tiles, one per control, grouped
by domain around the wall: a flat tile for Protected, a tile with a ring for Needs
attention, a tile cut through for Not protected, an outlined tile for Not checked,
a small disc for Not applicable. A beam joins a source to every control that reads
it. Status is shape and colour together, never colour alone, and nothing is written
inside the scene: the detail line, the legend and the tables carry every word.

Pointing at a pillar or a tile names it; a press selects it and brings its beams
forward while the rest steps back; the same happens from the **Show in scene**
button of a table row, which also turns the wall to face it. A drag turns and tilts
the wall; the buttons under it turn it by a step or reset the view. The canvas is
announced as an application (a scene), so a screen reader passes its keys on; with
it focused, Left and Right turn, plus and minus move closer and away, Home resets,
Escape clears the selection. The ground is the brand charcoal in both themes, the
same dark surface as the rail; the colours on it are the dark-theme status values of
`revrook.css`, which reach 4.5 to 1 on it.

## How it is built, and what it does without

- `app/static/js/evidence-explorer.js` is an ES module loaded by this page alone,
  under the same content security policy as every page (`default-src 'self'`, no
  inline script, no `unsafe-eval`). It checks for WebGL 2 first and only then
  imports the library, so a browser without WebGL 2 never downloads it.
- three.js r186 (npm `three@0.186.1`, MIT) is served unmodified from
  `app/static/vendor/three`: `three.module.js` and `three.core.js` as published.
  The licence file and `PINNED.json` are committed; the two build files are not.
  `PINNED.json` records the npm tarball integrity and the SHA-256 of each file, and
  `tools/fetch_three.py` downloads that tarball, checks it and writes the two files
  only when every check passes. CI runs it before the tests and the image build runs
  it in the builder stage. To run the tests on your machine, run
  `python tools/fetch_three.py` once first; `tests/test_evidence_explorer.py` checks
  the files against `PINNED.json`. The two files are 2.1 MB (about 420 KB
  compressed); a smaller tree-shaken build needs a bundler the repository does not
  have and is a decision for later. No CDN, no download by the browser or at run
  time, no automatic update.
- Without script, or without WebGL 2, the stage keeps a note rendered by the server
  and the tables are the page. A request that fails (a session that ended, a client
  that is gone) leaves a note that says what to do. A lost graphics context stops
  the drawing with a note and resumes when the browser restores it.
- `prefers-reduced-motion` stops the wall turning by itself and makes every move
  immediate, also when the setting changes while the page is open; otherwise it
  turns slowly until the person touches it. Frames are drawn only when something
  changed or the wall is turning, never while the page is hidden or the stage is
  out of view.
- Leaving the page disposes every geometry, material and the renderer.
  `document.getElementById("explorer").revrookExplorer` offers `dispose()`,
  `mount()` and `info()` so a test can cycle the scene ten times and read the
  renderer's geometry and program counts.

## Limits

The scene has been checked in a headless browser with a software renderer
(SwiftShader) on the Development site; no hardware GPU, WebGPU, phone or touch
screen has been measured. The 51 controls and up to 13 sources of a client are a
small scene; a larger one has not been tried. The page keeps its own script
(`evidence-explorer.js`) while the rookery skyline and the domain keep share
`scenes.js`; folding the explorer onto the shared module is a later change.
