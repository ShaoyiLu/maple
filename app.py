"""Maple Freight action dashboard.

Runs with the Python standard library only. It reads the supplied CSV files,
reconciles them, and serves a small decision dashboard for the 6:00 p.m.
September 21, 2026 operating review.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
ET = ZoneInfo("America/Toronto")
AS_OF = datetime(2026, 9, 21, 18, 0, tzinfo=ET)


def read_csv(name: str) -> list[dict[str, str]]:
    with (DATA / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def number(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_local(value: str) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M").replace(tzinfo=ET)


def event_signature(row: dict[str, object]) -> tuple[object, ...]:
    return tuple(
        row.get(key, "")
        for key in (
            "vehicle_id", "driver_id", "alert_type", "event_time_utc", "value",
            "unit", "posted_limit_kmh", "dtc_code",
        )
    )


def build_model() -> dict[str, object]:
    raw_alerts = read_csv("alerts.csv")
    vehicles = {row["vehicle_id"]: row for row in read_csv("vehicles.csv")}
    dtc = {row["dtc_code"]: row for row in read_csv("dtc_reference.csv")}
    work_orders = read_csv("work_orders.csv")

    alerts: list[dict[str, object]] = []
    seen: set[tuple[object, ...]] = set()
    for source in raw_alerts:
        row: dict[str, object] = dict(source)
        signature = event_signature(row)
        if signature in seen:
            continue
        seen.add(signature)
        row["event_utc"] = parse_utc(str(row["event_time_utc"]))
        row["received_utc"] = parse_utc(str(row["received_time_utc"]))
        row["event_et"] = row["event_utc"].astimezone(ET)  # type: ignore[union-attr]
        row["delay_seconds"] = (
            row["received_utc"] - row["event_utc"]  # type: ignore[operator]
        ).total_seconds()
        row["value_num"] = number(str(row.get("value", "")))
        row["limit_num"] = number(str(row.get("posted_limit_kmh", "")))
        row.update({f"vehicle_{key}": value for key, value in vehicles[row["vehicle_id"]].items()})
        code = str(row.get("dtc_code", ""))
        row["dtc"] = dtc.get(code)
        alerts.append(row)

    duplicate_extras = len(raw_alerts) - len(alerts)
    night_noise = [
        row for row in alerts
        if row["alert_type"] in {"device_unplugged", "camera_offline"}
        and row["event_et"].hour == 23  # type: ignore[union-attr]
    ]
    future_maintenance = [
        row for row in alerts
        if row["alert_type"] == "maintenance_due"
        and (row["value_num"] or 0) < 0
    ]
    delayed_1h = [row for row in alerts if row["delay_seconds"] > 3600]
    delayed_24h = [row for row in alerts if row["delay_seconds"] > 86400]

    fault_rows = [row for row in alerts if row["alert_type"] == "engine_fault"]
    severity_mismatch = 0
    for row in fault_rows:
        reference = row["dtc"]
        if not reference:
            continue
        expected = str(reference["reference_urgency"]).split()[0].upper()
        if row["vendor_severity"] != expected:
            severity_mismatch += 1

    work_by_vehicle: dict[str, list[dict[str, object]]] = defaultdict(list)
    for source in work_orders:
        row: dict[str, object] = dict(source)
        row["opened_et"] = parse_local(str(row.get("opened_local", "")))
        row["closed_et"] = parse_local(str(row.get("closed_local", "")))
        work_by_vehicle[str(row["vehicle_id"])].append(row)

    by_vehicle: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in alerts:
        by_vehicle[str(row["vehicle_id"])].append(row)

    def vehicle_context(vehicle_id: str) -> tuple[str, str]:
        vehicle = vehicles[vehicle_id]
        return vehicle["depot"], vehicle["assigned_driver"]

    def action(
        vehicle_id: str, score: int, priority: str, category: str, title: str,
        why: str, evidence: list[str], next_step: str, status: str = "Needs action",
    ) -> dict[str, object]:
        depot, driver = vehicle_context(vehicle_id)
        return {
            "vehicle": vehicle_id, "driver": driver, "depot": depot,
            "score": score, "priority": priority, "category": category,
            "title": title, "why": why, "evidence": evidence,
            "next_action": next_step, "status": status,
        }

    actions: list[dict[str, object]] = []

    # Cross-source decisions that matter before the next dispatch.
    v137_fault = next(
        row for row in by_vehicle["V-137"]
        if row["alert_type"] == "engine_fault" and row["dtc_code"] == "P0524"
    )
    actions.append(action(
        "V-137", 100, "Critical", "Maintenance",
        "Stop V-137 before dispatch",
        "A new low-oil-pressure fault appeared after the vehicle was cleared this morning. The DTC reference says to stop immediately even though the vendor labelled it MEDIUM.",
        [
            f"P0524 at {v137_fault['event_et']:%b %d, %I:%M %p} ET; measured value 96 kPa.",
            "WO-5540 closed at 7:40 a.m. for a different issue (P0217 coolant sensor).",
            "The new fault occurred 6 h 52 min after the repair was closed.",
        ],
        "Operations: place V-137 on dispatch hold now. Maintenance: verify oil pressure mechanically before release.",
    ))

    v151_fault = max(
        (row for row in by_vehicle["V-151"] if row["alert_type"] == "engine_fault" and row["dtc_code"] == "P0300"),
        key=lambda row: row["event_et"],
    )
    v151_maint = max(
        (row for row in by_vehicle["V-151"] if row["alert_type"] == "maintenance_due"),
        key=lambda row: row["event_et"],
    )
    actions.append(action(
        "V-151", 94, "Critical", "Maintenance",
        "Move V-151 service forward and hold it",
        "The vehicle combines a recent misfire with the largest maintenance overrun in the fleet. Its current service date is two weeks away.",
        [
            f"P0300 misfire at {v151_fault['event_et']:%b %d, %I:%M %p} ET; reference requires inspection within 24 h.",
            f"Latest maintenance alert: {v151_maint['value_num']:,.0f} km overdue.",
            "WO-5541 is only scheduled for Oct 5; no completed repair is recorded.",
        ],
        "Hamilton Depot: do not dispatch V-151. Escalate the service slot and inspect the misfire before release.",
    ))

    v158_fault = next(
        row for row in by_vehicle["V-158"]
        if row["alert_type"] == "engine_fault" and row["dtc_code"] == "P0300"
        and row["event_et"].date() == AS_OF.date()
    )
    actions.append(action(
        "V-158", 90, "High", "Maintenance",
        "Confirm V-158 remains out of service",
        "A misfire was detected less than an hour before this review. The shop opened a work order, but dispatch status is not explicitly recorded.",
        [
            f"P0300 at {v158_fault['event_et']:%b %d, %I:%M %p} ET; vendor and reference both rate it HIGH.",
            "WO-5543 opened at 5:30 p.m.; inspection is booked for Sep 22 morning.",
            "No closed repair or explicit 'not dispatched' note exists.",
        ],
        "Operations: mark V-158 unavailable for the 6:00 a.m. dispatch until maintenance clears WO-5543.",
        "In progress",
    ))

    # Add acute safety items from the last 24 hours, grouped by vehicle.
    recent_cutoff = AS_OF - timedelta(hours=24)
    recent_safety: dict[str, dict[str, object]] = defaultdict(lambda: {
        "max_over": None, "max_g": None, "high_count": 0, "events": 0, "latest": None,
    })
    for row in alerts:
        if row["event_et"] < recent_cutoff or row["alert_type"] not in {
            "speeding", "harsh_braking", "harsh_accel", "harsh_cornering",
        }:
            continue
        info = recent_safety[str(row["vehicle_id"])]
        info["events"] += 1
        info["high_count"] += int(row["vendor_severity"] == "HIGH")
        info["latest"] = max(info["latest"] or row["event_et"], row["event_et"])
        if row["alert_type"] == "speeding" and row["limit_num"] is not None:
            over = row["value_num"] - row["limit_num"]
            info["max_over"] = max(info["max_over"] or over, over)
        elif row["value_num"] is not None:
            info["max_g"] = max(info["max_g"] or row["value_num"], row["value_num"])

    for vehicle_id, info in recent_safety.items():
        max_over = info["max_over"] or 0
        max_g = info["max_g"] or 0
        if max_over < 20 and max_g < 0.70:
            continue
        score = min(79, int(48 + max_over + (10 if max_g >= 0.70 else 0) + min(info["high_count"] * 2, 6)))
        evidence = [f"{info['events']} safety events in the last 24 hours."]
        if max_over:
            evidence.append(f"Maximum observed speed: {max_over:.0f} km/h over the posted limit.")
        if max_g:
            evidence.append(f"Maximum harsh-event reading: {max_g:.2f} g.")
        actions.append(action(
            vehicle_id, score, "High" if score >= 72 else "Medium", "Safety",
            f"Review recent driving for {vehicle_context(vehicle_id)[1]}",
            "Recent driving contains an acute event that is more actionable than a raw 14-day alert count.",
            evidence,
            "Safety manager: review the event context with the driver before the next shift and document the outcome.",
        ))

    # Operational controls already underway should remain visible but below new hazards.
    actions.append(action(
        "V-102", 61, "Medium", "Dispatch control",
        "Keep V-102 off the dispatch board",
        "Its telematics unit is removed and the work order says the truck is parked. This is a verification task, not a new diagnosis.",
        ["WO-5536 is open since Sep 18, 11:00 p.m.", "Technician note says the truck is not dispatched."],
        "Operations: confirm the existing dispatch hold remains in place until the telematics unit is replaced.",
        "In progress",
    ))

    # Keep one entry per vehicle in the action queue, preferring the higher score.
    best_by_vehicle: dict[str, dict[str, object]] = {}
    for item in actions:
        vehicle_id = str(item["vehicle"])
        if vehicle_id not in best_by_vehicle or item["score"] > best_by_vehicle[vehicle_id]["score"]:
            best_by_vehicle[vehicle_id] = item
    queue = sorted(best_by_vehicle.values(), key=lambda item: (-int(item["score"]), str(item["vehicle"])))[:10]

    # Driver comparison: normalize by exposure and surface the firmware effect.
    safety_types = {"speeding", "harsh_braking", "harsh_accel", "harsh_cornering"}
    driver_counts: Counter[str] = Counter()
    for row in alerts:
        if row["alert_type"] in safety_types:
            driver_counts[str(row["driver_id"])] += 1
    drivers = []
    for driver_id, count in driver_counts.items():
        vehicle = next(v for v in vehicles.values() if v["assigned_driver"] == driver_id)
        km = float(vehicle["km_driven_14d"])
        drivers.append({
            "driver": driver_id, "vehicle": vehicle["vehicle_id"], "events": count,
            "km": int(km), "rate": round(count / km * 1000, 1),
            "firmware": vehicle["device_firmware"], "depot": vehicle["depot"],
        })
    driver_top = sorted(drivers, key=lambda row: (-row["rate"], row["driver"]))[:8]

    firmware = defaultdict(lambda: {"events": 0, "km": 0, "vehicles": set()})
    for row in alerts:
        if row["alert_type"] not in safety_types:
            continue
        version = str(row["vehicle_device_firmware"])
        firmware[version]["events"] += 1
        firmware[version]["vehicles"].add(str(row["vehicle_id"]))
    for version, info in firmware.items():
        info["km"] = sum(float(vehicles[v]["km_driven_14d"]) for v in info["vehicles"])
    firmware_rates = [
        {
            "firmware": version, "events": info["events"], "vehicles": len(info["vehicles"]),
            "km": int(info["km"]), "rate": round(info["events"] / info["km"] * 1000, 1),
        }
        for version, info in sorted(firmware.items())
    ]

    return {
        "as_of": AS_OF.isoformat(),
        "actions": queue,
        "top3": queue[:3],
        "drivers": driver_top,
        "firmware": firmware_rates,
        "metrics": {
            "raw_alerts": len(raw_alerts), "unique_events": len(alerts),
            "duplicate_extras": duplicate_extras, "night_noise": len(night_noise),
            "future_maintenance": len(future_maintenance), "delayed_1h": len(delayed_1h),
            "delayed_24h": len(delayed_24h), "faults": len(fault_rows),
            "severity_mismatch": severity_mismatch,
        },
        "method": [
            "Use event time, converted from UTC to Eastern, for recency decisions.",
            "Collapse identical event signatures even when alert IDs differ.",
            "Ignore device-unplugged and camera-offline alerts from 11:00 p.m. to midnight local time.",
            "Treat negative maintenance values as not yet due.",
            "Use the DTC reference urgency instead of blindly trusting vendor severity.",
            "Compare drivers per 1,000 km and disclose firmware detection bias.",
        ],
    }


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Maple Freight | Tonight's Action Queue</title>
<style>
:root{--navy:#09213f;--blue:#1769aa;--pale:#eef5fb;--line:#d8e3ed;--red:#b42318;--amber:#b54708;--green:#027a48;--ink:#172b3f;--muted:#5d6f81}
*{box-sizing:border-box}body{margin:0;overflow-x:hidden;background:#f6f8fb;color:var(--ink);font:15px/1.45 Inter,Segoe UI,Arial,sans-serif}.shell{max-width:1180px;margin:auto;padding:28px}
header{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:24px}h1{margin:0;color:var(--navy);font-size:34px;letter-spacing:-.6px}.sub{color:var(--muted);margin-top:6px}.stamp{text-align:right;color:var(--muted);font-size:13px}
.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px}.metric,.card,.panel{background:white;border:1px solid var(--line);border-radius:12px;box-shadow:0 2px 7px #102a4310}.metric{padding:16px}.metric b{display:block;font-size:27px;color:var(--navy)}.metric span{color:var(--muted);font-size:13px}
.section-head{display:flex;justify-content:space-between;align-items:center;margin:22px 0 12px}.section-head h2{margin:0;color:var(--navy);font-size:21px}.hint{font-size:13px;color:var(--muted)}
.top3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.card{padding:18px;border-top:5px solid var(--red)}.card.high{border-top-color:var(--amber)}.eyebrow{display:flex;justify-content:space-between;gap:8px;font-size:12px;font-weight:700;text-transform:uppercase;color:var(--red)}.card.high .eyebrow{color:var(--amber)}h3{font-size:19px;line-height:1.25;margin:10px 0 8px}.meta{font-size:13px;color:var(--muted)}.why{min-height:84px}.evidence{padding-left:18px;color:#334e68;font-size:13px}.next{background:var(--pale);padding:11px;border-radius:8px;font-size:13px}.next b{color:var(--navy)}
.panel{padding:18px;margin-bottom:18px;min-width:0}.controls{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}select,input{border:1px solid #b8c6d4;border-radius:8px;padding:9px 11px;background:white;color:var(--ink)}input{min-width:250px;max-width:100%}table{width:100%;border-collapse:collapse}th{text-align:left;font-size:12px;color:var(--muted);text-transform:uppercase;border-bottom:2px solid var(--line);padding:10px 8px}td{border-bottom:1px solid var(--line);padding:12px 8px;vertical-align:top;overflow-wrap:anywhere}.pill{display:inline-block;padding:3px 8px;border-radius:999px;font-size:12px;font-weight:700}.Critical{background:#fee4e2;color:var(--red)}.High{background:#ffead5;color:var(--amber)}.Medium{background:#eaf2f8;color:#175c8d}.score{font-weight:800;color:var(--navy)}.detail{font-size:12px;color:var(--muted);margin-top:4px}.grid2{display:grid;grid-template-columns:1.15fr .85fr;gap:18px}.grid2>*{min-width:0}.callout{background:#fff8e7;border-left:4px solid #f4b400;padding:13px;margin:12px 0}.method li{margin:6px 0}.footer{color:var(--muted);font-size:12px;margin:24px 0 10px}
@media(max-width:1000px){.top3,.grid2{grid-template-columns:1fr}.why{min-height:0}}@media(max-width:700px){.shell{padding:16px}.summary{grid-template-columns:1fr 1fr}header{display:block}.stamp{text-align:left;margin-top:8px}.section-head{display:block}.section-head .hint{margin-top:5px}table{font-size:13px}}
</style></head><body><main class="shell">
<header><div><h1>Maple Freight: What Needs Me Today?</h1><div class="sub">A focused action queue for tonight and the 6:00 a.m. dispatch</div></div><div class="stamp">As of Sep 21, 2026 · 6:00 p.m. Eastern<br>Source: supplied synthetic telematics and shop data</div></header>
<section class="summary" id="metrics"></section>
<div class="section-head"><h2>Tonight's top 3</h2><div class="hint">Ranked by consequence, recency, corroboration and current resolution status</div></div>
<section class="top3" id="top3"></section>
<div class="section-head"><h2>Action queue</h2><div class="hint">Capped at 10 items to match operational capacity</div></div>
<section class="panel"><div class="controls"><select id="priority"><option value="">All priorities</option><option>Critical</option><option>High</option><option>Medium</option></select><select id="category"><option value="">All categories</option><option>Maintenance</option><option>Safety</option><option>Dispatch control</option></select><input id="search" placeholder="Search vehicle, driver or depot"></div><div style="overflow:auto"><table><thead><tr><th>Rank</th><th>Priority</th><th>Vehicle / driver</th><th>Why this is here</th><th>Next action</th><th>Status</th></tr></thead><tbody id="queue"></tbody></table></div></section>
<section class="grid2"><div class="panel"><div class="section-head" style="margin-top:0"><h2>Driver comparison</h2><div class="hint">Safety events per 1,000 km</div></div><div class="callout"><b>D-17 is not clearly the worst driver.</b> Raw counts are distorted by distance and firmware 4.2.1's higher detection rate. Use normalized results as a review signal, not a disciplinary verdict.</div><div style="overflow:auto"><table><thead><tr><th>Driver</th><th>Vehicle</th><th>Events</th><th>Km</th><th>Rate</th><th>Firmware</th></tr></thead><tbody id="drivers"></tbody></table></div></div>
<div class="panel"><div class="section-head" style="margin-top:0"><h2>Data checks</h2></div><p>The vendor export cannot be treated as a clean decision list:</p><ul class="method" id="method"></ul><h3>Firmware comparison</h3><table><thead><tr><th>Version</th><th>Vehicles</th><th>Events / 1,000 km</th></tr></thead><tbody id="firmware"></tbody></table></div></section>
<div class="footer">This tool prioritizes review and operational action. It does not infer facts not present in the supplied data.</div>
</main><script>
const data=__DATA__;
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const metrics=[['10','Action capacity'],[data.metrics.raw_alerts.toLocaleString(),'Raw alerts'],[data.metrics.duplicate_extras,'Duplicate event rows removed'],[data.metrics.severity_mismatch,'DTC/vendor severity conflicts']];
document.querySelector('#metrics').innerHTML=metrics.map(x=>`<div class="metric"><b>${x[0]}</b><span>${x[1]}</span></div>`).join('');
document.querySelector('#top3').innerHTML=data.top3.map((a,i)=>`<article class="card ${a.priority==='High'?'high':''}"><div class="eyebrow"><span>#${i+1} ${esc(a.priority)}</span><span>${esc(a.vehicle)}</span></div><h3>${esc(a.title)}</h3><div class="meta">${esc(a.driver)} · ${esc(a.depot)} · ${esc(a.category)}</div><p class="why">${esc(a.why)}</p><ul class="evidence">${a.evidence.map(e=>`<li>${esc(e)}</li>`).join('')}</ul><div class="next"><b>Next:</b> ${esc(a.next_action)}</div></article>`).join('');
function drawQueue(){const p=document.querySelector('#priority').value,c=document.querySelector('#category').value,q=document.querySelector('#search').value.toLowerCase();const rows=data.actions.filter(a=>(!p||a.priority===p)&&(!c||a.category===c)&&(!q||`${a.vehicle} ${a.driver} ${a.depot}`.toLowerCase().includes(q)));document.querySelector('#queue').innerHTML=rows.map((a,i)=>`<tr><td class="score">${i+1}</td><td><span class="pill ${a.priority}">${esc(a.priority)}</span><div class="detail">Score ${a.score}</div></td><td><b>${esc(a.vehicle)}</b><div class="detail">${esc(a.driver)} · ${esc(a.depot)}</div></td><td>${esc(a.title)}<div class="detail">${esc(a.why)}</div></td><td>${esc(a.next_action)}</td><td>${esc(a.status)}</td></tr>`).join('')||'<tr><td colspan="6">No matching actions.</td></tr>'}
['priority','category','search'].forEach(id=>document.querySelector('#'+id).addEventListener(id==='search'?'input':'change',drawQueue));drawQueue();
document.querySelector('#drivers').innerHTML=data.drivers.map(d=>`<tr><td><b>${esc(d.driver)}</b></td><td>${esc(d.vehicle)}</td><td>${d.events}</td><td>${d.km.toLocaleString()}</td><td><b>${d.rate}</b></td><td>${esc(d.firmware)}</td></tr>`).join('');
document.querySelector('#method').innerHTML=data.method.map(m=>`<li>${esc(m)}</li>`).join('')+`<li>${data.metrics.delayed_1h} events arrived more than one hour late; ${data.metrics.delayed_24h} arrived more than 24 hours late.</li><li>${data.metrics.night_noise} expected overnight device alerts and ${data.metrics.future_maintenance} not-yet-due maintenance alerts were excluded from escalation.</li>`;
document.querySelector('#firmware').innerHTML=data.firmware.map(f=>`<tr><td>${esc(f.firmware)}</td><td>${f.vehicles}</td><td><b>${f.rate}</b></td></tr>`).join('');
</script></body></html>"""


def render_dashboard() -> str:
    payload = json.dumps(build_model(), default=str).replace("</", "<\\/")
    return HTML.replace("__DATA__", payload)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path not in {"/", "/index.html"}:
            self.send_error(404)
            return
        body = render_dashboard().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Maple Freight action dashboard")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--export", action="store_true", help="Write a standalone dashboard.html")
    args = parser.parse_args()
    if args.export:
        target = ROOT / "dashboard.html"
        target.write_text(render_dashboard(), encoding="utf-8")
        print(f"Wrote {target}")
        return
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Maple Freight dashboard: http://127.0.0.1:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
