# Guides

Step-by-step tutorials for every flow of the revrook Community Edition web interface,
in the order a new installation meets them. Every picture is a live capture of the
Development site (`https://ce-dev-revrook.theriark.dev`) taken on 2026-10-25 from the
application build documented and captured (commit
`b4634182e0fd68d760c209fcc6051ff9adceea2e`), with the synthetic test data of that site;
one picture of the profile editor is still from the set of 2026-10-24 (see the
[capture manifest](../images/README.md#known-limits-of-this-set)).
Later documentation-only commits are deployed on top with the same application code; the
deployed head is read from the deployment receipt and the package manifest. The pictures
are in [docs/images](../images/README.md) with a capture manifest (file, SHA-256, page,
viewport, theme, capture time and the guide that uses each). What the output is, and is
not, is in the [README](../../README.md): a configuration evidence summary, not a
certification.

| Guide | What you do |
| --- | --- |
| [1. First start and sign-in](01-first-start.md) | Create the one administrator, sign in, set the business name, sign out |
| [2. Home and clients](02-clients-and-home.md) | Read the dashboard, the rookery and what moves the score, read the score chart with few reports, add a client, open its overview |
| [3. Import evidence](03-import-evidence.md) | Map a vendor export in the profile editor, import it, read the evidence page, check the hash chains |
| [4. The checklist and the notes of a control](04-checklist-and-control-notes.md) | Read the 51 controls, search, filter and order them, open a control in the drawer, write the four lines a report prints |
| [5. Exceptions](05-exceptions.md) | Record that a client knowingly accepts a gap, and close it later |
| [6. Reports and exports](06-reports-and-exports.md) | Choose the period, write the details, make the report, preview and export it, read the rendered review on a screen or a phone, find it in the export history |
| [7. Settings, System and the glossary](07-settings-system-and-glossary.md) | The fixed facts of the installation, the worker, the data export, deleting a client, the glossary and the problem page |
| [8. Scenes, the folded rail and the Evidence Explorer](08-scenes-rail-and-explorer.md) | Read and steer the rookery and the domain keep, hide or show the scenes, fold the rail, choose the theme, explore which exports feed which controls |
| [9. The top bar, the filters in use and bulk actions](09-top-bar-filters-and-bulk-actions.md) | Find a page and a client from the top bar, remove the filters of the clients list, make reports for, download or delete several clients at once |

Every guide uses the same test installation and its administrator account. The clients
("Seed Gaps Ltd (synthetic)", "Seed Tidy Ltd (synthetic)" and the others), "Sample MSP"
(the business name of the test installation), the leavers file and the exception in the
pictures are synthetic test data; nothing in them is a real customer, a real address or
a credential. Two parts of the live pages are kept out of every picture because they
name a seeded sign-in account of the Development installation: **Recent changes** on
Home and on a client overview, and **Users and mappings** in Settings (see the capture
manifest).
