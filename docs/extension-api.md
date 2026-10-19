# Extension API, version 1

How a package adds to revrook without changing it. Version 1 is **frozen**: a name, a
member, a field or a signature below changes only together with a new
`EXTENSION_API_VERSION`. revrook Community Edition ships no plugin; with none installed
the registry is empty and the product behaves as it always did. The code is in
`app/ext/` (`protocols.py`, `registry.py`), the contract tests in
`tests/test_extension_api.py`, and a no-op reference plugin in `tests/ref_plugin.py`
(used only by those tests: it is not packaged and not part of the image).

## Loading a plugin

A plugin is an installed Python package that names an object in the entry point group
`revrook.plugins` (`PLUGIN_ENTRY_POINT_GROUP`) in its own `pyproject.toml`:

```toml
[project.entry-points."revrook.plugins"]
acme = "acme_revrook:PLUGIN"
```

The object is a plugin instance, or a class that takes no arguments. It has:

| Member | Meaning |
| --- | --- |
| `name` | Lower-case letters, digits and dashes, unique among plugins. |
| `api_version` | An integer equal to `EXTENSION_API_VERSION` (1). |
| `register(registry)` | Hands the extension objects of the plugin to the registry. |

`create_app` calls `load_plugins()` once, at start-up, and keeps the registry in
`app.state.extensions`. Loading **fails closed**: a plugin that cannot be imported, speaks
another API version, registers an object that does not implement its point, repeats a
name, or raises while registering stops the start-up with `ExtensionError` and a message
that names the plugin and the class of the error (never the text of the error, which
could hold a secret; the error itself is not chained to `ExtensionError`, so it does not
reach the start-up log either). The plugin `name` must match the pattern above, or the
load is refused. An `ExtensionError` that a plugin raises on its own is shown as written.

## The seven extension points

Each is a `typing.Protocol` in `app.ext.protocols`, checked at registration with
`isinstance`. Every object has a `name` of lower-case letters, digits and dashes, unique
within its point (at most 40 characters, starting with a letter).

| Point | Registry method | Members | Purpose |
| --- | --- | --- | --- |
| `CollectorProvider` | `add_collector` | `name`, `source_code`, `async collect(client_id, now)` | Gathers evidence the importers do not read. Returns `CollectedEvidence` (`source_code`, `captured_at`, `data`). |
| `FrameworkPack` | `add_framework` | `name`, `framework`, `version`, `mappings()` | Maps controls to the clauses of one framework version (`ControlMapping`: `control_id`, `reference`, `verified`). |
| `QuestionnairePack` | `add_questionnaire` | `name`, `title`, `questions()` | A questionnaire answered from controls (`Question`: `id`, `text`, `control_ids`, `verified`). |
| `ReportTemplate` | `add_report_template` | `name`, `kind`, `render(snapshot)` | Renders a stored snapshot document as a file (`RenderedReport`: `filename`, `content_type`, `body`). |
| `AuthProvider` | `add_auth_provider` | `name`, `async authenticate(headers)` | Names the caller from request headers (`ExternalIdentity`: `username`, `is_admin`) or returns `None`. |
| `RetentionPolicy` | `add_retention_policy` | `name`, `raw_retention_days(source_code, default_days)`, `pack_retention_months(default_months)` | Chooses retention; the arguments are the installation's defaults. |
| `UiExtension` | `add_ui_extension` | `name`, `nav_items()` | Adds links to the navigation (`NavItem`: `label`, `path` starting with `/`). |

The data types are frozen dataclasses. A mapping or a question that a person has not
checked must carry `verified=False`: a report never presents an unverified mapping as
established.

## What version 1 does not do yet

Version 1 freezes the **contract**: the shapes above, the loader and the registry. The
Community Edition reads the registry at start-up but does not yet call every point from
its own pages and jobs; a later edition wires the points it needs. A plugin must not
rely on any behaviour that this document does not state, on private names in `app`, or
on the order in which plugins load (they load sorted by entry point name).

## Rules for a plugin

- It runs in the process of revrook with the rights of revrook: install only code you
  trust, and review it like the application.
- It must not log secrets, tokens or customer data.
- It must not change `app` at run time (no monkey patching).
- A change that is not backwards compatible is a new `EXTENSION_API_VERSION`; a plugin
  written for version 1 then fails to load with a message, never silently.

## The CE image

The image holds the application, its migrations and its data files only, and no plugin.
`tests/test_extension_api.py` checks that the Dockerfile copies nothing else, that no
file it copies holds a name that belongs to a later edition, and that the package
declares the entry point group empty.
