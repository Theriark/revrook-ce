# Screenshots of the web interface

The pictures the [guides](../guides/README.md) and the [README](../../README.md) use.
Every one is a live capture of the Development site of revrook CE,
`https://ce-dev-revrook.theriark.dev`, running commit
`0f705cace6f1d91c950693a2f1d67552904a2744` (the merge of pull request #135), signed in as
the test administrator `revrook-admin`, with the synthetic test data of that
installation only. No picture is a mock-up or was edited, and none holds a credential,
a real person or a real customer.

## The current set

On 2026-11-13, between 22:40 and 22:45 UTC, all 62 pictures were captured again,
because pull requests #127 to #135 revamped the interface in place after the set of
`544b166`: Inter, shipped with the installation, as the typeface of every page and of
the exported reports; the 28 px page title; motion (a page change that keeps the rail
and the top bar still, lists and arcs that arrive); the attention list read as text;
the clients table fitted to the wider typeface; on the client overview, **How fresh is
the evidence?** and **Recent changes** in a column beside **Coverage by domain**; and one
page frame, so nothing shifts between two pages. Every picture keeps its file name, its
window, its theme and its rail state. Two changed frame: `client-overview-1440.png` and
`client-overview-1440-rail-folded-dark.png` were a window that ended above Recent
changes and are now the whole page, because that section now stands beside the domain
keep and a window that ends above it would cut the keep off.

This set was taken on a deployment, with the 3D view shown on every page that has a
scene. One picture, `home-1440-scenes-hidden-dark.png`, shows the stage closed on
purpose: guide 8 explains **Show the 3D view** with it. The browser ran on the
operator's Windows computer, with a hardware GPU, and reached the site over its public
address.

| Fact | Value |
| --- | --- |
| Commit | `0f705cace6f1d91c950693a2f1d67552904a2744` (merge of pull request #135) |
| Image | `ghcr.io/theriark/revrook-ce@sha256:22d402c93e9a387817d291d69ba539b8089de91a2c83531fac04ca2d8c33ef94` |
| CI run | 43516815094 (the push of the commit to `development`) |
| Evidence | the System page showed `revrook 27.0.0.dev0, build 0f705cace6f1, role all` (pictured in `system-1440.png`) |
| Version shown | `27.0.0.dev0` on the System page, with the build commit beside it |
| Browser | Playwright for Python driving the installed Chrome 157, headless, CSS-pixel scale |
| Renderer | `ANGLE (NVIDIA, NVIDIA GeForce RTX 2080 SUPER (0x00001E81) Direct3D11 vs_5_0 ps_5_0, D3D11)`, a hardware GPU |
| Account | `revrook-admin`, signed in with a session cookie made on the Development server; no password typed |

`MANIFEST.json` in this folder is the capture manifest (schema 4): for every picture its
file name, SHA-256, size in bytes and pixels, the page, the window it was taken in
(width and height), the theme, the state of the rail, a code for the frame, the capture
time in Europe/Lisbon, the file the capture script wrote, what the frame shows and the
pages that use it; for the set, the candidate and how it was read, the privacy checks,
every change made to the Development data for the captures, what was not captured and
why, and the known limits. Every picture keeps the SHA-256 of the one it replaced under
`replaces`; `recapture` lists all 62.

The desktop view is the picture at 1440 px; the pictures at 768 px and 390 px are the
tablet and phone views and say so in the captions of the guides and the README.

What is pictured:

- **The top bar** on every signed-in page: the breadcrumb, the search, the theme toggle
  and the account menu (closed: its initial and name).
- **The import page**: Import evidence as it opens on a client, four synthetic files
  chosen, and the result table with three files imported and one refused as not
  recognised; the page on a phone.
- **The public DNS check**: the card before the run, with the mail domain typed, and
  after it, with the message that the result is stored.
- **The scenes** at 1440, 768 and 390 px, in the light and the dark theme: Home with the
  stage closed behind **Show the 3D view**, then with the street of twelve offices
  drawn, an office chosen from the keyboard with its company card open and the rail
  folded; a client overview with the domain keep, a domain chosen, the rail folded; the
  Evidence Explorer as it opens on the companies ring (1440 and 768 px) and the evidence
  wall of one client (`?client_id=21`, 1440 px dark and 390 px).
- **Every other flow**: the score drivers and the score over time on Home; the filters
  in use, the selection with the Make reports and Delete dialogs on the clients list,
  and the selection on a phone; the checklist and its tools at 1440, 768 and 390 px; the
  control drawer and the page of a control; the evidence page right after the import of
  the guide; the integrity check; the profile editor before and after reading and
  mapping a synthetic leavers file; the exceptions register, the report builder, the
  preview, the rendered review on a screen and on a phone, the export history; the
  settings, the system page with its version, build, worker and schedules, the glossary,
  the problem page and the sign-in page.

How a frame is made. Most pictures are the browser window at a given size: a window
as tall as the page shows the whole page with the rail drawn to its foot; a window
that ends above a section, or that is scrolled to a section, shows exactly that part.
A full-page capture is used only where the rail does not need to reach the foot (the
sign-in page, the narrow layouts, the rendered report). The manifest names the frame
of each picture.

### Six pictures of 2026-11-14

On 2026-11-14 at 04:16 UTC five pictures were captured again, on the Development
deployment of `56e697d499efc101c1013079f32b0594c5fc97e4` (the merge of pull request #139, image
`sha256:a883ae686ad2ccdbc59b2d6455338ea103b1a8fdc4b9e9a5f03dca2a337d7671`, CI run
43555212041): `settings-1440.png` and the four pictures of the rendered review
(`report-preview-file-1440.png`, `report-preview-file-full-1440.png`,
`report-preview-file-390.png`, `report-preview-file-390-table.png`). Pull requests
#137 to #139 gave the reports the look of a document (a cover with a dark head and
the score dial, a status bar, findings that say what was checked and the usual next
step, a section for what could not be checked, a mark for each domain) and Settings
a block for the logo of the business. The review pictured is now the one of Seed Gaps
Ltd (synthetic), report 20, a client with open findings, so that the findings are
seen; the pictures of the report builder, of Preview and export and of the export
history still show Seed Tidy Ltd (synthetic). The other 57 pictures are those of
2026-11-13, byte for byte. For these five, two reports of Seed Gaps were made on
Development that day (19 and 20), a made-up test logo was uploaded on Settings and
removed again while pull request #138 was checked (no logo is saved there, as the
picture shows), and the theme of the test account was switched to Light and back.

