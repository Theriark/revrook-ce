# Screenshots of the web interface

The pictures the [guides](../guides/README.md) and the [README](../../README.md) use.
Every one is a live capture of the Development site of revrook CE
(`https://ce-dev-revrook.theriark.dev`), signed in as the administrator test account of
that installation, with synthetic data only. No picture is a mock-up or was edited, and
none holds a credential, a real person, a real customer or another environment.

## The current set

On 2026-11-12, 26 of these pictures were captured again, because pull request #98
changed the pages they show: Home now has Needs attention and Score over time under the
stat cards and folds the mean score into **How the score works**, the clients list shows
the bands as chips, and the checklist no longer repeats the status or shows an empty
Owner column. They are every picture of Home, the clients list and the checklist (with
the control drawer over it), taken between 08:40 and 08:44 UTC in two browser sessions
(the second only retook the rook chosen with the keyboard) with the same browser tools and the same administrator test account, on commit
`38da74b76d0daeef035921cbfa3f5f784d0b3224` (image
`ghcr.io/theriark/revrook-ce@sha256:96fcfb92a4e1298a1848b5a9cafa1c6cc85f4a4992bf2b0a62d653c8cf27ea13`,
CI run 43135573327; the System page showed `build 38da74b76d0d`). The scene pictures of
Home are now scrolled to What moves the score, which no longer sits at the top of the
page. In `MANIFEST.json` each of them carries `candidate` and, under `replaces`, the
SHA-256 of the 2026-11-11 picture; `recapture` lists them. The other 36 pictures are the
set of 2026-11-11 described below.

The set holds 62 pictures, all captured on 2026-11-11 between 20:28 and 20:49
Europe/Lisbon (UTC+00:00, so the same as UTC) in one browser session, while the
Development site ran the application build documented and captured below: the merge
of pull request #90, which adds the import page, the DNS check of the evidence page
and the Microsoft 365 export script, and starts the scenes hidden. 56 pictures replace
the ones of the same name in the set of 2026-10-27 (the rail of every signed-in page
gained **Import evidence**, the scenes open behind **Show the 3D view**, and the
wording of several pages changed, so no earlier picture shows the current interface);
6 are new, for the import page and the DNS check. Later documentation-only commits
are deployed on top with the same application code; the deployed head is read from the
deployment receipt and the package manifest.

| Fact | Value |
| --- | --- |
| Commit | `99aaf21b26a93a54b6db1aa5534e602c6e2e8541` (merge of pull request #90) |
| Image | `ghcr.io/theriark/revrook-ce@sha256:6bd4e84cbbabccfd8b96ad5f44e9ed714262412bb81cceb61fdedb9c75967e6c` |
| Evidence | deployment receipt (CI run 43090547270, Dokploy deployment `74dTjv4AG-H9fHJgQ009u`, deployed 2026-11-11T20:01:55Z), read before the first capture, its image proof verified against the commit; the System page showed `build 99aaf21b26a9` during the session |
| Version shown | `27.0.0.dev0` on the System page, with the build commit beside it |

The six new pictures are `imports-1440.png`, `imports-1440-files-chosen.png`,
`imports-1440-result.png`, `imports-390.png`, `evidence-1440-dns-check.png` and
`evidence-1440-dns-check-done.png`.

`MANIFEST.json` in this folder is the capture manifest (schema 4): for every picture its
file name, SHA-256, size in bytes and pixels, the page, the window it was taken in
(width and height), the theme, the state of the rail, a code for the frame, the capture
time in Europe/Lisbon, the name of the browser capture it was imported from, what the
frame shows and the pages that use it; for the set, the candidate and how it was read,
the privacy checks, every change made to the Development data for the captures, what
was not captured and why, and the known limits. A picture that replaced one of the
earlier set keeps the SHA-256 of the one it replaced under `replaces`; a picture with
no predecessor says so under `new`. The `manifest.json` of the Nextcloud review package
of this set repeats these fields with the package paths of each picture.

The desktop view is the picture at 1440 px; the pictures at 768 px and 390 px are the
tablet and phone views and say so in the captions of the guides and the README.

What is pictured:

- **The import page** (new in this build): Import evidence as it opens on a client,
  four synthetic files chosen, and the result table with three files imported and one
  refused as not recognised; the page on a phone.
- **The public DNS check** (new on the evidence page in this build): the card before
  the run, with the mail domain filled in, and after it, with the message that the
  result is stored and the Public DNS check row current.
- **The scenes** at 1440, 768 and 390 px, in the light and the dark theme: Home as it
  opens with the stage closed behind **Show the 3D view**, then with the rookery drawn,
  a client chosen from the keyboard and the rail folded; a client overview with the
  domain keep, a domain chosen, the rail folded; the Evidence Explorer with its wall.
- **Every other flow**, captured again on this build: the top bar, the score drivers
  and the score over time on Home; the filters in use, the selection with the Make
  reports and Delete dialogs on the clients list, and the selection on a phone; the
  checklist and its tools at 1440, 768 and 390 px; the control drawer and the page of a
  control; the evidence page right after the import of the guide; the integrity check
  with the chains of deleted clients folded; the profile editor before and after
  reading a synthetic leavers file; the exceptions register, the report builder, the
  preview, the rendered review on a screen and on a phone, the export history; the
  settings, the system page with its version and build, the glossary, the problem page
  and the sign-in page.

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
audit trail names who made each change) and **Users and mappings** in Settings (which
now marks that account as a Development test account). Home, the client overview and
Settings are pictured in a window that ends above them. The exceptions register and the
export history are pictured on Seed Tidy Ltd (synthetic), as before.

