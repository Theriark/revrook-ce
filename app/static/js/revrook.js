/*
 * revrook shell script (docs/design-system.md). Same origin, no eval, no network.
 * Three decorations, none needed for a page to work:
 * - the drag-and-drop import area: the file input covers the whole area, so
 *   dropping and choosing a file work without this script; it adds the drag-over
 *   state and shows the names of the chosen files;
 * - the strips that scroll sideways (the main navigation below 1024px, the client
 *   tabs): it marks a strip data-scroll-end="true" while nothing lies to the right
 *   of what is in view, so the stylesheet hides the fade at its edge; without the
 *   script the fade stays;
 * - the message a form leaves after its redirect (?done=added, ?saved=1): it
 *   moves focus to the message, so a screen reader reads it, and takes the query
 *   out of the address, so a reload does not repeat it; without the script the
 *   message still shows after the redirect, and the query stays;
 * - the message a fragment brings when htmx swaps it in (the profile editor:
 *   the profile saved, the file imported): focus moves to it and it is scrolled
 *   to the top of the view; without the script (and so without htmx) the server
 *   draws the whole page with the result in place.
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

  function watchStrip(strip) {
    var scroller = strip.querySelector("nav");
    if (!scroller) {
      return;
    }
    // The strip is at its end once the right edge of its last link is inside
    // the visible box of the scroller. Measured, not assumed: the space after
    // the last link (revrook-retest.css), the gap before that space and the end
    // padding of the scroller (16px on the navigation bar, none on the tabs)
    // count as they are, so no constant can drift from the stylesheet. One
    // pixel of slack covers a fractional scroll position.
    function update() {
      var links = scroller.querySelectorAll("a");
      var atEnd = true;
      if (links.length > 0) {
        var last = links[links.length - 1].getBoundingClientRect();
        var box = scroller.getBoundingClientRect();
        var edge = box.left + scroller.clientLeft + scroller.clientWidth;
        atEnd = last.right <= edge + 1;
      }
      strip.setAttribute("data-scroll-end", atEnd ? "true" : "false");
    }
    scroller.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    // The fonts may arrive after the script: measure again when the page is loaded.
    window.addEventListener("load", update);
    update();
  }

  // A message rendered with the page (role="status") is often not read out when
  // the page loads: focus moves to it (the template gives it tabindex="-1"), and
  // the query named in data-clear-query is removed from the address in place.
  function announce(message) {
    var name = message.getAttribute("data-clear-query");
    message.focus();
    if (!name || !window.history || !window.history.replaceState) {
      return;
    }
    var address = new URL(window.location.href);
    if (address.searchParams.has(name)) {
      address.searchParams.delete(name);
      window.history.replaceState(window.history.state, "", address.href);
    }
  }

  // A message that arrives inside a swapped fragment sits below the form that
  // sent it, and the button that was pressed went with the swap, so focus fell
  // to the page and at 390px the result of an import stayed off screen. The
  // fragment marks its message data-announce (with tabindex="-1"): focus moves
  // to it, then it is scrolled to the top of the view (scroll-margin-top in
  // revrook-retest.css keeps the heading of its card in view).
  function announceSwapped(event) {
    var target = event.target;
    if (!target || !target.querySelector) {
      return;
    }
    var message = target.querySelector("[data-announce]");
    if (!message) {
      return;
    }
    message.focus({ preventScroll: true });
    message.scrollIntoView({ block: "start" });
  }

  function ready() {
    document.addEventListener("htmx:afterSwap", announceSwapped);
    var zones = document.querySelectorAll(".rv-dropzone");
    for (var k = 0; k < zones.length; k += 1) {
      decorate(zones[k]);
    }
    var strips = document.querySelectorAll(".rv-nav-strip, .rv-tabs-strip");
    for (var n = 0; n < strips.length; n += 1) {
      watchStrip(strips[n]);
    }
    var messages = document.querySelectorAll("[data-clear-query]");
    if (messages.length > 0) {
      announce(messages[0]);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ready);
  } else {
    ready();
  }
})();
