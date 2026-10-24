/*
 * The filter chips of the clients list (templates/clients.html, THE-1061). Same
 * origin, no eval, no network. Every chip of the "Filtered by" row is a plain
 * link to the list without that filter, and "Clear all filters" a link to the
 * list without any, so removing a filter works without this script. It adds:
 * - Delete or Backspace on a chip that has focus removes it, as Enter does;
 * - just before the list is left for a chip's address, a short note of what
 *   was removed (sessionStorage of this tab, read once, ten seconds at most);
 * - on the list that follows, focus moves to the chip that took the removed
 *   one's place (the next, else the one before) or, when no chip is left, to
 *   the Show filter in use; and the live region #filter-status says what was
 *   removed and how many clients are shown (data-shown, written by the server).
 * A click with a modifier key (a new tab) leaves no note. A browser that
 * refuses sessionStorage still follows the link; only the focus move and the
 * words are lost.
 */
(function () {
  "use strict";

  var NOTE = "revrook.filterChips";
  var MAX_AGE_MS = 10000;
  // Text put into an empty live region a moment after the page settles is read
  // out; text already there when the page loads usually is not.
  var SAY_AFTER_MS = 150;

  function linkOf(node) {
    while (node && node !== document) {
      if (
        node.tagName === "A" &&
        (node.hasAttribute("data-filter-chip") || node.hasAttribute("data-filter-clear"))
      ) {
        return node;
      }
      node = node.parentNode;
    }
    return null;
  }

  function chips() {
    return Array.prototype.slice.call(document.querySelectorAll("a[data-filter-chip]"));
  }

  function remember(link) {
    var cleared = link.hasAttribute("data-filter-clear");
    var note = {
      path: window.location.pathname,
      index: cleared ? -1 : chips().indexOf(link),
      text: cleared ? "" : link.getAttribute("data-filter-text") || "",
      at: Date.now()
    };
    try {
      window.sessionStorage.setItem(NOTE, JSON.stringify(note));
    } catch (error) {
      // No storage (a private window, a policy): the link still works.
    }
  }

  function recall() {
    var raw = null;
    try {
      raw = window.sessionStorage.getItem(NOTE);
      window.sessionStorage.removeItem(NOTE);
    } catch (error) {
      return null;
    }
    if (!raw) {
      return null;
    }
    var note = null;
    try {
      note = JSON.parse(raw);
    } catch (error) {
      return null;
    }
    if (!note || typeof note !== "object" || note.path !== window.location.pathname) {
      return null;
    }
    if (typeof note.at !== "number" || typeof note.index !== "number") {
      return null;
    }
    if (typeof note.text !== "string") {
      return null;
    }
    var age = Date.now() - note.at;
    if (age < 0 || age > MAX_AGE_MS) {
      return null;
    }
    return note;
  }

  function onClick(event) {
    if (event.defaultPrevented || event.button !== 0) {
      return;
    }
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }
    var link = linkOf(event.target);
    if (link) {
      remember(link);
    }
  }

  function onKey(event) {
    if (event.key !== "Delete" && event.key !== "Backspace") {
      return;
    }
    if (event.altKey || event.ctrlKey || event.metaKey) {
      return;
    }
    var link = linkOf(event.target);
    if (!link || !link.hasAttribute("data-filter-chip")) {
      return;
    }
    event.preventDefault();
    remember(link);
    window.location.assign(link.href);
  }

  function focusTarget(note) {
    var left = chips();
    if (note.index >= 0 && left.length > 0) {
      return left[Math.min(note.index, left.length - 1)];
    }
    var shown = document.querySelector(
      '#client-filters ul[aria-label="Show"] a[aria-current="true"]'
    );
    return shown || document.getElementById("q");
  }

  function settle(note) {
    var target = focusTarget(note);
    if (target) {
      target.focus();
    }
    var status = document.getElementById("filter-status");
    if (!status) {
      return;
    }
    var words = note.index < 0 ? "Every filter removed." : "Filter removed: " + note.text + ".";
    var shown = status.getAttribute("data-shown") || "";
    window.setTimeout(function () {
      status.textContent = shown ? words + " " + shown : words;
    }, SAY_AFTER_MS);
  }

  function ready() {
    document.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    var note = recall();
    if (note) {
      settle(note);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ready);
  } else {
    ready();
  }
})();
