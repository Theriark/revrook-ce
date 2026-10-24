/*
 * revrook shell script (docs/design-system.md). Same origin, no eval, no network.
 * Decorations, none needed for a page to work:
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
 *   draws the whole page with the result in place;
 * - the regions that scroll sideways (the exceptions register, the counts and
 *   the preview of an import): the template gives each tabindex="0", so the
 *   keyboard always reaches a region that scrolls; the script takes that tab
 *   stop away while the content fits its box (card rows, a short table) and
 *   gives it back when the content overflows (a resize, a swap);
 * - the control drawer (templates/_drawer.html): a link marked data-drawer on the
 *   checklist, the home page or the client overview opens the native dialog at
 *   the right edge and asks htmx to put the control into it (the server answers
 *   the drawer target with the control without its shell); focus moves to the
 *   title of the control and goes back to the link when the drawer closes. A
 *   click with a modifier key, a middle click, a browser without dialogs, a page
 *   without htmx, a failed request: all leave the link as it is, the page itself.
 * - the theme switch (templates/_theme.html): the choice is applied the moment a
 *   button is pressed and htmx posts it; if the server refuses the post (a
 *   session that ended, 403; a value it does not know, 422) or the request
 *   fails, the theme goes back to the one in use, since nothing was remembered;
 *   without the script the form posts and the page comes back in the chosen
 *   theme.
 * - the rail fold (templates/_rail.html): from 1024px the rail folds to its
 *   icons the moment the button is pressed and htmx posts the form; a refused
 *   or failed post puts the rail back, since nothing was remembered; without
 *   the script the form posts and the page comes back with the rail as chosen.
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

  // A region with tabindex="0" is one more tab stop even when nothing scrolls:
  // the exceptions are cards from 768px to 1279px, a short table fits its box.
  // The region keeps the tab stop only while its box clips (overflow-x auto or
  // scroll, as .rv-table-scroll sets it; from 1280px the exceptions region is
  // visible, and then the page scrolls, not the box) and the content is wider
  // than the box. A region that holds focus keeps it until focus moves on.
  function updateRegions() {
    var regions = document.querySelectorAll('.rv-table-scroll[role="region"]');
    for (var k = 0; k < regions.length; k += 1) {
      var region = regions[k];
      var overflow = window.getComputedStyle(region).overflowX;
      var clips = overflow === "auto" || overflow === "scroll";
      if (clips && region.scrollWidth > region.clientWidth) {
        region.setAttribute("tabindex", "0");
      } else if (region !== document.activeElement) {
        region.removeAttribute("tabindex");
      }
    }
  }

  // The control drawer. The link that opened it is kept so focus can return to
  // it; the dialog is modal (showModal), so Escape closes it, Tab stays inside and
  // the page behind is inert. While the control loads the dialog carries aria-busy
  // and the stylesheet shows the skeleton in place of the body.
  var DRAWER_BODY = "control-drawer-body";
  var drawerOpener = null;

  function drawerOf() {
    return document.getElementById("control-drawer");
  }

  function drawerLinkOf(event) {
    if (event.defaultPrevented || event.button !== 0) {
      return null;
    }
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return null;
    }
    var node = event.target;
    while (node && node !== document) {
      if (node.tagName === "A" && node.hasAttribute("data-drawer")) {
        return node;
      }
      node = node.parentNode;
    }
    return null;
  }

  function leaveForPage(link) {
    var dialog = drawerOf();
    if (dialog && dialog.open) {
      dialog.close();
    }
    window.location.assign(link.href);
  }

  function openDrawer(event) {
    var link = drawerLinkOf(event);
    var dialog = drawerOf();
    if (!link || !dialog || !window.htmx || !window.htmx.ajax) {
      return;
    }
    event.preventDefault();
    drawerOpener = link;
    dialog.setAttribute("aria-busy", "true");
    dialog.removeAttribute("aria-labelledby");
    if (!dialog.open) {
      dialog.showModal();
    }
    var pending = window.htmx.ajax("GET", link.getAttribute("href"), {
      source: link,
      target: "#" + DRAWER_BODY
    });
    if (pending && typeof pending.catch === "function") {
      pending.catch(function () {
        leaveForPage(link);
      });
    }
  }

  // The control arrived: the dialog is named by its title, which takes focus.
  // A refusal (the short message the server sends htmx) has no title: focus
  // goes to the Close button, so the keyboard is never left on the inert page.
  function drawerLoaded(event) {
    var body = event.target;
    if (!body || body.id !== DRAWER_BODY) {
      return;
    }
    var dialog = drawerOf();
    if (!dialog) {
      return;
    }
    dialog.removeAttribute("aria-busy");
    var scroll = dialog.querySelector(".rv-drawer-scroll");
    if (scroll) {
      scroll.scrollTop = 0;
    }
    var title = body.querySelector("#control-drawer-title");
    if (title) {
      dialog.setAttribute("aria-labelledby", "control-drawer-title");
      title.focus({ preventScroll: true });
      return;
    }
    var close = dialog.querySelector(".rv-drawer-close");
    if (close) {
      close.focus();
    }
  }

  // The request could not be made or the answer was not a page (a gateway error,
  // a timeout): the page itself is the fallback, so the person still gets there.
  function drawerFailed(event) {
    var link = event.target;
    if (link && link.hasAttribute && link.hasAttribute("data-drawer")) {
      leaveForPage(link);
    }
  }

  // Closed: the body is emptied, so the next open starts from the skeleton and
  // never from the previous control. It also keeps the console clean: a swap
  // into a body that still holds the same ids (the four note fields) makes htmx
  // copy attributes between the old and the new elements, and the content
  // security policy logs each of those as an inline style it blocked.
  function drawerClosed() {
    var dialog = drawerOf();
    if (dialog) {
      dialog.removeAttribute("aria-busy");
    }
    var body = document.getElementById(DRAWER_BODY);
    if (body && typeof body.replaceChildren === "function") {
      body.replaceChildren();
    }
    if (drawerOpener && document.body.contains(drawerOpener)) {
      drawerOpener.focus();
    }
    drawerOpener = null;
  }

  // The dialog has no padding and its panel fills it, so a click that reaches the
  // dialog itself landed on the veil beside it.
  function closeOnVeil(event) {
    var dialog = drawerOf();
    if (dialog && event.target === dialog) {
      dialog.close();
    }
  }

  function watchDrawer() {
    var dialog = drawerOf();
    if (!dialog || typeof dialog.showModal !== "function") {
      return;
    }
    document.addEventListener("click", openDrawer);
    dialog.addEventListener("click", closeOnVeil);
    dialog.addEventListener("close", drawerClosed);
    document.addEventListener("htmx:afterSwap", drawerLoaded);
    document.addEventListener("htmx:responseError", drawerFailed);
    document.addEventListener("htmx:sendError", drawerFailed);
  }

  // The theme switch (_theme.html): the choice is applied the moment a button
  // is pressed, so the page does not wait for the answer; htmx then posts the
  // form (hx-post, nothing swapped) and the server remembers it. The root
  // element carries the theme, the color-scheme meta follows it (form controls
  // and scrollbars), and the pressed button moves. Without script the form
  // posts and the page comes back in the chosen theme.
  var COLOR_SCHEMES = { light: "light", dark: "dark", system: "light dark" };
  // The theme the server drew the page in, or the last one it accepted: the
  // one to go back to when a post is refused (the page's response handling
  // treats 403 and 422 as answers, not errors, so afterRequest is the signal).
  var themeKept = null;

  function setTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    var meta = document.querySelector('meta[name="color-scheme"]');
    if (meta) {
      meta.setAttribute("content", COLOR_SCHEMES[theme]);
    }
    var buttons = document.querySelectorAll('.rv-theme button[name="theme"]');
    for (var k = 0; k < buttons.length; k += 1) {
      buttons[k].setAttribute("aria-pressed", buttons[k].value === theme ? "true" : "false");
    }
  }

  function themeButtonOf(event) {
    var node = event.target;
    while (node && node !== document) {
      if (node.tagName === "BUTTON" && node.name === "theme") {
        return node.form && node.form.classList.contains("rv-theme") ? node : null;
      }
      node = node.parentNode;
    }
    return null;
  }

  function applyTheme(event) {
    var button = themeButtonOf(event);
    if (!button || !COLOR_SCHEMES[button.value]) {
      return;
    }
    if (themeKept === null) {
      themeKept = document.documentElement.getAttribute("data-theme") || "system";
    }
    setTheme(button.value);
  }

  // The post of the switch came back: accepted (204), the choice is the one to
  // keep from now on; refused (403, 422) or failed (no answer), the page goes
  // back to the theme it had, since the server remembered nothing. The status
  // is read from the request itself: the page's response handling marks 403
  // and 422 as answers rather than errors, so htmx reports them as successful.
  function themePosted(event) {
    var form = event.target;
    if (!form || !form.classList || !form.classList.contains("rv-theme")) {
      return;
    }
    var detail = event.detail || {};
    var status = detail.xhr ? detail.xhr.status : 0;
    if (event.type === "htmx:afterRequest" && status >= 200 && status < 300) {
      themeKept = document.documentElement.getAttribute("data-theme") || "system";
      return;
    }
    if (themeKept !== null && COLOR_SCHEMES[themeKept]) {
      setTheme(themeKept);
    }
  }

  // The rail fold (_rail.html): the body carries data-rail, the button says
  // which state it asks for in its value and names the other one once pressed.
  var RAILS = { expanded: "expanded", compact: "compact" };
  var RAIL_WORDS = { expanded: "Fold the rail", compact: "Open the rail" };
  var railKept = null;

  function setRail(rail) {
    document.body.setAttribute("data-rail", rail);
    var buttons = document.querySelectorAll('.rv-rail-form button[name="rail"]');
    for (var k = 0; k < buttons.length; k += 1) {
      var other = rail === "compact" ? "expanded" : "compact";
      buttons[k].value = other;
      buttons[k].setAttribute("aria-expanded", rail === "compact" ? "false" : "true");
      buttons[k].setAttribute("aria-label", RAIL_WORDS[rail]);
      buttons[k].setAttribute("title", RAIL_WORDS[rail]);
    }
  }

  function railButtonOf(event) {
    var node = event.target;
    while (node && node !== document) {
      if (node.tagName === "BUTTON" && node.name === "rail") {
        return node.form && node.form.classList.contains("rv-rail-form") ? node : null;
      }
      node = node.parentNode;
    }
    return null;
  }

  function applyRail(event) {
    var button = railButtonOf(event);
    if (!button || !RAILS[button.value]) {
      return;
    }
    if (railKept === null) {
      railKept = document.body.getAttribute("data-rail") || "expanded";
    }
    setRail(button.value);
  }

  function railPosted(event) {
    var form = event.target;
    if (!form || !form.classList || !form.classList.contains("rv-rail-form")) {
      return;
    }
    var detail = event.detail || {};
    var status = detail.xhr ? detail.xhr.status : 0;
    if (event.type === "htmx:afterRequest" && status >= 200 && status < 300) {
      railKept = document.body.getAttribute("data-rail") || "expanded";
      return;
    }
    if (railKept !== null && RAILS[railKept]) {
      setRail(railKept);
    }
  }

  function ready() {
    watchDrawer();
    document.addEventListener("click", applyTheme);
    document.addEventListener("click", applyRail);
    document.addEventListener("htmx:afterRequest", themePosted);
    document.addEventListener("htmx:afterRequest", railPosted);
    document.addEventListener("htmx:sendError", themePosted);
    document.addEventListener("htmx:sendError", railPosted);
    document.addEventListener("htmx:afterSwap", announceSwapped);
    document.addEventListener("htmx:afterSwap", updateRegions);
    window.addEventListener("resize", updateRegions);
    window.addEventListener("load", updateRegions);
    updateRegions();
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
