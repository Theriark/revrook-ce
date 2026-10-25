/*
 * revrook bulk actions of the clients list (THE-1189, docs/design-system.md,
 * Bulk actions). The list works without this script: every row keeps its own
 * links. With it, a select box opens on every row, one box selects the page, and
 * a bar under the table acts on the clients chosen, one after another, with the
 * actions the application already has:
 *   - Make reports: the report builder's POST /clients/<id>/reports/snapshot
 *     (the last full quarter, as the builder does without dates);
 *   - Download as CSV: the rows on the page, made in the browser;
 *   - Delete: the System page's POST /system/clients/<id>/delete, after a dialog
 *     that asks for the name of every client, as that page does. The server
 *     checks the name again; nothing is deleted on a mismatch.
 * Every request is same-origin and carries the CSRF token of the page. No markup
 * is built from text: names are set with textContent only.
 */
(function () {
  "use strict";

  var MAX_DELETE = 10;
  var CHECK_MARK = String.fromCharCode(0x2713);
  // A byte order mark first, so a spreadsheet reads the file as UTF-8.
  var BOM = String.fromCharCode(0xfeff);
  var table = document.querySelector("[data-bulk-table]");
  var bar = document.getElementById("bulk-bar");
  var count = document.getElementById("bulk-count");
  var result = document.getElementById("bulk-result");
  var dialog = document.getElementById("bulk-dialog");
  var selectRow = document.getElementById("bulk-select");
  var all = document.getElementById("bulk-all");
  if (!table || !bar || !count || !result || !dialog || !selectRow || !all) {
    return;
  }
  if (typeof dialog.showModal !== "function") {
    return;
  }
  var csrf = table.getAttribute("data-csrf") || "";
  var busy = false;
  var opener = null;

  function rows() {
    return Array.prototype.slice.call(table.querySelectorAll("tr[data-bulk-row]"));
  }

  function boxOf(row) {
    return row.querySelector("input[data-bulk-pick]");
  }

  function chosen() {
    return rows().filter(function (row) {
      var box = boxOf(row);
      return box && box.checked;
    });
  }

  function idOf(row) {
    var value = row.getAttribute("data-bulk-row") || "";
    return /^[0-9]+$/.test(value) ? value : "";
  }

  function nameOf(row) {
    return row.getAttribute("data-name") || "";
  }

  function plural(number, one, many) {
    return number + " " + (number === 1 ? one : many);
  }

  function update() {
    var picked = chosen();
    var total = rows().length;
    rows().forEach(function (row) {
      row.classList.toggle("is-chosen", Boolean(boxOf(row) && boxOf(row).checked));
    });
    all.checked = total > 0 && picked.length === total;
    all.indeterminate = picked.length > 0 && picked.length < total;
    bar.hidden = picked.length === 0;
    count.textContent = picked.length
      ? plural(picked.length, "client", "clients") + " selected"
      : "No client selected";
    bar.querySelectorAll("[data-bulk-command]").forEach(function (button) {
      var action = button.getAttribute("data-bulk-command");
      var tooMany = action === "delete" && picked.length > MAX_DELETE;
      button.disabled = busy || (action !== "clear" && picked.length === 0) || tooMany;
      if (action === "delete") {
        button.textContent = tooMany ? "Delete (" + MAX_DELETE + " at most)" : "Delete";
      }
    });
  }

  function clearChildren(element) {
    while (element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  // --- the result, in the dock above the bar ---------------------------------------

  // The result stays in view at the foot of the window until it is dismissed or the
  // next action replaces it.
  function report(title, lines) {
    clearChildren(result);
    var head = document.createElement("div");
    head.className = "rv-bulk-result-head";
    var heading = document.createElement("p");
    heading.className = "rv-bulk-result-title";
    heading.textContent = title;
    head.appendChild(heading);
    var dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.className = "rv-button-quiet rv-button-small";
    dismiss.setAttribute("data-bulk-dismiss", "");
    dismiss.textContent = "Dismiss";
    head.appendChild(dismiss);
    result.appendChild(head);
    if (lines.length) {
      var list = document.createElement("ul");
      lines.forEach(function (line) {
        var item = document.createElement("li");
        item.className = line.ok ? "rv-bulk-ok" : "rv-bulk-failed";
        var mark = document.createElement("span");
        mark.className = "rv-bulk-mark";
        mark.setAttribute("aria-hidden", "true");
        mark.textContent = line.ok ? CHECK_MARK : "!";
        item.appendChild(mark);
        var words = document.createElement("span");
        words.textContent = line.text + " ";
        item.appendChild(words);
        if (line.href) {
          var link = document.createElement("a");
          link.href = line.href;
          link.textContent = line.link;
          item.appendChild(link);
        }
        list.appendChild(item);
      });
      result.appendChild(list);
    }
  }

  function progress(text) {
    clearChildren(result);
    var line = document.createElement("p");
    line.className = "rv-bulk-result-title";
    var spinner = document.createElement("span");
    spinner.className = "rv-busy";
    spinner.setAttribute("aria-hidden", "true");
    line.appendChild(spinner);
    line.appendChild(document.createTextNode(" " + text));
    result.appendChild(line);
  }

  // The message of a refusal: the problem page names it (problem.html).
  function reasonOf(response) {
    return response
      .text()
      .then(function (text) {
        var page = new DOMParser().parseFromString(text, "text/html");
        var message = page.querySelector(".rv-problem-message");
        var said = message ? message.textContent.trim() : "";
        return said || "The server answered " + response.status + ".";
      })
      .catch(function () {
        return "The server answered " + response.status + ".";
      });
  }

  function post(path, fields) {
    var body = new URLSearchParams();
    body.append("csrf_token", csrf);
    Object.keys(fields).forEach(function (key) {
      body.append(key, fields[key]);
    });
    return window.fetch(path, {
      method: "POST",
      body: body,
      credentials: "same-origin",
      redirect: "follow",
      headers: { "X-CSRF-Token": csrf },
    });
  }

  // One client after another, so the bar reads "2 of 5" and a refusal of one does
  // not stop the others.
  function runAll(list, step, title, done) {
    var lines = [];
    busy = true;
    update();
    var chain = Promise.resolve();
    list.forEach(function (row, index) {
      chain = chain.then(function () {
        progress(title + " " + (index + 1) + " of " + list.length + ": " + nameOf(row));
        return step(row).then(
          function (line) {
            lines.push(line);
          },
          function () {
            lines.push({ ok: false, text: nameOf(row) + ": the request did not reach the server." });
          }
        );
      });
    });
    return chain.then(function () {
      busy = false;
      done(lines);
      update();
    });
  }

  // --- the actions -----------------------------------------------------------------

  function makeReports(list) {
    return runAll(
      list,
      function (row) {
        var id = idOf(row);
        return post("/clients/" + id + "/reports/snapshot", {}).then(function (response) {
          var path = new URL(response.url, window.location.href).pathname;
          if (path === "/login") {
            return { ok: false, text: nameOf(row) + ": no report. The session ended; sign in again." };
          }
          var made = response.ok && new RegExp("^/clients/" + id + "/reports/[0-9]+$").test(path);
          if (made) {
            return { ok: true, text: nameOf(row) + ": report made.", href: path, link: "Open the report" };
          }
          return reasonOf(response).then(function (reason) {
            return { ok: false, text: nameOf(row) + ": no report. " + reason };
          });
        });
      },
      "Making report",
      function (lines) {
        var made = lines.filter(function (line) {
          return line.ok;
        }).length;
        report(
          plural(made, "report", "reports") + " made of " + lines.length + ". The last report column changes when the list is loaded again.",
          lines
        );
      }
    );
  }

  function deleteClients(list, typed) {
    return runAll(
      list,
      function (row) {
        var id = idOf(row);
        var name = typed[id] || "";
        return post("/system/clients/" + id + "/delete", { confirm: name }).then(function (response) {
          // A deletion answers with a redirect to /system?deleted=1; a session
          // that ended answers with one to the sign-in page, which is no deletion.
          var landed = new URL(response.url, window.location.href);
          if (landed.pathname === "/login") {
            return { ok: false, text: nameOf(row) + ": not deleted. The session ended; sign in again." };
          }
          if (response.ok && landed.pathname === "/system" && landed.searchParams.get("deleted") === "1") {
            row.parentNode.removeChild(row);
            return { ok: true, text: nameOf(row) + ": deleted, with its evidence, reports and files." };
          }
          return reasonOf(response).then(function (reason) {
            return { ok: false, text: nameOf(row) + ": not deleted. " + reason };
          });
        });
      },
      "Deleting",
      function (lines) {
        var gone = lines.filter(function (line) {
          return line.ok;
        }).length;
        report(plural(gone, "client", "clients") + " deleted of " + lines.length + ". Only the audit entries remain.", lines);
        // The rows go at once, but the counts of the chips, the chart of the bands
        // and the pages were made by the server before; only a new list is current.
        if (gone) {
          var again = document.createElement("p");
          var link = document.createElement("a");
          link.href = window.location.pathname + window.location.search;
          link.textContent = "Load the list again";
          again.appendChild(document.createTextNode("The counts above still include the deleted clients. "));
          again.appendChild(link);
          again.appendChild(document.createTextNode(" to update them."));
          result.appendChild(again);
        }
      }
    );
  }

  function cell(value) {
    var text = String(value);
    // A cell that starts like a formula is read as text by a spreadsheet.
    if (/^[=+\-@\t\r]/.test(text)) {
      text = "'" + text;
    }
    return '"' + text.replace(/"/g, '""') + '"';
  }

  function downloadCsv(list) {
    var lines = [["Client", "Score at last report", "Band at last report", "Last report", "Newest evidence", "Exports"]];
    list.forEach(function (row) {
      lines.push([
        nameOf(row),
        row.getAttribute("data-score") || "",
        row.getAttribute("data-band") || "",
        row.getAttribute("data-report-day") || "",
        row.getAttribute("data-newest") || "",
        row.getAttribute("data-exports") || "0",
      ]);
    });
    var text = lines
      .map(function (line) {
        return line.map(cell).join(",");
      })
      .join("\r\n");
    var blob = new Blob([BOM + text + "\r\n"], { type: "text/csv;charset=utf-8" });
    var link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "revrook-clients-" + new Date().toISOString().slice(0, 10) + ".csv";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.setTimeout(function () {
      URL.revokeObjectURL(link.href);
    }, 1000);
    report("Downloaded " + plural(list.length, "row", "rows") + " as CSV.", []);
  }

  // --- the dialog ------------------------------------------------------------------

  var title = document.getElementById("bulk-dialog-title");
  var text = document.getElementById("bulk-dialog-text");
  var names = document.getElementById("bulk-dialog-list");
  var note = document.getElementById("bulk-dialog-note");
  var confirm = dialog.querySelector("[data-bulk-confirm]");
  var pending = null;

  function openDialog(options) {
    title.textContent = options.title;
    text.textContent = options.text;
    clearChildren(names);
    note.hidden = true;
    note.textContent = "";
    confirm.textContent = options.confirm;
    confirm.className = options.danger ? "rv-button-danger" : "";
    pending = options;
    // A dialog closed with Escape keeps the last returnValue: start from none.
    dialog.returnValue = "";
    options.fill(names);
    dialog.showModal();
    var first = names.querySelector("input");
    (first || confirm).focus();
  }

  function deleteFields(list) {
    return function (container) {
      list.forEach(function (row) {
        var item = document.createElement("li");
        var label = document.createElement("label");
        var id = "bulk-confirm-" + idOf(row);
        label.setAttribute("for", id);
        label.textContent = "Type " + nameOf(row) + " to delete it";
        var input = document.createElement("input");
        input.type = "text";
        input.id = id;
        input.autocomplete = "off";
        input.maxLength = 200;
        input.setAttribute("data-client", idOf(row));
        input.setAttribute("data-name", nameOf(row));
        input.addEventListener("input", checkNames);
        item.appendChild(label);
        item.appendChild(input);
        container.appendChild(item);
      });
      checkNames();
    };
  }

  function namesMatch() {
    var inputs = Array.prototype.slice.call(names.querySelectorAll("input[data-name]"));
    return inputs.every(function (input) {
      return input.value.trim() === input.getAttribute("data-name");
    });
  }

  function checkNames() {
    confirm.disabled = !namesMatch();
  }

  function listNames(list) {
    return function (container) {
      list.forEach(function (row) {
        var item = document.createElement("li");
        item.textContent = nameOf(row);
        container.appendChild(item);
      });
      confirm.disabled = false;
    };
  }

  dialog.addEventListener("close", function () {
    var options = pending;
    pending = null;
    if (options && dialog.returnValue === "confirm") {
      options.run();
    }
    if (opener && document.contains(opener) && !opener.disabled) {
      opener.focus();
    } else {
      all.focus();
    }
  });

  // Cancel is a plain button (clients.html): Enter in a name field submits the
  // confirm button instead, which stays disabled until every name matches.
  dialog.querySelector("[data-bulk-cancel]").addEventListener("click", function () {
    dialog.close("cancel");
  });

  result.addEventListener("click", function (event) {
    var button = event.target.closest ? event.target.closest("[data-bulk-dismiss]") : null;
    if (!button) {
      return;
    }
    clearChildren(result);
    all.focus();
  });

  dialog.querySelector("form").addEventListener("submit", function (event) {
    var submitter = event.submitter;
    if (submitter && submitter.value === "confirm" && pending && pending.check && !pending.check()) {
      event.preventDefault();
      note.hidden = false;
      note.textContent = "A name does not match. Type each name exactly as it is shown.";
    }
  });

  bar.addEventListener("click", function (event) {
    var button = event.target.closest ? event.target.closest("[data-bulk-command]") : null;
    if (!button || button.disabled || busy) {
      return;
    }
    var list = chosen();
    var action = button.getAttribute("data-bulk-command");
    opener = button;
    if (action === "clear") {
      rows().forEach(function (row) {
        boxOf(row).checked = false;
      });
      update();
      all.focus();
    } else if (action === "csv") {
      downloadCsv(list);
    } else if (action === "report") {
      openDialog({
        title: "Make " + plural(list.length, "report", "reports"),
        text: "A report of the state of each client today, for the last full quarter, as the report builder makes it without dates. Nothing is exported or sent.",
        confirm: "Make " + plural(list.length, "report", "reports"),
        danger: false,
        fill: listNames(list),
        run: function () {
          makeReports(list);
        },
      });
    } else if (action === "delete") {
      openDialog({
        title: "Delete " + plural(list.length, "client", "clients") + " for good",
        text: "Each client loses its evidence, facts, reports, exports, kept files and pseudonym key. Only the audit entry and the hash chain remain. This cannot be undone.",
        confirm: "Delete " + plural(list.length, "client", "clients") + " for good",
        danger: true,
        fill: deleteFields(list),
        check: namesMatch,
        run: function () {
          var typed = {};
          names.querySelectorAll("input[data-client]").forEach(function (input) {
            typed[input.getAttribute("data-client")] = input.value.trim();
          });
          deleteClients(list, typed);
        },
      });
    }
  });

  table.addEventListener("change", function (event) {
    if (event.target && event.target.matches("input[data-bulk-pick]")) {
      update();
    }
  });

  all.addEventListener("change", function () {
    rows().forEach(function (row) {
      boxOf(row).checked = all.checked;
    });
    update();
  });

  // Ready: reveal the select boxes; the bar shows itself once a client is chosen.
  table.querySelectorAll("[data-bulk-cell]").forEach(function (element) {
    element.hidden = false;
  });
  selectRow.hidden = false;
  table.classList.add("has-bulk");
  update();
})();