At 16:17 UTC the same day a sixth picture followed, `report-preview-1440.png`, on the
Development deployment of `af35cfa59234ffafd435deaeecc0058fb2ab18de` (the merge of pull request
#141, image `sha256:51ec1759636f6c8d7c3f8c6716a98c497804ce91813fe27e7223c3efdb0d3783`,
CI run 43613972418): the page **Preview and export** of report 18 of Seed Tidy Ltd
(synthetic), whose paper sheet is now drawn as the file is. Only the theme of the test
account was switched for it, and put back.

## Kept out of the pictures

**Recent changes** on Home and **Users and mappings** in Settings stay out of the
pictures: Home and Settings are pictured in a window that ends above them, because on
the shared Development installation they can name a seeded sign-in account with a
real-domain mailbox. **Recent changes** of the client overview is pictured: on Seed Gaps
Ltd (synthetic) its ten entries are the imports made for this set by `revrook-admin`.
Before every capture the text of the frame was read for an e-mail address and a
ticket-style identifier; none was found. The one address in a picture is
`reminders@example.test` in the reminder field of Settings, a reserved test domain.

Changes made for the captures. **Prepared by** of Seed Tidy Ltd (synthetic) was written
as `revrook-admin` and two reports were made for it; the newer one is the report
pictured. The eleven synthetic exports of the Development seed's gaps and tidy profiles
were written again by the seed's own builders and imported for Seed Gaps Ltd (synthetic)
and Seed Tidy Ltd (synthetic), so that their evidence is current. A first run of the
capture script was discarded (it cut the client overview above the keep); it made the
same changes as the run kept. On the import page, three recognised files written again
with a new capture time were imported for Seed Tidy Ltd (synthetic): a leavers list of
two invented people at `seed.example.invalid`, a Conditional Access export and an Intune
export, each a new revision of a source already imported; the fourth file, a help-desk
CSV that matches no source, was refused and nothing of it was stored. The public DNS
check of Seed Gaps Ltd (synthetic) was run for `example.com`, a reserved documentation
domain, with the weekly box unticked, so its weekly schedule stays off. The evidence
chains were checked; the profile editor read `leavers-synthetic.csv` and mapped its
columns without saving a profile or importing it; three clients were chosen and the two
dialogs were opened and closed with Cancel; the control drawer was opened; the rail and
the 3D view were switched with their own buttons; the theme, stored with the account,
was switched for the dark and the light pictures and put back to dark, as it was.

