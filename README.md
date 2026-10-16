# Maple Freight: Shaoyi Lu

## How to run it

This build uses only the Python standard library.

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

1. **Item:** Stop V-137 before dispatch. **Why it matters:** a new P0524 low-oil-pressure fault appeared after the vehicle was cleared for dispatch this morning. The DTC reference says to stop immediately even though the vendor labelled it MEDIUM. **Evidence from the data:** P0524 was recorded at 2:32 p.m. ET at 96 kPa. WO-5540 closed at 7:40 a.m. for a different issue, the P0217 coolant sensor. **Next action (who, by when):** Operations places V-137 on dispatch hold now; Maintenance verifies oil pressure mechanically before release.
2. **Item:** Move V-151's service forward and hold the vehicle. **Why it matters:** the vehicle combines a recent P0300 misfire with the fleet's largest maintenance overrun. **Evidence from the data:** P0300 occurred Sep 20 at 3:09 p.m. ET; the latest maintenance alert is 2,350 km overdue; WO-5541 is only scheduled for Oct 5. **Next action (who, by when):** Hamilton Depot removes V-151 from tomorrow's dispatch and escalates inspection before release.
3. **Item:** Confirm V-158 remains out of service. **Why it matters:** a P0300 misfire was detected less than one hour before the 6:00 p.m. review. **Evidence from the data:** the alert occurred at 5:09 p.m.; WO-5543 opened at 5:30 p.m. and books inspection for Sep 22 morning, but no explicit dispatch hold is recorded. **Next action (who, by when):** Operations marks V-158 unavailable for the 6:00 a.m. dispatch until Maintenance clears WO-5543.

## What I built, and for whom

I built a local web dashboard for the operations manager's evening review and morning dispatch preparation. It converts the export into a capped action queue, explains each priority, provides evidence and a next action, and lets the user filter by priority and category. It also shows why the claim that D-17 is clearly the worst driver is not supported without normalizing for kilometres and firmware.

## Assumptions I made

- The operating cutoff is Sep 21, 2026 at 6:00 p.m. Eastern, as stated in the brief.
- Event time determines when an incident happened; received time is used only to diagnose reporting delay.
- Rows with the same vehicle, driver, alert type, event time, value, unit, posted limit and DTC represent the same underlying event even if alert IDs differ. I collapse 134 extra rows for prioritization but leave the source files unchanged.
- Device-unplugged and camera-offline events from 11:00 p.m. to midnight local time are expected update-window noise.
- A negative `maintenance_due` value means the vehicle is not yet due and should not be escalated.
- DTC reference urgency overrides vendor severity when they disagree. There are 35 such disagreements among 120 deduplicated engine-fault events.
- An open work order shows that work has started, but it does not prove that Operations has placed the vehicle on dispatch hold unless the note says so.
- Driver alert counts should be normalized per 1,000 km. Firmware 4.2.1 records 20.6 safety alerts per 1,000 km versus 8.1 for 4.3.0, so comparisons across firmware versions are not equivalent.

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
- Added automated tests for the Top 3, deduplication, known noise, severity conflicts and normalized driver rates.

## AI use

- **Tools I used:** OpenAI Codex for data exploration, implementation, test generation and review.
- **What AI did for me:** It helped inspect the supplied files, identify cross-file inconsistencies, propose a prioritization approach, implement the zero-dependency dashboard and draft tests and documentation.
- **One thing AI got wrong or incomplete, and how I caught it:** The initial idea focused too heavily on vendor HIGH alerts. Cross-checking `dtc_reference.csv` exposed a MEDIUM-labelled P0524 event that the reference classifies as critical, so I changed the ranking to use DTC urgency and work-order timing.
- **Link to / export of my AI session:** https://github.com/ShaoyiLu/maple

## If I had two more days

I would validate thresholds with Maple Freight staff, add persistence for acknowledgement and ownership, test the ranking against historical outcomes, and separate device-health monitoring from driver-safety review. I would also add refresh support and regression fixtures for additional exports.
