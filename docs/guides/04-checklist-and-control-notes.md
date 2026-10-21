# 4. The checklist and the notes of a control

## The checklist

Open a client and its tab **Checklist**. It lists the 51 controls of the library as a
report made today would show them, with the evidence behind each status.

![The checklist at 1440 px](../images/checklist-1440.png)

- The filter band has two chips with counts: **All controls** and **Changed or needs a
  look** (the controls whose status changed since the last report or that need
  attention). The line under them says how many rows are shown.
- Each row: the control in plain language with its identifier and whether it is a gate
  control, the **Status** as an icon and words (Protected, Needs attention, Not
  protected, Not checked), the **Coverage**, the date of the evidence, the **Owner** of
  the open exception if any, and **Why it needs a look**.
- A violet mark on a row means its status changed since the last report. The head of
  the table stays in view while you scroll; on a phone every control is a card.

![The checklist on a phone](../images/checklist-390.png)

A status is never shown by colour alone. **Not checked** means nothing was verified:
there is no dated evidence for the control ([controls](../controls.md)).

## The page of a control

Press the name of a control (or **Open** in a Needs attention list).

![The page of a control at 1440 px](../images/control-1440.png)

1. The verdict band: the status as a large pill beside the facts of the evidence (the
   date, its state, its type and the coverage).
2. **What was checked**: the rule in words and the finding, for example how many leavers
   are still enabled after the grace period.
3. **Exceptions for this control**: the open exception with its owner and review date,
   or the empty state with **Add one on the exceptions page**
   ([5. Exceptions](05-exceptions.md)).
4. **Your notes**: the four lines the report prints for this control, **What we did**,
   **What we recommend**, **What we need from you** and **By when**, with a suggested
   wording above them. Notes are saved as you type (the card says "Saving" while a
   note is posted); **Save notes** posts them without script.

To change a status, import newer evidence ([3. Import evidence](03-import-evidence.md)):
notes and exceptions never change a status and never raise the score.

Next: [5. Exceptions](05-exceptions.md).
