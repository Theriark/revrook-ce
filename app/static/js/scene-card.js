/*
 * revrook scene card (docs/design-system.md, Scenes): the card of a node chosen in
 * a scene, shared by the Home street (scenes.js) and the companies ring of the
 * Evidence Explorer (evidence-explorer.js). The card is a non-modal popover the
 * server drew into a <template> on the page; this module clones it, never builds
 * it from strings. It stands beside its node inside the stage, or, on a narrow
 * stage (a phone), under the stage, full width, so it never covers the scene it
 * describes. Imported with the version of the importing script, like office.js.
 */

// Below this stage width the card docks under the scene instead of standing
// beside its node.
const DOCK_WIDTH = 600;

function clamp(value, low, high) {
  return Math.min(high, Math.max(low, value));
}

// One card at a time for one stage. `onKey` gets the keys pressed in the card
// (Escape anywhere in it; every key on its heading, where the keyboard lands, so
// the keys of the scene keep choosing); `onClose(refocus)` is asked to close it:
// by its Close button (refocus, the canvas gets the focus back) or by a press
// outside it (no refocus), unless the press is in `keep` (the buttons under a
// stage that change the view, not the choice). Every listener ends with `signal`.
export function sceneCard({ page, stage, canvas, signal, keep = null, onKey, onClose }) {
  let card = null;

  function close() {
    if (card) {
      card.element.remove();
      card = null;
    }
  }

  // Beside `anchor` (a point of the scene) on the side with room, inside the
  // stage; docked under a narrow stage.
  function place(camera) {
    if (!card) {
      return;
    }
    const width = stage.clientWidth;
    const height = stage.clientHeight;
    const docked = width < DOCK_WIDTH;
    card.element.classList.toggle("is-docked", docked);
    if (docked) {
      card.element.style.left = "";
      card.element.style.top = "";
      if (card.element.parentNode !== stage.parentNode) {
        stage.after(card.element);
      }
      return;
    }
    if (card.element.parentNode !== stage) {
      stage.appendChild(card.element);
    }
    const point = card.anchor.clone().project(camera);
    const x = ((point.x + 1) / 2) * width;
    const y = ((1 - point.y) / 2) * height;
    const wide = card.element.offsetWidth;
    const high = card.element.offsetHeight;
    const gap = 16;
    const left = x + gap + wide > width - 8 ? x - gap - wide : x + gap;
    card.element.style.left = clamp(left, 8, Math.max(8, width - wide - 8)) + "px";
    card.element.style.top = clamp(y - high / 2, 8, Math.max(8, height - high - 8)) + "px";
  }

  // The card of the template `id` beside `anchor`; a node without a template has
  // no card. Opened from the keyboard, its heading takes the focus.
  function open(id, anchor, camera, keyed) {
    close();
    const template = id ? page.getElementById(id) : null;
    const source = template && template.content ? template.content.firstElementChild : null;
    if (!source) {
      return;
    }
    const element = source.cloneNode(true);
    const heading = element.querySelector(".rv-scene-card-title");
    const button = element.querySelector(".rv-scene-card-close");
    if (button) {
      button.addEventListener("click", () => onClose(true), { signal });
    }
    element.addEventListener(
      "keydown",
      (event) => {
        if (event.key === "Escape" || event.target === heading) {
          onKey(event);
        }
      },
      { signal }
    );
    stage.appendChild(element);
    card = { element, anchor };
    place(camera);
    if (keyed && heading) {
      heading.focus();
    }
  }

  // A press outside the card closes it; a press on the canvas picks instead
  // (another node moves the card, the ground closes it), and a press in a dialog
  // the card opened (the control drawer) leaves it, so focus can come back to it.
  page.addEventListener(
    "pointerdown",
    (event) => {
      const target = event.target;
      if (!card || target === canvas || card.element.contains(target) || (keep && keep.contains(target))) {
        return;
      }
      if (target.closest && target.closest("dialog[open]")) {
        return;
      }
      onClose(false);
    },
    { signal }
  );

  return { open, close, place };
}
