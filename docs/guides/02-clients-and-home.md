# 2. Home and clients

## Home: where every client stands

Signed in, you land on **Home**. It is read from the same stored reports and snapshots
as the client pages; nothing on it is a check run on the fly.

![Home at 1440 px, light theme](../images/home-1440.png)

From top to bottom:

1. Four stat cards: clients, controls protected, controls that need work and exports to
   refresh, each with the change since the last reports.
2. **Posture by client**: the rookery skyline, one rook per client as tall as its
   score, above a card per client with the ring and the band of its last report. A
   dashed ring with a question mark, and a wire rook, mean the evidence is too thin for
   a score (**Insufficient evidence**); a flat footprint means nothing is imported yet.
   The scene is a way of looking at the cards under it and never replaces them
   ([8. Scenes, the folded rail and the Evidence Explorer](08-scenes-rail-and-explorer.md)).
3. **Needs attention**: the gate controls first, then what is not protected, by weight,
   across all clients. **Open** shows the control in a drawer over the page
   ([4. The checklist](04-checklist-and-control-notes.md#the-drawer-and-the-page-of-a-control)).
   A client with an open exception for that control says so on the row.
4. **Score over time** from the stored reports of the last 7, 30 or 90 days, and
   **Controls by domain** as one bar per domain; **Show the numbers** opens the table
   behind each chart. Point at a mark or a segment, or reach it with Tab and the
   arrow keys, for its exact values; a mark opens that report.
5. **Recent changes**: the newest entries of the audit trail that changed a client, its
   evidence or its reports, with who made each change. A deleted client is named by its
   number. This list is not pictured: on the shared Development installation it names
   a seeded sign-in account (see the [capture manifest](../images/README.md)).

The picture above is the page at 1440 px wide down to the two charts. On a tablet the
navigation is a bar at the top and the cards stand two to a row; on a phone they stand
one to a row and the navigation scrolls sideways.

![Home at 768 px, light theme](../images/home-768.png)

![Home on a phone](../images/home-390.png)

![Posture by client on a phone](../images/home-390-rookery.png)

## Clients: the list

Open **Clients** in the Work group. Every client shows the posture of its last report,
the controls at that report as pills with counts, the newest evidence with its age, and
the links **Open**, **Checklist**, **Evidence** and **Reports**.

![The clients list at 1440 px](../images/clients-1440.png)

- **Clients by band** counts the clients in each band of their last report; a band
  narrows the list to those clients.
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

![The overview of a client at 1440 px, light theme](../images/client-overview-1440.png)

- The period picker at the top chooses the quarter a report would cover; **Show this
  period** reloads the page for it. The evidence is always read as it is today.
- **Where the client stands** is the posture ring with the band, the coverage, the
  exports to refresh and the change since the last report, with the summary sentence
  the report would print.
- **Controls by status** is the bar and the four pills; **Open the checklist** leads to
  every control with its evidence.
- **Needs attention** lists the controls to fix first for this client.
- **Coverage by domain** holds the domain keep, one block per domain as wide as its
  weight in the score and built of its controls in layers by status, above one bar per
  domain with its weight and score. A segment of a bar opens the checklist narrowed to
  that domain and status ([8. Scenes](08-scenes-rail-and-explorer.md#the-domain-keep-on-a-client-overview)).
- **How fresh is the evidence?** names the sources that need a fresh export and lists
  every source with its newest export and the date it goes stale.
- **Recent changes** is the audit trail of this client (not pictured, for the reason
  given under Home).

Next: [3. Import evidence](03-import-evidence.md).
