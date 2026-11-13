// Nothing runs here. base.html links this file without `defer`, after the
// stylesheets: a browser cannot run a script before the stylesheets above it are
// in, so it also cannot reach <body> before them. That is the moment it decides
// whether a page change is animated (the @view-transition rule of revamp.css);
// without this file the rule was read too late and every page change was cut.
