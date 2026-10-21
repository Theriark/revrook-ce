/*
 * revrook shell script (docs/design-system.md). Same origin, no eval, no network.
 * Two decorations, neither needed for a page to work:
 * - the drag-and-drop import area: the file input covers the whole area, so
 *   dropping and choosing a file work without this script; it adds the drag-over
 *   state and shows the names of the chosen files;
 * - the strips that scroll sideways (the main navigation below 1024px, the client
 *   tabs): it marks a strip data-scroll-end="true" while nothing lies to the right
 *   of what is in view, so the stylesheet hides the fade at its edge; without the
 *   script the fade stays.
 */
(function () {
  "use strict";

  // The space after the last link of a strip (revrook-retest.css): with only that
  // space left to scroll, the strip is at its end. One pixel of slack covers a
  // fractional scroll position.
  var STRIP_TAIL = 48;

  function decorate(zone) {
    var input = zone.querySelector('input[type="file"]');
    var output = zone.querySelector(".rv-dropzone-file");
    if (!input) {
      return;
    }
    function show() {
      var names = [];
      var files = input.files || [];
      for (var k = 0; k < files.length; k += 1) {
        names.push(files[k].name);
      }
      zone.classList.toggle("has-file", names.length > 0);
      if (output) {
        output.textContent = names.join(", ");
      }
    }
    ["dragenter", "dragover"].forEach(function (type) {
      zone.addEventListener(type, function () {
        zone.classList.add("is-dragover");
      });
    });
    ["dragleave", "drop"].forEach(function (type) {
      zone.addEventListener(type, function () {
        zone.classList.remove("is-dragover");
      });
    });
    input.addEventListener("change", show);
    show();
  }

  function watchStrip(strip) {
    var scroller = strip.querySelector("nav");
    if (!scroller) {
      return;
    }
    function update() {
      var remaining =
        scroller.scrollWidth - scroller.clientWidth - scroller.scrollLeft;
      strip.setAttribute(
        "data-scroll-end",
        remaining <= STRIP_TAIL + 1 ? "true" : "false"
      );
    }
    scroller.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    // The fonts may arrive after the script: measure again when the page is loaded.
    window.addEventListener("load", update);
    update();
  }

  function ready() {
    var zones = document.querySelectorAll(".rv-dropzone");
    for (var k = 0; k < zones.length; k += 1) {
      decorate(zones[k]);
    }
    var strips = document.querySelectorAll(".rv-nav-strip, .rv-tabs-strip");
    for (var n = 0; n < strips.length; n += 1) {
      watchStrip(strips[n]);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ready);
  } else {
    ready();
  }
})();
