# Screenshots of the web interface

The pictures the [guides](../guides/README.md) and the [README](../../README.md) use.
Every one is a live capture of the Development site of revrook CE
(`https://ce-dev-revrook.theriark.dev`), signed in as the administrator test account of
that installation, with synthetic data only. No picture is a mock-up or was edited, and
none holds a credential, a real person, a real customer or another environment.

## The current set

All 44 pictures were captured on 2026-10-24 between 11:01 and 11:10 Europe/Lisbon
(10:01 to 10:10 UTC) while the Development site ran the deployed candidate:

| Fact | Value |
| --- | --- |
| Commit | `314d239c38965e5ea503ba6526c62d0d2ea7b523` |
| Image | `ghcr.io/theriark/revrook-ce@sha256:30bf7d9727764d91b490a73d7b621d4284fc18397ac140e648290c4336581ca6` |
| Evidence | the deployment receipt of the Development environment (CI run 40079874064, deployed 2026-10-24T09:11:03Z), read before the first capture and after the last, with no deployment in between |

`MANIFEST.json` in this folder is the capture manifest (schema 4): for every picture its
file name, SHA-256, size in bytes and pixels, the page, the window it was taken in
(width and height), the theme, the state of the rail, a code for the frame, the capture
time in Europe/Lisbon and the pages that use it; for the set, the candidate and how it
was read, the privacy checks, every change made to the Development data for the
captures, what was not captured and why, and the known limits. A picture that replaced
one of the earlier set keeps the SHA-256 of the one it replaced under `replaces`. The
`manifest.json` of the Nextcloud review package of this set adds, for every picture,
what the frame shows, the frame in words, the capture time in UTC and the name of the
browser capture.

What is pictured:

- **The changed flows** at 1440, 768 and 390 px, in the light and the dark theme: Home
  with the rookery skyline, a client chosen from the keyboard, the scenes hidden, the
  rail folded; a client overview with the domain keep, a domain chosen, the rail
  folded; the Evidence Explorer; the control drawer.
- **Every other page** at 1440 px in the light theme (the sign-in page, the clients
  list and the checklist also at 768 or 390 px), captured again because the rail of
  every page changed (the Evidence Explorer moved into the Evidence group and the fold
  button was added) and because the Development site now holds the seed clients.

How a frame is made. Most pictures are the browser window at a given size: a window
as tall as the page shows the whole page with the rail drawn to its foot; a window
that ends above a section, or that is scrolled to a section, shows exactly that part.
A full-page capture is used only where the rail does not need to reach the foot (the
sign-in page, the narrow layouts, the rendered report). The manifest names the frame
of each picture.

## Kept out of the pictures

Two parts of the live pages are never pictured, because on the shared Development
installation they name a second sign-in account created by the Development seed, whose
login is a real-domain mailbox: **Recent changes** on Home and on a client overview (the
audit trail names who made each change) and **Users and mappings** in Settings. Home,
the client overview and Settings are pictured in a window that ends above them. For the
same reason, and because earlier tests left labels with internal ticket numbers on Seed
Gaps Ltd and the Design Review Sample Client, the exceptions register and the export
history are pictured on Seed Tidy Ltd (synthetic).

Changes made for the captures, all on synthetic data: one exception added to Seed Tidy
Ltd (synthetic) through its form (left open, so the register and the reports show it),
one export of its quarterly review, a synthetic leavers file read in the profile editor
(nothing saved), and the theme, the rail and the scenes switched and switched back.

## Reading the pictures

- On the phone picture of the checklist (`checklist-390.png`) the tab bar of the client
  is cut at the right edge on purpose: the tabs are a strip that scrolls sideways
  ([design system](../design-system.md)).
- The Evidence Explorer turns by itself until a person touches it, so each of its
  pictures shows the wall at the angle of that moment.
- `client-overview-768-keep-dark.png` shows the block in the front right corner of the
  keep meeting the bottom edge of its stage: a known limit of the candidate at 768 px
  ([guide 8](../guides/08-scenes-rail-and-explorer.md#known-limits)).
- `report-preview-file-full-1440.png` is the whole rendered review, 16,429 px tall.

## History

The earlier capture sets (2026-10-21 and 2026-10-22, taken on the commits `c41125fd`,
`f143e3db` and `6247addf`) are history and are not used as the current preview. The
pictures they held under the names reused here are kept byte for byte in git at the
base commit of this set (`git show 314d239c38965e5ea503ba6526c62d0d2ea7b523:docs/images/<file>`),
with their own schema 3 manifest, and in the earlier review packages in Nextcloud
(`Documentation/v27.0.0-rc.1` to `v27.0.0-rc.10` of the product folder), which are left
untouched. Each replaced picture keeps the hash of its predecessor in the manifest.
