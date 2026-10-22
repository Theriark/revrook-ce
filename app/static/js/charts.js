/*
 * revrook chart script (docs/design-system.md, Charts). Same origin, no eval, no
 * request of its own: a range is asked for through the vendored htmx, as the
 * control drawer does. Every chart is drawn by the server as SVG with a table of
 * its numbers, and without this script it all still works: a mark is a link to
 * its report, a segment is a link to its list, a range is a GET form, the title
 * of a mark is its native tooltip. The script adds:
 * - the tooltip (.rv-tip): one element, filled from data-tip of the mark under
 *   the pointer or the keyboard and moved beside it; hidden on leave, blur,
 *   Escape, scroll and resize;
 * - roving focus (data-roving): the marks of one chart are one tab stop; the
 *   arrow keys move between them, Home and End to the first and the last;
 * - the series toggles: each client of the legend becomes a pressed button;
 *   not pressed, its line, its marks and its rows are hidden in both drawings;
 * - the range (form.rv-range): the pressed button asks data-fragment for the
 *   body of the card and swaps it into data-target in place, then the address
 *   remembers the range (replaceState) so a reload shows it; a request that
 *   fails leaves for the page with that range, as the form would;
 * - the sparklines (data-spark): one tab stop each; the marks on them show
 *   their week and value under the pointer and under the arrow keys;
 * - a link to a row of a folded table (#domain-row-..., #source-...) opens the
 *   fold and focuses the row.
 */
