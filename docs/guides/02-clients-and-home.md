# 2. Home and clients

## Home: where every client stands

Signed in, you land on **Home**. It is read from the same stored reports and snapshots
as the client pages; nothing on it is a check run on the fly.

![Home at 1440 px](../images/home-1440.png)

From top to bottom:

1. Four stat cards: clients, controls protected, controls that need work and exports to
   refresh, each with the change since the last reports.
2. **Posture by client**: a ring per client with the band of its last report. A dashed
   ring with a question mark means the evidence is too thin for a score
   (**Insufficient evidence**).
3. **Needs attention**: the gate controls first, then what is not protected, by weight,
   across all clients. **Open** goes to the control page.
4. **Score over time** from the stored reports of the last 7, 30 or 90 days, and
   **Controls by domain** as one bar per domain; **Show the numbers** opens the table
   behind each chart. Point at a mark or a segment, or reach it with Tab and the
   arrow keys, for its exact values; a mark opens that report.
5. **Recent changes**: the newest entries of the audit trail that changed a client, its
   evidence or its reports. A deleted client is named by its number.

On a phone the cards stand one to a row and the navigation is a scrolling bar.

![Home on a phone](../images/home-390.png)

## Clients: the list

Open **Clients** in the Work group. Every client shows the posture of its last report,
the controls at that report as pills with counts, the newest evidence with its age, and
the links **Open**, **Checklist**, **Evidence** and **Reports**.

![The clients list at 1440 px](../images/clients-1440.png)

- **Search by name** and the chips **All clients**, **Needs work**, **No report yet** and
  **No evidence yet** filter the list; the headings sort it; **Comfortable** and
  **Compact** change the density. Fifty clients make a page.
- Below 1024 px the rows are cards, two to a row from 768 px and one on a phone.

![The clients list at 768 px](../images/clients-768.png)

![The clients list on a phone](../images/clients-390.png)

## Add a client

1. Press **Add a client** at the top of the list, or use the card at its bottom.
2. Type the **Client name** as it should appear on reports and press **Add client**.
3. The client opens on its overview, ready for its first import
   ([3. Import evidence](03-import-evidence.md)).

## The overview of a client

The overview has the client header with the way back, the tabs **Overview**,
**Checklist**, **Evidence and imports**, **Exceptions**, **Reports** and
**Export history**, and the two actions **Review flagged controls** and
**Prepare a report**.

![The overview of a client at 1440 px](../images/client-overview-1440.png)

- The period picker at the top chooses the quarter a report would cover; **Show this
  period** reloads the page for it. The evidence is always read as it is today.
- **Where the client stands** is the posture ring with the band, the coverage, the
  exports to refresh and the change since the last report, with the summary sentence
  the report would print.
- **Controls by status** is the bar and the four pills; **Open the checklist** leads to
  every control with its evidence.
- **Needs attention** lists the controls to fix first for this client.
- **Coverage by domain** is one bar per domain with its weight and score.
- **How fresh is the evidence?** names the sources that need a fresh export and lists
  every source with its newest export and the date it goes stale.
- **Recent changes** is the audit trail of this client.

Next: [3. Import evidence](03-import-evidence.md).
