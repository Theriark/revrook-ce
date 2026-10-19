"""Extension API (decision D1), frozen at version 1 in phase 11.

The seven extension points are protocols in `app.ext.protocols`; plugins are found
and loaded by `app.ext.registry`. Nothing is imported here, so the constants can be
read without loading either. `docs/extension-api.md` is the reference.
"""

EXTENSION_API_VERSION = 1
PLUGIN_ENTRY_POINT_GROUP = "revrook.plugins"