(function () {
  "use strict";

  var TIP_CLASS = "rv-tip";
  var SHOWN = "is-shown";
  var ACTIVE = "is-active";
  var ENTER = "rv-chart-enter";
  var READY = "ready";
  var GAP = 10;
  var EDGE = 4;
  var NEXT_KEYS = ["ArrowRight", "ArrowDown"];
  var PREVIOUS_KEYS = ["ArrowLeft", "ArrowUp"];
  var tip = null;
  var tipFor = null;

  function closest(node, selector) {
    while (node && node !== document) {
      if (node.matches && node.matches(selector)) {
        return node;
      }
      node = node.parentNode;
    }
    return null;
  }

  // --- the tooltip --------------------------------------------------------------

  function tipElement() {
    if (tip) {
      return tip;
    }
    tip = document.createElement("div");
    tip.className = TIP_CLASS;
    tip.setAttribute("aria-hidden", "true");
    document.body.appendChild(tip);
    return tip;
  }

  // The words come from data-tip, one line per line; the mark's own title gives
  // a screen reader the same words, so the tooltip is hidden from it.
  function fillTip(text) {
    var box = tipElement();
    while (box.firstChild) {
      box.removeChild(box.firstChild);
    }
    var lines = text.split("\n");
    for (var k = 0; k < lines.length; k += 1) {
      var line = document.createElement("span");
      line.className = "rv-tip-line";
      line.textContent = lines[k];
      box.appendChild(line);
    }
  }

  // Above the mark, centred on it; below it when the top of the page is near;
  // never past an edge of the view. The position is set through the CSSOM,
  // which the content security policy permits (an inline style would not be).
  function placeTip(target) {
    var box = tipElement();
    var at = target.getBoundingClientRect();
    var size = box.getBoundingClientRect();
    var left = at.left + at.width / 2 - size.width / 2;
    var top = at.top - size.height - GAP;
    if (top < EDGE) {
      top = at.bottom + GAP;
    }
    var most = document.documentElement.clientWidth - size.width - EDGE;
    if (left > most) {
      left = most;
    }
    if (left < EDGE) {
      left = EDGE;
    }
    box.style.left = Math.round(left + window.scrollX) + "px";
    box.style.top = Math.round(top + window.scrollY) + "px";
  }

  function showTip(target) {
    var text = target.getAttribute("data-tip");
    if (!text) {
      return;
    }
    tipFor = target;
    fillTip(text);
    tipElement().classList.add(SHOWN);
    placeTip(target);
  }

  function hideTip() {
    tipFor = null;
    if (tip) {
      tip.classList.remove(SHOWN);
    }
  }

  function tipTargetOf(node) {
    return closest(node, "[data-tip]");
  }

  function pointerOver(event) {
    var target = tipTargetOf(event.target);
    if (target) {
      if (target !== tipFor) {
        showTip(target);
      }
      return;
    }
    if (tipFor && document.activeElement !== tipFor) {
      hideTip();
    }
  }

  function pointerOut(event) {
    if (!tipFor || document.activeElement === tipFor) {
      return;
    }
    if (tipTargetOf(event.relatedTarget) !== tipFor) {
      hideTip();
    }
  }

  // --- roving focus within a chart ----------------------------------------------

  function isShown(node, group) {
    var line = node;
    while (line && line !== group) {
      if (line.hasAttribute && line.hasAttribute("hidden")) {
        return false;
      }
      line = line.parentNode;
    }
    return true;
  }

  function stopsOf(group) {
    var all = group.querySelectorAll("a[data-tip]");
    var found = [];
    for (var k = 0; k < all.length; k += 1) {
      if (isShown(all[k], group)) {
        found.push(all[k]);
      }
    }
    return found;
  }

  // The first mark of a chart is the one tab stop; a hidden line's marks are
  // left out, and one that was switched off while focused gives the stop back
  // to the first shown.
  function prepareRoving(group) {
    var stops = stopsOf(group);
    var all = group.querySelectorAll("a[data-tip]");
    for (var k = 0; k < all.length; k += 1) {
      all[k].setAttribute("tabindex", "-1");
    }
    if (stops.length > 0) {
      stops[0].setAttribute("tabindex", "0");
    }
  }

  function stepOf(key, at, last) {
    if (NEXT_KEYS.indexOf(key) >= 0) {
      return at + 1;
    }
    if (PREVIOUS_KEYS.indexOf(key) >= 0) {
      return at - 1;
    }
    if (key === "Home") {
      return 0;
    }
    if (key === "End") {
      return last;
    }
    return null;
  }

  function rovingKey(group, event) {
    var stops = stopsOf(group);
    var at = stops.indexOf(document.activeElement);
    if (at < 0) {
      return;
    }
    var to = stepOf(event.key, at, stops.length - 1);
    if (to === null || to < 0 || to >= stops.length) {
      return;
    }
    event.preventDefault();
    stops[at].setAttribute("tabindex", "-1");
    stops[to].setAttribute("tabindex", "0");
    stops[to].focus();
  }

  // --- the series toggles -------------------------------------------------------

  function buildSeries(list) {
    var items = list.querySelectorAll("li[data-series]");
    for (var k = 0; k < items.length; k += 1) {
      var item = items[k];
      if (item.querySelector("button")) {
        continue;
      }
      var button = document.createElement("button");
      button.type = "button";
      button.className = "rv-series";
      button.setAttribute("aria-pressed", "true");
      while (item.firstChild) {
        button.appendChild(item.firstChild);
      }
      item.appendChild(button);
    }
  }

  function cardOf(node) {
    return closest(node, ".rv-card") || document.body;
  }

  // Off: the line and its marks in both drawings and its rows in the table carry
  // the hidden attribute (an SVG group has no hidden property; the stylesheet
  // hides what carries the attribute). The tab stops of the charts are set again,
  // so focus never lands on a mark that is not drawn.
  function toggleSeries(button) {
    var item = button.parentNode;
    var id = item.getAttribute("data-series");
    var card = cardOf(item);
    var off = button.getAttribute("aria-pressed") === "true";
    button.setAttribute("aria-pressed", off ? "false" : "true");
    var parts = card.querySelectorAll('[data-series="' + id + '"]');
    for (var k = 0; k < parts.length; k += 1) {
      if (parts[k] === item) {
        continue;
      }
      if (off) {
        parts[k].setAttribute("hidden", "");
      } else {
        parts[k].removeAttribute("hidden");
      }
    }
    var groups = card.querySelectorAll("[data-roving]");
    for (var n = 0; n < groups.length; n += 1) {
      prepareRoving(groups[n]);
    }
    hideTip();
  }

  // --- the range of a chart -----------------------------------------------------

  function rememberRange(name, value) {
    if (!window.history || !window.history.replaceState) {
      return;
    }
    var address = new URL(window.location.href);
    address.searchParams.set(name, value);
    window.history.replaceState(window.history.state, "", address.href);
  }

  function animate(target) {
    var charts = target.querySelectorAll(".rv-chart");
    for (var k = 0; k < charts.length; k += 1) {
      charts[k].classList.add(ENTER);
    }
  }

  function animationDone(event) {
    if (event.target && event.target.classList) {
      event.target.classList.remove(ENTER);
    }
  }

  function rangeSubmit(event) {
    var form = event.target;
    if (!form || !form.classList || !form.classList.contains("rv-range")) {
      return;
    }
    var button = event.submitter;
    var fragment = form.getAttribute("data-fragment");
    var targetId = form.getAttribute("data-target");
    var target = targetId ? document.getElementById(targetId) : null;
    if (!button || !fragment || !target || !window.htmx || !window.htmx.ajax) {
      return;
    }
    event.preventDefault();
    var name = button.name;
    var value = button.value;
    var query = encodeURIComponent(name) + "=" + encodeURIComponent(value);
    var page = form.getAttribute("action") + "?" + query;
    hideTip();
    target.setAttribute("aria-busy", "true");
    var pending = window.htmx.ajax("GET", fragment + "?" + query, {
      target: "#" + targetId,
      source: form
    });
    function arrived() {
      target.removeAttribute("aria-busy");
      rememberRange(name, value);
      prepare(target);
      animate(target);
      var pressed = target.querySelector('.rv-range button[aria-pressed="true"]');
      if (pressed) {
        pressed.focus({ preventScroll: true });
      }
    }
    function failed() {
      target.removeAttribute("aria-busy");
      window.location.assign(page);
    }
    if (pending && typeof pending.then === "function") {
      pending.then(arrived, failed);
    } else {
      failed();
    }
  }

  // --- the sparklines -----------------------------------------------------------

  function sparkOf(node) {
    return closest(node, "[data-spark]");
  }

  function sparkMarks(spark) {
    return spark.querySelectorAll(".rv-spark-mark");
  }

  function sparkIndex(spark) {
    var marks = sparkMarks(spark);
    var at = parseInt(spark.getAttribute("data-active") || "", 10);
    if (isNaN(at) || at < 0 || at >= marks.length) {
      at = marks.length - 1;
    }
    return at;
  }

  function showSparkMark(spark, at) {
    var marks = sparkMarks(spark);
    if (marks.length === 0) {
      return;
    }
    for (var k = 0; k < marks.length; k += 1) {
      marks[k].classList.toggle(ACTIVE, k === at);
    }
    spark.setAttribute("data-active", String(at));
    showTip(marks[at]);
  }

  function clearSpark(node) {
    var spark = sparkOf(node);
    if (!spark) {
      return;
    }
    var marks = sparkMarks(spark);
    for (var k = 0; k < marks.length; k += 1) {
      marks[k].classList.remove(ACTIVE);
    }
  }

  function sparkKey(spark, event) {
    var marks = sparkMarks(spark);
    if (marks.length === 0) {
      return;
    }
    var to = stepOf(event.key, sparkIndex(spark), marks.length - 1);
    if (to === null || to < 0 || to >= marks.length) {
      return;
    }
    event.preventDefault();
    showSparkMark(spark, to);
  }

  // --- a link into a folded table -----------------------------------------------

  function openFold(event) {
    var link = closest(event.target, "[data-roving] a[href^='#']");
    if (!link) {
      return;
    }
    var row = document.getElementById(link.getAttribute("href").slice(1));
    if (!row) {
      return;
    }
    var fold = closest(row, "details");
    if (fold) {
      fold.open = true;
    }
    hideTip();
    row.focus();
  }

  // --- wiring -------------------------------------------------------------------

  function prepare(root) {
    var legends = root.querySelectorAll(".rv-chart-legend");
    for (var k = 0; k < legends.length; k += 1) {
      buildSeries(legends[k]);
    }
    var groups = root.querySelectorAll("[data-roving]");
    for (var n = 0; n < groups.length; n += 1) {
      prepareRoving(groups[n]);
    }
    document.documentElement.setAttribute("data-charts", READY);
  }

  function clicked(event) {
    var button = closest(event.target, "button.rv-series");
    if (button) {
      toggleSeries(button);
      return;
    }
    openFold(event);
  }

  function focused(event) {
    var target = tipTargetOf(event.target);
    if (target) {
      showTip(target);
      return;
    }
    var spark = sparkOf(event.target);
    if (spark) {
      showSparkMark(spark, sparkIndex(spark));
    }
  }

  function blurred(event) {
    hideTip();
    clearSpark(event.target);
  }

  function keyPressed(event) {
    if (event.key === "Escape") {
      hideTip();
      return;
    }
    var spark = sparkOf(event.target);
    if (spark) {
      sparkKey(spark, event);
      return;
    }
    var group = closest(event.target, "[data-roving]");
    if (group) {
      rovingKey(group, event);
    }
  }

  function swapped(event) {
    if (event.target && event.target.querySelectorAll) {
      prepare(event.target);
    }
  }

  function ready() {
    document.addEventListener("pointerover", pointerOver);
    document.addEventListener("pointerout", pointerOut);
    document.addEventListener("focusin", focused);
    document.addEventListener("focusout", blurred);
    document.addEventListener("keydown", keyPressed);
    document.addEventListener("click", clicked);
    document.addEventListener("submit", rangeSubmit);
    document.addEventListener("animationend", animationDone);
    document.addEventListener("htmx:afterSwap", swapped);
    window.addEventListener("scroll", hideTip, { passive: true });
    window.addEventListener("resize", hideTip);
    prepare(document);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ready);
  } else {
    ready();
  }
})();
