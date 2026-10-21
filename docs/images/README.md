# Screenshots of the web interface

The pictures the [guides](../guides/README.md) use. Every one is a live capture of the
Development site of revrook CE (`https://ce-dev-revrook.theriark.dev`), signed in as
the one administrator account of that test installation, with synthetic data only. No
picture is a mock-up, and none holds a credential, a real person or another
environment.

`MANIFEST.json` in this folder is the capture manifest: for every picture its file name,
SHA-256, size in bytes and pixels, the environment, the page and the role, the viewport
width, the capture time in Europe/Lisbon (and UTC) and the guides that use it; for the
set, the source commit and the immutable image digest that the site ran at capture time
and how each was read, the version the application showed, the state of the release
candidate label, the flows that were not captured and why, and what is unchanged. A
reviewer compares the hash of each file with the manifest; the manifest changes only
when a picture is captured again, and a picture is captured again only when the page
it shows changed.

Viewports: 1440 px for every page; 390 px for the four pages whose layout changes most
on a phone (the clients list, Home, the checklist and the sign-in page); 768 px for the
clients list only, where the rows become two cards to a row. A picture named `-1440` is
the whole page at 1440 px unless the manifest says `fullPage: false` (the checklist,
whose 51 rows would make the picture very tall, and the problem page).
