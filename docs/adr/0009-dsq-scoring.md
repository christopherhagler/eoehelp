# ADR 0009 — Score dysphagia with the DSQ as published

**Status:** Accepted · 2026-09-18

## Context

The daily log was modelled on the Dysphagia Symptom Questionnaire (DSQ), but the
first implementation invented its own scoring:

- dysphagia was graded 1–3 by three homemade severity levels
- pain (0–3) was added on top
- the total was capped at 6 a day

The range came out as the DSQ's 0–84, but a given day produced a different
number than the real instrument, so scores could not be compared with the
trials that use the DSQ as their endpoint (budesonide oral suspension among
them). The log also could not record the instrument's actual third question:
it had no "coughed or gagged" answer, and it let patients choose several
coping actions where the DSQ asks for one.

## Decision

Ask and score questions 1–3 as published (Dellon ES et al., *Aliment Pharmacol
Ther* 2013):

| Question | Answer | Points |
|---|---|---|
| 1. Did you eat solid food? | No | The day is not a valid diary day |
| 2. Did food go down slowly or get stuck? | Yes | 2 |
| 3. At the worst time, what did you have to do to get relief? (one choice) | Nothing, it cleared on its own | 0 |
| | Drank liquid | 1 |
| | Coughed or gagged | 2 |
| | Vomited | 3 |
| | Sought medical attention | 4 |

The 14-day score is the sum of daily points × 14 ÷ the number of valid diary
days, giving a range of 0–84.

**Pain on swallowing** is still recorded, but it is not part of the total. It
is reported alongside the score.

An **emergency visit for impacted food** is also still recorded, as a separate
flag. It requires the question 3 answer "sought medical attention".

The database enforces the question logic, and the API validator explains it:

- A day with no solid food has no dysphagia answer.
- A solid-food day must answer question 2.
- Question 3 is answered exactly when question 2 is yes.

The score's components break down the question 3 answers, so a clinician can
see what drives the number.

## Open, and blocking before any score reaches a clinician

- **The licence.** It is not confirmed. The seeded attribution previously
  claimed a Creative Commons licence, which was never verified; it now says
  the terms are unconfirmed.
- **The minimum number of valid days** for a window to be scored. The code
  uses 7, and some trials have required more.
- **The exact question wording** against the v4.0 instrument.

A gastroenterologist must sign off all three, alongside the EREFS and
histology items in ADR 0007's successor work.

## Consequences

- The `dysphagia_severity` and `coping_actions` columns are gone, replaced by
  `dysphagia_relief`. Migration 0002 was edited in place, because no deployed
  database exists.
- Synthetic histories draw question 3 answers weighted by severity.
- Scores computed before this change are not comparable with scores computed
  after it. No real patient data exists yet, so nothing is lost.
