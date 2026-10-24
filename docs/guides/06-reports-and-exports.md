# 6. Reports and exports

Two reports are made from one stored state of a client: the **quarterly security
review** and the **cyber insurance evidence pack**, each as one HTML file with print
styles ([reports](../reports.md)). There is no PDF export in the Community Edition:
print the HTML file to PDF from the browser if you need one.

Before the first export, set the name of your business in **Settings**
([1. First start](01-first-start.md)).

## The report builder

Open a client and its tab **Reports** (or **Prepare a report** on the overview).

![The report builder at 1440 px](../images/report-builder-1440.png)

1. **Choose the period.** The quarter the report covers; the last full quarter is
   chosen for you. Change the dates if you like and press **Use this period**. The
   evidence is still read as it is today. A period may not be longer than 400 days or
   end in the future.
2. **Write the details.** **Prepared by** goes on the cover; **Plan for next quarter**
   is one line per step and becomes the numbered plan at the end of the review; the
   insurance topics and the owner of each go into the pack. Everything here is saved as
   you type (the line under the form shows when); **Save the details** posts it without
   script. The notes for each control are written on its own page
   ([4. The checklist](04-checklist-and-control-notes.md)).
3. **Make the report.** Press **Make the report for this period**. This stores the
   state of the client today as a snapshot and opens the preview page. A second press
   within 30 seconds opens the report the first press made instead of storing another.

**Reports made before** lists every report of this client, the newest first, with its
period and pack date; **Preview and export** opens each from the snapshot it was made
from.

## Preview and export

![Preview and export at 1440 px](../images/report-preview-1440.png)

- The band says whether the report is ready to export, with the controls, the open
  exceptions, the data sources and the preparer. **Before you export** lists what
  stops an export, each line saying what is missing; the usual first one is the
  business name.
- The paper sheet shows the cover and the summary as the client receives them: the
  period, the pack date, the summary sentence and the counts by status.
- **The reports**: for each of the two, **Preview** opens the file as it would be sent,
  and **Export the quarterly security review** or **Export the cyber insurance
  evidence pack** keeps an unchangeable copy and its SHA-256 and opens the export
  history.
- A file is made from the stored snapshot together with what is current when it is
  made: the details of step 2, the open exceptions of the client and the date it is
  generated. A preview or an export made later of the same report therefore shows an
  exception recorded after the snapshot, and the band counts it. The same snapshot,
  details, exceptions and date give the same bytes, and the export history keeps every
  exported file exactly as it was sent.

## The rendered report

**Preview** of the quarterly security review opens the file itself, as the client
receives it: one HTML page laid out as paper. The cover carries the name of your
business (from Settings), the client, the period, who prepared it, the date it was
generated, the pack date, the data sources and the id of the snapshot it was made
from, followed by the disclaimer that every report prints.

![The cover of the rendered quarterly security review at 1440 px](../images/report-preview-file-1440.png)

The whole file, from the cover through the summary, the findings, the plan for next
quarter, the evidence, the exceptions register and the appendix of each domain to the
important notice, is one tall picture in
[report-preview-file-full-1440.png](../images/report-preview-file-full-1440.png); its
sections are described in [reports](../reports.md). The cyber insurance evidence pack
opens the same way from its own **Preview** and is not pictured here.

## The export history

Open the tab **Export history** of the client.

![The export history at 1440 px](../images/export-history-1440.png)

Every file that was exported is kept as it was sent, with the time (UTC), the report,
the file name, the size, the SHA-256 and who exported it. **Download** sends the kept
copy, checked against that hash, and never makes it again; a copy altered on disk is
reported instead of sent. Deleting the client deletes its exports.

Next: [7. Settings, System and the glossary](07-settings-system-and-glossary.md).
