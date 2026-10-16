# Maple Freight: Shaoyi Lu

## How to run it

Requires Python 3.9 or newer. No third-party packages or installation are required.

```powershell
python app.py
```

Open `http://127.0.0.1:8000` in a browser. To create a standalone HTML snapshot instead:

```powershell
python app.py --export
```

Run the checks with:

```powershell
python -m unittest -v
```

## Tonight's top 3 for Maple Freight

1. **Item:** Stop V-108 and inspect two critical faults. **Why it matters:** the Hamilton gateway backfill revealed both overheating and low oil pressure on the same vehicle; both occurred before the original review but were hidden by the outage. **Evidence from the data:** P0217 occurred at 12:05 p.m. ET at 107 °C and P0524 occurred at 3:41 p.m. ET at 88 kPa. Both were delivered at 6:47 p.m.; the only V-108 work order closed Sep 9 for unrelated P0171. **Next action (who, by when):** Hamilton Depot places V-108 on dispatch hold now; Maintenance checks the cooling and oil-pressure systems before tomorrow's 6:00 a.m. dispatch.
2. **Item:** Stop V-137 before dispatch. **Why it matters:** a new P0524 low-oil-pressure fault appeared after the vehicle was cleared for dispatch this morning. The DTC reference says to stop immediately even though the vendor labelled it MEDIUM. **Evidence from the data:** P0524 was recorded at 2:32 p.m. ET at 96 kPa. WO-5540 closed at 7:40 a.m. for a different issue, the P0217 coolant sensor. **Next action (who, by when):** Operations places V-137 on dispatch hold now; Maintenance verifies oil pressure mechanically before tomorrow's 6:00 a.m. dispatch.
3. **Item:** Move V-151's service forward and hold the vehicle. **Why it matters:** the vehicle combines a recent P0300 misfire with the fleet's largest maintenance overrun. **Evidence from the data:** P0300 occurred Sep 20 at 3:09 p.m. ET; the latest maintenance alert is 2,350 km overdue; WO-5541 is only scheduled for Oct 5. **Next action (who, by when):** Hamilton Depot removes V-151 from tomorrow's dispatch now and Maintenance inspects it before returning it to service.

## What I built, and for whom

I built a local web dashboard for the operations manager's evening review and morning dispatch preparation. It converts the export into a capped action queue, explains each priority, provides evidence and a next action, and lets the user filter by priority and category. It also shows why the claim that D-17 is clearly the worst driver is not supported without normalizing for kilometres and firmware.

## Assumptions I made

- The updated operating cutoff is Sep 21, 2026 at 6:47 p.m. Eastern, when the Hamilton gateway backfill arrived.
- Event time determines when an incident happened; received time identifies reporting delay. The 10 Hamilton backfill records are included even though their events happened earlier.
- Rows with the same vehicle, driver, alert type, event time, value, unit, posted limit and DTC represent the same underlying event even if alert IDs differ. I collapse 134 extra rows for prioritization but leave the source files unchanged.
- Device-unplugged and camera-offline events from 11:00 p.m. to midnight local time are expected update-window noise.
- A negative `maintenance_due` value means the vehicle is not yet due and should not be escalated.
- DTC reference urgency overrides vendor severity when they disagree. There are 37 such disagreements after the backfill.
- An open work order shows that work has started, but it does not prove that Operations has placed the vehicle on dispatch hold unless the note says so.
- Driver alert counts should be normalized per 1,000 km. Firmware 4.2.1 records 20.6 safety alerts per 1,000 km versus 8.1 for 4.3.0, so comparisons across firmware versions are not equivalent.

## What changed after the new information

The Hamilton backfill changed my priorities. V-108 moved to the top of the action queue because the delayed alerts contain both P0217 engine overheating and P0524 low oil pressure. Both faults occurred before the original 6:00 p.m. review but were not delivered until the Hamilton gateway reconnected at 6:47 p.m.

I updated the dashboard cutoff to 6:47 p.m., added the ten backfilled alerts, moved V-108 to first position, and moved V-158 out of the Top 3 because its misfire already has an open work order.

This also changed my data-quality conclusion: normal depot connectivity cannot be assumed. Alert delivery delay can hide urgent events, so the dashboard distinguishes event time from received time and highlights delayed critical faults.

## What I deliberately did NOT do (and why)

- I did not label every raw alert high, medium or low. Maple Freight can act on about 10 items per day, so I grouped evidence into operational actions.
- I did not use an LLM or paid API inside the product. The supplied structured data can be handled deterministically, which keeps the result reproducible and runnable offline.
- I did not treat visual polish as the primary goal. I prioritized a finished workflow, evidence and transparent logic.
- I did not infer route, weather, cargo or driver intent because those fields were not supplied.
- I did not recommend discipline from telematics counts alone. Firmware sensitivity and driving exposure create material confounding.

## How I checked it's correct

- Parsed UTC event and received timestamps separately and converted event times to America/Toronto.
- Recomputed duplicate signatures, expected nightly device noise, not-yet-due maintenance alerts and transmission delays.
- Cross-checked critical engine faults against `dtc_reference.csv` and against work-order open/close times.
- Verified that V-137's P0524 occurred after WO-5540 closed and concerns a different system than the repaired P0217 sensor issue.
- Verified that D-17 has the largest raw safety-event count but not the largest exposure-adjusted rate.
- Added automated tests for the changed Top 3, backfill counts, deduplication, known noise, delayed delivery, critical-fault evidence, queue rules and normalized driver rates.

## AI use

- **Tools I used:** OpenAI Codex / ChatGPT.
- **What AI did for me:** AI helped me explore the supplied files, identify cross-file inconsistencies, design the prioritization method, implement the dashboard, write automated tests and review the README.
- **One thing AI got wrong or incomplete, and how I caught it:** The initial idea focused too heavily on vendor HIGH alerts. Cross-checking `dtc_reference.csv` exposed a MEDIUM-labelled P0524 event that the reference classifies as critical, so I changed the ranking to use DTC urgency and work-order timing.
- **Link to / export of my AI session:** https://chatgpt.com/s/cx_6ad2714db094819196b8b6c68c6f4962

## If I had two more days

I would validate thresholds with Maple Freight staff, add persistence for acknowledgement and ownership, test the ranking against historical outcomes, and separate device-health monitoring from driver-safety review. I would also add refresh support and regression fixtures for additional exports.
