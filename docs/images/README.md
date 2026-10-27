# Screenshots of the web interface

The pictures the [guides](../guides/README.md) and the [README](../../README.md) use.
Every one is a live capture of the Development site of revrook CE
(`https://ce-dev-revrook.theriark.dev`), signed in as the administrator test account of
that installation, with synthetic data only. No picture is a mock-up or was edited, and
none holds a credential, a real person, a real customer or another environment.

## The current set

The set holds 56 pictures. 54 were captured on 2026-10-27 between 01:56 and 02:32
Europe/Lisbon (UTC+00:00, so the same as UTC) while the Development site ran the
application build documented and captured below, the revamped interface. The 2 of the
sign-in page are kept because a fresh capture on that build was byte-identical. Later
documentation-only commits are deployed on top with the same application code; the
deployed head is read from the deployment receipt and the package manifest.

| Fact | Value |
| --- | --- |
| Commit | `d0a2e9fe8c769bb3fdb8ee884a3c16199dcc57a5` (merge of pull request #83) |
| Image | `ghcr.io/theriark/revrook-ce@sha256:91c6b72cb44ddd4aba33b1c04c0b2b27283311ebab5f752eba92faa5b67183ef` |
| Evidence | the deployment receipt of the Development environment (CI run 40337009384, Dokploy deployment `l4TQ87N-4OEwvBzVw-XR5`, deployed 2026-10-26T14:27:34Z), read before the first capture and after the last, with no deployment in between |

`MANIFEST.json` in this folder is the capture manifest (schema 4): for every picture its
file name, SHA-256, size in bytes and pixels, the page, the window it was taken in
(width and height), the theme, the state of the rail, a code for the frame, the capture
time in Europe/Lisbon, the name of the browser capture it was imported from and the
pages that use it; for the set, the candidate and how it was read, the privacy checks,
every change made to the Development data for the captures, what was not captured and
why, and the known limits. A picture that replaced one of the earlier set keeps the
SHA-256 of the one it replaced under `replaces`; a picture kept from an earlier set says
why under `kept`. The `manifest.json` of the Nextcloud review package of this set adds,
for every picture, what the frame shows, the frame in words and the capture time in UTC.

The desktop view is the picture at 1440 px; the pictures at 768 px and 390 px are the
tablet and phone views and say so in the captions of the guides and the README.

What is pictured:

- **The revamp of this build** on every signed-in page: the keep, the charcoal band
  with the battlement of the mark that carries the title, the purpose, the primary
  action and the tabs of a client; the stone rail of the light theme; on Home the
  ledger of stat cards, the gauge beside the rookery in the keep panel and the
  dashboard in two columns; the checklist grouped by domain; the control page with the
  sources it reads; the exceptions register with its horizon; the report builder as
  three joined steps beside the reports made before; the preview as a white sheet in
  the keep; the export history as a ledger; the settings with the cover line; the
  system page as tiles; the glossary with its index.
- **The scenes** at 1440, 768 and 390 px, in the light and the dark theme: Home with
  the gauge and the rookery skyline, a client chosen from the keyboard, the scenes
  hidden, the rail folded; a client overview with the domain keep, a domain chosen, the
  rail folded; the Evidence Explorer.
- **The flows of the earlier sets**, captured again on this build: the top bar, the
  score drivers and the score over time on Home; the filters in use, the selection with
  the CSV result and the Make reports and Delete dialogs on the clients list, and the
  selection on a phone; the search, Status and Order tools of the checklist at 1440 and
  768 px; the control drawer; the profile editor before and after reading a synthetic
  leavers file; the integrity check; the rendered review on a screen and on a phone.

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

Changes made for the captures: none to the client data (the open exception and the
export of Seed Tidy Ltd (synthetic) were made for the set of 2026-10-24 and are
pictured as they are). Three clients were chosen and downloaded as CSV, the Make reports
and Delete dialogs were opened and closed with Cancel, the evidence chains were checked
(a read), a synthetic leavers file (`leavers-synthetic.csv`, four invented people at
`example.test` addresses, shown only as pseudonyms) was read in the profile editor
without saving a profile or importing it, and the theme, the rail and the scenes were
switched and switched back. The clients list also shows a client named `test`, left
empty by an earlier test of the site; it holds no data.

## Reading the pictures

- On the phone pictures the navigation and the tabs of a client are strips that scroll
  sideways; the chevron at their right edge says more links lie beyond
  ([design system](../design-system.md)).
- The Evidence Explorer turns by itself until a person touches it, so each of its
  pictures shows the wall at the angle of that moment.
- The score charts name each client at the end of its line, fitted to the room beside
  the plot and tied to the line by a short leader when names are moved apart; the
  legend under the chart gives every name in full.
- The integrity page lists the chains of clients deleted by earlier tests as
  "Deleted client" and a number: the chain of a deleted client stays, by design.
- `report-preview-file-full-1440.png` is the whole rendered review, 16,499 px tall. The
  rendered review is drawn by `app/reports`, which the revamp did not change; it differs
  from the set of 2026-10-25 by its generation date only.

## Known limits of this set

- The scenes were drawn by a software renderer; no hardware GPU, phone or touch screen.
- The note a stage shows when the browser refuses a WebGL context is not pictured: the
  capture browser draws the scenes ([guide 8](../guides/08-scenes-rail-and-explorer.md)).
- The pictures show the interface as it is on this build, including five layout
  findings that were reported for a fix and that this documentation does not change: a
  chosen client card on a phone keeps white strips behind its labels
  (`clients-390-selected.png`); with the rail folded the content stops about 200 px
  short of the right edge at 1440 px (`home-1440-rail-folded-dark.png`); the facts of
  the control drawer wrap (`control-drawer-1440.png`); the checklist at 768 px breaks a
  date after its second hyphen (`checklist-768-tools.png`); and the owner "Office
  manager" breaks inside the word in the exceptions register (`exceptions-1440.png`).

## History

The earlier capture sets are history and are not used as the current preview: the set
of 2026-10-25 (taken on `b4634182`, schema 4), the set of 2026-10-24 (taken on
`314d239c`, schema 4) and the sets of 2026-10-21 and 2026-10-22 (taken on `c41125fd`,
`f143e3db` and `6247addf`, schema 3). The pictures the set of 2026-10-25 held under the
names reused here are kept byte for byte in git at the base commit of this set
(`git show d0a2e9fe8c769bb3fdb8ee884a3c16199dcc57a5:docs/images/<file>`), with their
manifest, and in the earlier review packages in Nextcloud (`Documentation/` of the
product folder), which are left untouched. Each replaced picture keeps the hash of its
predecessor in the manifest.