## Reading the pictures

- The scenes start hidden. `home-1440-scenes-hidden-dark.png` is Home as it opens; every
  other picture of a scene shows it after **Show the 3D view** was pressed, a choice the
  browser keeps for Home, the client overview and the Evidence Explorer together.
- The Development installation holds twelve clients: the four Seed clients and eight
  Mock clients, whose evidence is the synthetic export packs of the Mock Platform. Ten
  have a score (Seed Gaps 18.8 today and 16.0 at its last report, Seed Tidy 72.3, the
  Mock clients from 15.2 to 65.8) and two have evidence too thin for one (Seed Empty and
  Seed Stale, drawn in scaffolding with a lower bound); the pictures show that state as
  it was.
- The business name of the installation pictured is "Sample MSP", a made-up name, so
  the report pictures print it and the preview says the report is ready to export. Seed
  Tidy has one open exception and one kept export. 26 test clients were deleted on this
  installation earlier, so the integrity page folds their chains into one line.
- On the phone pictures the navigation wraps onto three rows, and the tabs of a client
  are a strip that scrolls sideways; the chevron at its right edge says more links lie
  beyond ([design system](../design-system.md)).
- The Evidence Explorer turns by itself until a person touches it, so each of its
  pictures shows the scene at the angle of that moment.
- `report-preview-file-full-1440.png` is the whole rendered review, 14,461 px tall; it
  was judged by its structure and the text of the page.

## Known limits of this set

- The Development installation is shared test data: its clients, scores and dates are
  those of 2026-11-13 and change as tests go on.
- The scenes were drawn by a hardware GPU in headless Chrome; no phone or touch screen.
- A still picture does not show motion: each one is the page at rest, after its
  entrance.
- The note a stage shows when the browser refuses a WebGL context is not pictured: the
  capture browser draws the scenes ([guide 8](../guides/08-scenes-rail-and-explorer.md)).
- The run of the Microsoft 365 export script is not pictured: it runs on the MSP's own
  machine against a tenant, and the documentation set has no tenant
  ([guide 10](../guides/10-microsoft-365-export.md)).
- The account menu is not pictured open.

## History

The earlier capture sets are history and are not used as the current preview: the 62
pictures captured on the night of 2026-11-12 on a local build of `544b1660` with the
Evidence Explorer table fix, the 62 pictures captured on the evening of 2026-11-12 on a
local build of `6ee1bba0`, the 26 pictures captured again on the morning of 2026-11-12
on `38da74b7` (Development), the set of 2026-11-11 (taken on `99aaf21b`, Development),
the set of 2026-10-27 (taken on `d0a2e9fe`, `f6fc7085` and `ab870e4d`, schema 4), the
set of 2026-10-25 (taken on `b4634182`, schema 4), the set of 2026-10-24 (taken on
`314d239c`, schema 4) and the sets of 2026-10-21 and 2026-10-22 (taken on `c41125fd`,
`f143e3db` and `6247addf`, schema 3). The pictures replaced here are kept byte for byte
in git at the base commit of this set
(`git show 0f705cace6f1d91c950693a2f1d67552904a2744:docs/images/<file>`),
with their manifest, and in the earlier review packages in Nextcloud
(`Documentation/` of the product folder), which are left untouched. Each replaced
picture keeps the hash of its predecessor in the manifest.
