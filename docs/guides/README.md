# Guides

Step-by-step tutorials for every flow of the revrook Community Edition web interface,
in the order a new installation meets them. Every picture is a live capture of the
Development site (`https://ce-dev-revrook.theriark.dev`) taken on 2026-11-11 from the
application build documented and captured (commit `99aaf21b26a93a54b6db1aa5534e602c6e2e8541`, the merge of pull request
#90, image `sha256:6bd4e84cbbabccfd8b96ad5f44e9ed714262412bb81cceb61fdedb9c75967e6c`), with the synthetic test data of that site (see the
[capture manifest](../images/README.md)). Pictures at 1440 px are the desktop view;
pictures at 768 px and 390 px are labelled as tablet and phone views in their
captions. Later documentation-only commits are deployed on top with the same
application code; the deployed head is read from the deployment receipt and the
package manifest. The pictures
are in [docs/images](../images/README.md) with a capture manifest (file, SHA-256, page,
viewport, theme, capture time and the guide that uses each). What the output is, and is
not, is in the [README](../../README.md): a configuration evidence summary, not a
certification.

| Guide | What you do |
| --- | --- |
| [1. First start and sign-in](01-first-start.md) | Create the one administrator, sign in, set the business name, sign out |
| [2. Home and clients](02-clients-and-home.md) | Read the dashboard, the rookery and what moves the score, read the score chart with few reports, add a client, open its overview |
| [3. Import evidence](03-import-evidence.md) | Drop every export of a client on the import page and read what happened to each file, map a vendor export in the profile editor, read the evidence page, check the hash chains |
| [4. The checklist and the notes of a control](04-checklist-and-control-notes.md) | Read the 51 controls, search, filter and order them, open a control in the drawer, write the four lines a report prints |
| [5. Exceptions](05-exceptions.md) | Record that a client knowingly accepts a gap, and close it later |
| [6. Reports and exports](06-reports-and-exports.md) | Choose the period, write the details, make the report, preview and export it, read the rendered review on a screen or a phone, find it in the export history |
| [7. Settings, System and the glossary](07-settings-system-and-glossary.md) | The fixed facts of the installation, the worker, the data export, deleting a client, the glossary and the problem page |
| [8. Scenes, the folded rail and the Evidence Explorer](08-scenes-rail-and-explorer.md) | Show the 3D view, read and steer the rookery and the domain keep, hide the scenes again, fold the rail, choose the theme, explore which exports feed which controls |
| [9. The top bar, the filters in use and bulk actions](09-top-bar-filters-and-bulk-actions.md) | Find a page and a client from the top bar, remove the filters of the clients list, make reports for, download or delete several clients at once |
| [10. Export Microsoft 365 with the script](10-microsoft-365-export.md) | Run the read-only PowerShell script that writes the six Microsoft 365 files of a tenant, and drop them on Import evidence |
| [11. The public DNS check](11-public-dns-check.md) | Run the SPF, DKIM and DMARC check of a client's mail domains from its evidence page, once or every Monday, and read its result |

Every guide uses the same test installation and its administrator account. The clients
("Seed Gaps Ltd (synthetic)", "Seed Tidy Ltd (synthetic)" and the others), "Sample MSP"
(the business name of the test installation), the leavers file and the exception in the
pictures are synthetic test data; nothing in them is a real customer, a real address or
a credential. The files imported for guide 3 are invented too (two leavers at
`seed.example.invalid`, a Conditional Access and an Intune export made by the
Development seed's own builders, and a help-desk file that matches no source). Two parts
of the live pages are kept out of every picture because they name a seeded sign-in
account of the Development installation: **Recent changes** on Home and on a client
overview, and **Users and mappings** in Settings (see the capture manifest).
