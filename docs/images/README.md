# Screenshots of the web interface

The pictures the [guides](../guides/README.md) and the [README](../../README.md) use.
Every one is a live capture of revrook CE built locally from commit
`544b16606e7475b8b10db186c8ff38db78800eb7` (the merge of pull request #114) with the
Evidence Explorer table fix of this pull request, signed in as
the local administrator `local-admin`, with the synthetic data of the Development seed
only. No picture is a mock-up or was edited, and none holds a credential, a real
person, a real customer or another environment.

## The current set

On 2026-11-12, between 22:22 and 22:35 UTC, all 62 pictures were captured again on
the build being promoted, because pull request #110 changed several screens after the
set of `6ee1bba`: one **No report yet** chip; **Newest evidence** in calendar days; the
company card on Home's street inside the stage and 24rem wide; the Evidence Explorer
ring filling its stage at 768 px; no gap above the heading of the DNS card; table
bottom borders across the full width; an icon gap in button links; one wording for the
missing business name in the report pages, with no stray separator in the report
header; the rook of the sign-in wordmark in the link colour; a 14 px placeholder in the
phone checklist; and **Show in scene** on one line. Every picture keeps its file name,
its window, its theme, its rail state and its frame. Eleven of the new captures came out
byte for byte the same as the pictures they replace, because their screens did not
change; the manifest lists them under `recapture.unchangedBytes`.

The recapture found the tables of the Evidence Explorer cut at the edge of the window at
768 px. This pull request puts each of them in a region that scrolls sideways
(`app/ui/templates/evidence_explorer.html`, `app/static/css/evidence-explorer.css`); the
app was restarted on that working tree and the four Evidence Explorer pictures were
taken again. The other 58 pages do not load that template or stylesheet. The candidate
is therefore development `544b166` plus this fix, and the source of the release
candidate is the merge commit of this pull request.

This set was not taken on a deployment. The application ran on the operator's Windows
computer at `http://127.0.0.2:8099`, started from the repository at the commit below
with a local PostgreSQL and the Development seed (`DEV_SEED=1`). There is no container
image, no image digest, no CI run and no Dokploy deployment behind these pictures.

| Fact | Value |
| --- | --- |
| Commit | `544b16606e7475b8b10db186c8ff38db78800eb7` (merge of pull request #114) plus the uncommitted Evidence Explorer table fix of this pull request |
| Image | none: a local build |
| Evidence | the System page showed `build 544b16606e74` (read from HEAD, so the uncommitted fix does not show in it) |
| Version shown | `27.0.0.dev0` on the System page, with the build commit beside it |
| Browser | Playwright for Python driving the installed Chrome 157, headless, CSS-pixel scale |
| Renderer | `ANGLE (NVIDIA, NVIDIA GeForce RTX 2080 SUPER (0x00001E81) Direct3D11 vs_5_0 ps_5_0, D3D11)`, a hardware GPU |
| Account | `local-admin`, signed in with a session cookie minted locally; no password typed |

`MANIFEST.json` in this folder is the capture manifest (schema 4): for every picture its
file name, SHA-256, size in bytes and pixels, the page, the window it was taken in
(width and height), the theme, the state of the rail, a code for the frame, the capture
time in Europe/Lisbon, the file the capture script wrote, what the frame shows and the
pages that use it; for the set, the candidate and how it was read, the privacy checks,
every change made to the local data for the captures, what was not captured and why,
and the known limits. Every picture keeps the SHA-256 of the one it replaced under
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
  stage closed behind **Show the 3D view**, then with the street of offices drawn, an
  office chosen from the keyboard with its company card open and the rail folded; a
  client overview with the domain keep, a domain chosen, the rail folded; the Evidence
  Explorer as it opens on the companies ring (1440 and 768 px) and the evidence wall of
  one client (`?client_id=2`, 1440 px dark and 390 px).
- **Every other flow**: the score drivers and the score over time on Home; the filters
  in use, the selection with the Make reports and Delete dialogs on the clients list,
  and the selection on a phone; the checklist and its tools at 1440, 768 and 390 px; the
  control drawer and the page of a control; the evidence page right after the import of
  the guide; the integrity check; the profile editor before and after reading and
  mapping a synthetic leavers file; the exceptions register, the report builder, the
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

**Recent changes** on Home and on a client overview and **Users and mappings** in
Settings stay out of the main pictures: Home, the client overview and Settings are
pictured in a window that ends above them, as in the earlier sets, where the shared
Development installation listed a seeded sign-in account with a real-domain mailbox
there. On the local installation of this set both name only `local-admin`, and the
first entries of Recent changes show at the foot of the two score-driver pictures.
Before every capture the text of the frame was read for an e-mail address and a
ticket-style identifier; none was found.

Changes made for the captures. On the import page, the four files of the earlier set
were sent once more and all four were refused (three as already uploaded that day, one
as not recognised), so nothing was stored and that picture was discarded. The three
recognised files were then written again by the Development seed's own builders, with a
new capture time, and imported for Seed Tidy Ltd (synthetic): a leavers list of two
invented people at `seed.example.invalid`, a Conditional Access export and an Intune
export, each a new revision of a source already imported; the fourth file, a help-desk
CSV that matches no source, was refused and nothing of it was stored. The public DNS
check of Seed Gaps Ltd (synthetic) was run once more for `example.com`, a reserved
documentation domain, with the weekly box unticked, so no schedule was made. The evidence chains were checked; the
profile editor read `leavers-synthetic.csv` and mapped its columns without saving a
profile or importing it; three clients were chosen and the two dialogs were opened and
closed with Cancel; the control drawer was opened; the theme (stored with the account),
the rail and the 3D view were switched with their own buttons.

## Reading the pictures

- The scenes start hidden. `home-1440-scenes-hidden-dark.png` is Home as it opens; every
  other picture of a scene shows it after **Show the 3D view** was pressed, a choice the
  browser keeps for Home, the client overview and the Evidence Explorer together.
- The local seed gives two clients a score (Seed Gaps 17.4 today and 16.0 at its last
  report, Seed Tidy 49.0) and two
  evidence too thin for one (Seed Empty and Seed Stale, drawn in scaffolding with a
  lower bound); the pictures show that state as it was.
- The installation pictured has no business name, so the report pictures show none,
  the report builder warns that a report cannot be exported yet, and the export history
  is empty. It has no exception and no deleted client either.
- On the phone pictures the navigation wraps onto three rows, and the tabs of a client
  are a strip that scrolls sideways; the chevron at its right edge says more links lie
  beyond ([design system](../design-system.md)).
- The Evidence Explorer turns by itself until a person touches it, so each of its
  pictures shows the scene at the angle of that moment.
- `report-preview-file-full-1440.png` is the whole rendered review, 15,774 px tall; it
  was judged by its structure and the text of the page.

## Known limits of this set

- A local build, not a deployment: the pictures do not prove what the Development site
  serves, only what this commit draws with the local seed.
- The scenes were drawn by a hardware GPU in headless Chrome; no phone or touch screen.
- The note a stage shows when the browser refuses a WebGL context is not pictured: the
  capture browser draws the scenes ([guide 8](../guides/08-scenes-rail-and-explorer.md)).
- The run of the Microsoft 365 export script is not pictured: it runs on the MSP's own
  machine against a tenant, and the documentation set has no tenant
  ([guide 10](../guides/10-microsoft-365-export.md)).
- The account menu is not pictured open, and the System page shows no worker and no
  schedule, because the local run starts the web process only.

## History

The earlier capture sets are history and are not used as the current preview: the 62
pictures captured on the evening of 2026-11-12 on a local build of `6ee1bba0`, the 26
pictures captured again on the morning of 2026-11-12 on `38da74b7` (Development), the
set of 2026-11-11 (taken on `99aaf21b`, Development), the set of 2026-10-27 (taken on
`d0a2e9fe`, `f6fc7085` and `ab870e4d`, schema 4), the set of 2026-10-25 (taken on
`b4634182`, schema 4), the set of 2026-10-24 (taken on `314d239c`, schema 4) and the
sets of 2026-10-21 and 2026-10-22 (taken on `c41125fd`, `f143e3db` and `6247addf`,
schema 3). The pictures replaced here are kept byte for byte in git at the base commit
of this set (`git show 544b16606e7475b8b10db186c8ff38db78800eb7:docs/images/<file>`),
with their manifest, and in the earlier review packages in Nextcloud
(`Documentation/` of the product folder), which are left untouched. Each replaced
picture keeps the hash of its predecessor in the manifest.
