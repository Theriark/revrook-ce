# Guides

Step-by-step tutorials for every flow of the revrook Community Edition web interface,
in the order a new installation meets them. Every picture is a live capture, taken on
2026-11-12, of a local build of commit `544b16606e7475b8b10db186c8ff38db78800eb7` (the
merge of pull request #114) with the Evidence Explorer table fix of the same pull request
as these pictures, with the synthetic data of the
Development seed (see the [capture manifest](../images/README.md)); it is not a
capture of a deployment. Pictures at 1440 px are the desktop view; pictures at 768 px
and 390 px are labelled as tablet and phone views in their captions. The pictures
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
| [12. Export the cloud accounts with scripts](12-cloud-exports.md) | Run the read-only script of a cloud (AWS, Google Cloud) that writes its firewall rules, servers and backups as revrook CSV files, and drop them on Import evidence |

Every guide uses the same test installation and its administrator account
(`local-admin`). The clients ("Seed Gaps Ltd (synthetic)", "Seed Tidy Ltd (synthetic)"
and the others) and the leavers file in the pictures are synthetic test data; the
installation pictured has no business name set, so the report pictures show none.
Nothing in them is a real customer, a real address or a credential. The files imported for guide 3 are invented too (two leavers at
`seed.example.invalid`, a Conditional Access and an Intune export made by the
Development seed's own builders, and a help-desk file that matches no source). Two parts
of the pages stay out of the main pictures, as in the earlier sets, because on the shared
Development installation they name a seeded sign-in account: **Recent changes** on Home
and on a client overview, and **Users and mappings** in Settings (see the capture
manifest).