Changes made for the captures. On the import page, three synthetic files were imported
for Seed Tidy Ltd (synthetic): a leavers list of two invented people at
`seed.example.invalid`, a Conditional Access export and an Intune export, each written
by the Development seed's own builders and each a new revision of a source the seed
had already imported; the fourth file, a help-desk CSV that matches no source, was
refused and nothing of it was stored. The public DNS check of Seed Gaps Ltd
(synthetic) was run once for `example.com`, a reserved documentation domain, with the
weekly box unticked; the client already had a run for that domain from the same day,
and its `dns-check` schedule stays switched off (it is the row the System page shows).
The evidence chains were checked (a read); the profile editor read
`leavers-synthetic.csv` without saving a profile or importing it; three clients were
chosen and the two dialogs were opened and closed with Cancel; the 3D view, the theme
and the rail were switched and switched back.

## Reading the pictures

- The scenes start hidden. `home-1440-scenes-hidden-dark.png` is Home as it opens; every
  other picture of a scene shows it after **Show the 3D view** was pressed, a choice the
  browser keeps for Home, the client overview and the Evidence Explorer together.
- On the capture day every client of the Development site had evidence too thin for a
  score: its seeded exports are older than the strictest control that reads them
  allows. So every rook of the rookery is a wire rook, every score a lower bound, and
  the stat cards count expired exports; the pictures show that state as it was.
- On the phone pictures the navigation and the tabs of a client are strips that scroll
  sideways; the chevron at their right edge says more links lie beyond
  ([design system](../design-system.md)).
- The Evidence Explorer turns by itself until a person touches it, so each of its
  pictures shows the wall at the angle of that moment.
- The integrity page folds the chains of the 25 clients deleted by earlier tests into
  one line under the table; the chain of a deleted client stays, by design.
- `report-preview-file-full-1440.png` is the whole rendered review, 16,003 px tall, and
  `evidence-1440.png` the whole evidence page of a client with 44 items, 6,128 px tall;
  both were judged by their structure and the text of the page.

## Known limits of this set

- The scenes were drawn by a software renderer; no hardware GPU, phone or touch screen.
- The note a stage shows when the browser refuses a WebGL context is not pictured: the
  capture browser draws the scenes ([guide 8](../guides/08-scenes-rail-and-explorer.md)).
- The run of the Microsoft 365 export script is not pictured: it runs on the MSP's own
  machine against a tenant, and the documentation set has no tenant
  ([guide 10](../guides/10-microsoft-365-export.md)).
- The two sign-in pictures were captured again rather than kept: a fresh capture was
  not byte-identical to the stored ones, because the theme switch of the sign-in page
  followed the cookie of the signed-out account (Light pressed) where the earlier set
  showed System.

## History

The earlier capture sets are history and are not used as the current preview: the set
of 2026-10-27 (taken on `d0a2e9fe`, `f6fc7085` and `ab870e4d`, schema 4), the set of
2026-10-25 (taken on `b4634182`, schema 4), the set of 2026-10-24 (taken on
`314d239c`, schema 4) and the sets of 2026-10-21 and 2026-10-22 (taken on `c41125fd`,
`f143e3db` and `6247addf`, schema 3). The pictures the set of 2026-10-27 held under the
names reused here are kept byte for byte in git at the base commit of this set
(`git show 99aaf21b26a93a54b6db1aa5534e602c6e2e8541:docs/images/<file>`), with their
manifest, and in the earlier review packages in Nextcloud (`Documentation/` of the
product folder), which are left untouched. Each replaced picture keeps the hash of its
predecessor in the manifest.
