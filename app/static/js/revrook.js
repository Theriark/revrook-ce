/*
 * revrook shell script (docs/design-system.md). Same origin, no eval, no network.
 * It only decorates the drag-and-drop import area: the file input covers the whole
 * area, so dropping and choosing a file work without this script; it adds the
 * drag-over state and shows the names of the chosen files.
 */
(function () {
  "use strict";

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

  function ready() {
    var zones = document.querySelectorAll(".rv-dropzone");
    for (var k = 0; k < zones.length; k += 1) {
      decorate(zones[k]);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ready);
  } else {
    ready();
  }
})();
