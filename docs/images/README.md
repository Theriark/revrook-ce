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
needed a cleaner state.

The commit and digest in the manifest are capture-time facts: what the Development
site ran when each picture was taken. They are not the deployed Development
candidate (its commit and digest are read from the deployment receipt and recorded in
[release-candidate.md](../release-candidate.md)), and no match between a capture-time
image and the deployed image is claimed. The application pages are the same between
the capture-time commits and the documentation head, because the commits in between
changed documentation only.

Viewports: 1440 px for every page; 390 px for the four pages whose layout changes most
on a phone (the clients list, Home, the checklist and the sign-in page); 768 px for the
clients list only, where the rows become two cards to a row. A picture named `-1440` is
the whole page at 1440 px unless the manifest says `fullPage: false` (the checklist,
whose 51 rows would make the picture very tall, and the problem page).

What the pictures show is the shared Development test installation: every client,
report and audit entry in them is synthetic. The **Recent changes** list on Home names
clients that were added and deleted by earlier automated tests ("a deleted client
(client 9)" and so on). Those lines are audit entries, which the product keeps on
purpose after a client is deleted ([7. Settings](../guides/07-settings-system-and-glossary.md#system)),
so they cannot be removed without deleting the database; every later capture of Home
shows more of them, not fewer, and the Home pictures were therefore kept from the first
capture.

On the phone picture of the checklist (`checklist-390.png`) the tab bar of the client
ends with "Evidence and impo": the strip is cut at the right edge of the viewport by
design. The tabs of a client are a strip that scrolls sideways when they are wider than
the page (`main nav` has `overflow-x: auto` and `div.rv-tabs-strip` fades the last
visible tab into the background at the right edge, so a person sees that it goes on;
[design system](../design-system.md), tested in `tests/test_webui_fixes.py` and
`tests/test_webui_followup.py`). It is intended horizontal scrolling, not a clipped
control: a swipe or a Tab key press brings **Exceptions**, **Reports** and **Export
history** into view.
