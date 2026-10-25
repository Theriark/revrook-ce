# Screenshots of the web interface

The pictures the [guides](../guides/README.md) and the [README](../../README.md) use.
Every one is a live capture of the Development site of revrook CE
(`https://ce-dev-revrook.theriark.dev`), signed in as the administrator test account of
that installation, with synthetic data only. No picture is a mock-up or was edited, and
none holds a credential, a real person, a real customer or another environment.

## The current set

The set holds 56 pictures. 53 were captured on 2026-10-25 between 11:03 and 11:43
Europe/Lisbon (UTC+00:00 that day, after the clock went back, so the same as UTC) while
the Development site ran the application build documented and captured below. The 2 of
the sign-in page are kept because a fresh capture on that build was byte-identical. 1,
`profile-editor-preview-1440.png`, is kept from the set of 2026-10-24 and is marked so
(see [Known limits of this set](#known-limits-of-this-set)). Later documentation-only
commits are deployed on top with the same application code; the deployed head is read
from the deployment receipt and the package manifest.

| Fact | Value |
| --- | --- |
| Commit | `b4634182e0fd68d760c209fcc6051ff9adceea2e` |
| Image | `ghcr.io/theriark/revrook-ce@sha256:cfcb12a8a3979bc10957ca220c59e26b28bbc7742669b868373a7451192ea7d5` |
| Evidence | the deployment receipt of the Development environment (CI run 40184907364, Dokploy deployment `ogG86UI70qyy2DI07CqAu`, deployed 2026-10-25T10:45:58Z), read before the first capture, between the two capture sessions and after the last, with no deployment in between |

`MANIFEST.json` in this folder is the capture manifest (schema 4): for every picture its
file name, SHA-256, size in bytes and pixels, the page, the window it was taken in
(width and height), the theme, the state of the rail, a code for the frame, the capture
time in Europe/Lisbon and the pages that use it; for the set, the candidate and how it
was read, the privacy checks, every change made to the Development data for the
captures, what was not captured and why, and the known limits. A picture that replaced
one of the earlier set keeps the SHA-256 of the one it replaced under `replaces`; a
picture kept from an earlier set says why under `kept`. The
`manifest.json` of the Nextcloud review package of this set adds, for every picture,
what the frame shows, the frame in words, the capture time in UTC and the name of the
browser capture.

What is pictured:

- **The new flows of this build**: the top bar of every signed-in page (breadcrumb and
  the search of the clients); on Home, what moves the score (light and dark) and the
  score over time with clients that have one report; on the clients list, the filters
  in use as chips, three clients chosen with the CSV result, the Make reports and the
  Delete dialogs (both closed with Cancel), and the selection on a phone; the search,
  Status and Order tools of the checklist at 1440 and 768 px; the rendered review on a
  phone, with a table scrolling in its own frame.
- **The scenes** at 1440, 768 and 390 px, in the light and the dark theme: Home with
  the rookery skyline, a client chosen from the keyboard, the scenes hidden, the rail
  folded; a client overview with the domain keep fitted to its stage, a domain chosen,
  the rail folded; the Evidence Explorer.
- **Every other signed-in page** at 1440 px in the light theme (the clients list and
  the checklist also at 768 or 390 px), captured again because the top bar was added
  to every signed-in page.

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
(a read), and the theme, the rail and the scenes were switched and switched back.

## Reading the pictures

- On the phone picture of the checklist (`checklist-390.png`) the tab bar of the client
  is cut at the right edge on purpose: the tabs are a strip that scrolls sideways
  ([design system](../design-system.md)).
- The Evidence Explorer turns by itself until a person touches it, so each of its
  pictures shows the wall at the angle of that moment.
- The score charts name each client at the end of its line and shorten a long name
  there; the legend under the chart gives every name in full.
- The integrity page lists the chains of clients deleted by earlier tests as
  "Deleted client" and a number: the chain of a deleted client stays, by design.
- `report-preview-file-full-1440.png` is the whole rendered review, 16,499 px tall.

## Known limits of this set

- `profile-editor-preview-1440.png` (the profile editor after reading a synthetic
  leavers file) is the capture of 2026-10-24 on `314d239c`: it shows the page without
  the top bar. Reading a file needs a file chosen in the browser, and the browser
  upload tool was not permitted in the capture run. The steps it shows are unchanged.
- The scenes were drawn by a software renderer; no hardware GPU, phone or touch screen.

## History

The earlier capture sets are history and are not used as the current preview: the set
of 2026-10-24 (taken on `314d239c`, schema 4) and the sets of 2026-10-21 and 2026-10-22
(taken on `c41125fd`, `f143e3db` and `6247addf`, schema 3). The pictures the set of
2026-10-24 held under the names reused here are kept byte for byte in git at the base
commit of this set (`git show b4634182e0fd68d760c209fcc6051ff9adceea2e:docs/images/<file>`),
with their manifest, and in the earlier review packages in Nextcloud
(`Documentation/` of the product folder), which are left untouched. Each replaced
picture keeps the hash of its predecessor in the manifest.
