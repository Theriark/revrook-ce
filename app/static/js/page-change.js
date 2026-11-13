// base.html links this file without `defer`, after the stylesheets: a browser
// cannot run a script before the stylesheets above it are in, so it also cannot
// reach <body> before them. That is the moment it decides whether a page change
// is animated (the @view-transition rule of revamp.css); without this file the
// rule was read too late and every page change was cut.
//
// One thing runs here. A report preview is the report as the client gets it, a
// file with no rule of ours, so it takes no part in a page change: the browser
// would cut the change on arrival and write an exception to the console of the
// preview. The page that is left cuts it itself.
window.addEventListener("pageswap", function (event) {
  var entry = event.activation && event.activation.entry;
  if (!event.viewTransition || !entry) {
    return;
  }
  if (/\/preview\/[a-z]+$/.test(new URL(entry.url).pathname)) {
    event.viewTransition.skipTransition();
  }
});
