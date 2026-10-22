# Screenshots of the web interface

The pictures the [guides](../guides/README.md) use. Every one is a live capture of the
Development site of revrook CE (`https://ce-dev-revrook.theriark.dev`), signed in as
the one administrator account of that test installation, with synthetic data only. No
picture is a mock-up, and none holds a credential, a real person or another
environment.

`MANIFEST.json` in this folder is the capture manifest: for every picture its file name,
SHA-256, size in bytes and pixels, the environment, the page and the role, the viewport
width, the capture time in Europe/Lisbon (and UTC), the commit and image digest the
site ran at that moment, and the guides that use it; for the set, the capture-time
commit and digest of the first capture and how each was read, the version the
application showed, the state of the release candidate label, the flows that were not
captured and why, and what is unchanged. A reviewer compares the hash of each file
with the manifest; the manifest changes only when a picture is captured again, and a
picture is captured again only when the page it shows changed or when its content
needed a cleaner state. A picture that replaced an earlier one keeps the hash, the time
and the reason of the one it replaced under `replaces`.

The commit and digest in the manifest are capture-time facts: what the Development
site ran when each picture was taken. For the pictures of 2026-10-21 they are not the
deployed Development candidate (its commit and digest are read from the deployment
receipt and recorded in [release-candidate.md](../release-candidate.md)), and no match
between a capture-time image and the deployed image is claimed. The application pages
are the same between the capture-time commits and the documentation head, because the
commits in between changed documentation only. For the pictures of 2026-10-22 the
manifest carries the commit and digest the deployment receipt returned before and
after the capture, which named the deployed candidate; the pages themselves were not
asked.

Four pictures were captured again on 2026-10-21 between 20:31 and 20:33
(Europe/Lisbon), while the deployed Development candidate of that day was running:
`settings-1440.png` and `report-preview-1440.png`, because the first capture showed
the business name "FE Retest MSP THE-497" left by an earlier test (the name was set to
"Sample MSP" in Settings, the only state change made for the capture, and the preview
page prints that name at render time), and the two new pictures of the rendered
quarterly security review that **Preview** opens, `report-preview-file-1440.png` (the
cover at the viewport size) and `report-preview-file-full-1440.png` (the whole file,
15,615 px tall). For these four the manifest carries the commit and digest of the
deployed candidate, read from the deployment receipt: the pages themselves could not
tell the two commits of that day apart, because no static file changed between them
and the stylesheet version query stayed the same.

Six pictures were captured again on 2026-10-22 between 01:29 and 01:31
(Europe/Lisbon): the clients list at 1440, 768 and 390 px, Home at 1440 and 390 px and
the System page. Their first capture showed a second synthetic test client whose name
carried an internal ticket number; that client was deleted through **System**,
**Delete a client** (typing its name, the only route the product offers), the only
state change made for the capture, and the pages were captured again. The manifest
records what each picture replaced.

Three pictures were captured again on 2026-10-22 between 08:35 and 08:38
(Europe/Lisbon), while the deployed Development candidate of that day was running:
`evidence-integrity-1440.png`, `exceptions-1440.png` and
`profile-editor-preview-1440.png`. Their first capture still showed test labels with
internal ticket numbers that the product offers no route to edit on the sample client
(the chain of a since-deleted test client, the owner and reason of a closed exception,
and a saved profile name). Evidence integrity was captured on the shared data after
**Check all chains**, where every deleted client is named by its number only. For the
other two a throwaway client with a neutral invented name was added, one open exception
with a neutral owner and reason was recorded on it, a two-row synthetic leavers file was
read in the profile editor and its mapping saved under a neutral profile name, and the
throwaway client was then deleted through **System**, **Delete a client** (typing its
name); the sample client was not changed. For these three the manifest carries the
commit and digest of the deployed candidate, read from the deployment receipt before
and after the capture.

Viewports: 1440 px for every page; 390 px for the four pages whose layout changes most
on a phone (the clients list, Home, the checklist and the sign-in page); 768 px for the
clients list only, where the rows become two cards to a row. A picture named `-1440` is
the whole page at 1440 px unless the manifest says `fullPage: false` (the checklist,
whose 51 rows would make the picture very tall, the problem page, and the cover of the
rendered report, whose whole file has its own picture).

What the pictures show is the shared Development test installation: every client,
report and audit entry in them is synthetic. The **Recent changes** list on Home names
clients that were added and deleted by earlier automated tests and reviews ("a deleted
client (client 4)", "client 14" and so on). Those lines are audit entries, which the
product keeps on purpose after a client is deleted
([7. Settings](../guides/07-settings-system-and-glossary.md#system)), so they cannot be
removed without deleting the database; they name a deleted client by its number only,
and the Home pictures of 2026-10-22 show them as they were at that moment.

On the phone picture of the checklist (`checklist-390.png`) the tab bar of the client
ends with "Evidence and impo": the strip is cut at the right edge of the viewport by
design. The tabs of a client are a strip that scrolls sideways when they are wider than
the page (`main nav` has `overflow-x: auto` and `div.rv-tabs-strip` fades the last
visible tab into the background at the right edge, so a person sees that it goes on;
[design system](../design-system.md), tested in `tests/test_webui_fixes.py` and
`tests/test_webui_followup.py`). It is intended horizontal scrolling, not a clipped
control: a swipe or a Tab key press brings **Exceptions**, **Reports** and **Export
history** into view.
