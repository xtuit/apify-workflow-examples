#!/usr/bin/env python3
"""Synthetic inquiry-to-CRM demonstration. Python standard library only."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
from pathlib import Path
import re
import shutil
import sqlite3
from datetime import datetime, timezone


FIELDS = ("email", "name", "company", "source", "message")
POLICY_VERSION = "demo-v1"
MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_INPUT_RECORDS = 10_000
DISCLAIMER = "SYNTHETIC DATA DEMO — not real customers, transactions, or revenue."


def valid_email(value: str) -> bool:
    """Practical ASCII address syntax check; no DNS or mailbox-delivery claims."""
    if len(value) > 254 or value.count("@") != 1:
        return False
    local, domain = value.split("@")
    if not local or len(local) > 64 or local.startswith(".") or local.endswith("."):
        return False
    if ".." in local or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+", local):
        return False
    labels = domain.split(".")
    if len(labels) < 2 or not re.fullmatch(r"[a-z]{2,63}", labels[-1]):
        return False
    return all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in labels)


def parse_input(path: Path) -> dict:
    with path.open("rb") as handle:
        raw = handle.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("Input exceeds the 10 MiB demo limit; entire file rejected.")
    try:
        source_text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Input must be UTF-8 CSV; no customer state was changed.") from error
    if "\x00" in source_text:
        raise ValueError("Input contains a NUL character; entire file rejected.")
    reader = csv.reader(io.StringIO(source_text, newline=""), strict=True)
    try:
        header = next(reader, None)
        if header is None or len(header) != len(FIELDS) or set(header) != set(FIELDS):
            raise ValueError("CSV must contain each header exactly once: " + ",".join(FIELDS))
        candidates = {}
        quarantined = []
        duplicates = []
        total = 0
        valid_rows = 0
        previous_line = reader.line_num
        for values in reader:
            first_line = previous_line + 1
            previous_line = reader.line_num
            if not values:
                continue
            total += 1
            if total > MAX_INPUT_RECORDS:
                raise ValueError("Input exceeds the 10,000-record demo limit; entire file rejected.")
            reason = []
            if len(values) != len(header):
                reason.append(f"expected {len(header)} columns; received {len(values)}")
                record = {key: values[index] if index < len(values) else "" for index, key in enumerate(header)}
            else:
                record = dict(zip(header, values))
            normalized = {key: record[key].strip() for key in FIELDS}
            normalized["email"] = normalized["email"].lower()
            for key in ("name", "company", "source"):
                normalized[key] = " ".join(normalized[key].split())
            normalized["message"] = normalized["message"].replace("\r\n", "\n").replace("\r", "\n")
            missing = [key for key in FIELDS if not normalized[key]]
            if missing:
                reason.append("missing required: " + ", ".join(missing))
            if normalized["email"] and not valid_email(normalized["email"]):
                reason.append("invalid email syntax")
            if reason:
                quarantined.append({"line_number": first_line, "reason": "; ".join(reason),
                                    "raw_values_json": json.dumps(values, ensure_ascii=False)})
                continue
            valid_rows += 1
            email = normalized["email"]
            if email in candidates:
                duplicates.append({"email": email, "replaced_line": candidates[email]["line_number"],
                                   "kept_line": first_line})
            candidates[email] = {"line_number": first_line, **normalized}
    except csv.Error as error:
        raise ValueError(f"Malformed CSV near physical line {reader.line_num}; entire file rejected.") from error
    digest = hashlib.sha256(raw).hexdigest()
    batch_id = hashlib.sha256((POLICY_VERSION + ":" + digest).encode()).hexdigest()
    return {"candidates": candidates, "quarantined": quarantined, "duplicates": duplicates,
            "input_rows": total, "valid_rows": valid_rows, "sha256": digest, "batch_id": batch_id}


def fingerprint(record: dict) -> str:
    payload = json.dumps({key: record[key] for key in FIELDS}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def spreadsheet_safe(value) -> str:
    """Neutralize spreadsheet formulas without changing the database value."""
    text = str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r")):
        return "'" + text
    return text


def write_csv(path: Path, headers: tuple, records: list) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow({key: spreadsheet_safe(record.get(key, "")) for key in headers})


def table(headers: tuple, records: list) -> str:
    if not records:
        return '<p class="empty">None in this run.</p>'
    head = "".join("<th>" + html.escape(label) + "</th>" for label in headers)
    rows = []
    for record in records:
        cells = "".join("<td>" + html.escape(str(record.get(label, ""))) + "</td>" for label in headers)
        rows.append("<tr>" + cells + "</tr>")
    return '<div class="table-wrap"><table><thead><tr>' + head + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"


def write_report(path: Path, summary: dict, events: list, parsed: dict, stale_versions: list) -> None:
    new = [event for event in events if event["action"] == "new"]
    updates = [event for event in events if event["action"] == "update"]
    metrics = [("Input rows", summary["input_rows"]), ("Valid rows", summary["valid_rows"]),
               ("Quarantined", summary["quarantined_rows"]), ("Within-file duplicates", summary["duplicate_rows"]),
               ("New synthetic contacts", summary["new_customers"]), ("Synthetic contact updates", summary["updated_customers"]),
               ("Unchanged synthetic contacts", summary["unchanged_customers"]), ("Suppressed replay candidates", summary["replay_candidates"]),
               ("Suppressed known old versions", summary["suppressed_stale_versions"])]
    metric_html = "".join(f'<div><span>{label}</span><strong>{value}</strong></div>' for label, value in metrics)
    changes = []
    for event in updates:
        for field, change in event["changes"].items():
            changes.append({"email": event["email"], "field": field, "before": change["before"], "after": change["after"]})
    report = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Synthetic inquiry processing report</title>
<style>
body{font-family:system-ui,sans-serif;margin:0;color:#15212e;background:#f3f6f8;line-height:1.55}
main{max-width:1080px;margin:auto;padding:28px 20px 48px}h1{line-height:1.2;font-size:28px}h2{margin-top:32px;font-size:21px}
.notice{background:#fff3d3;color:#654900;padding:14px;border-left:4px solid #ba8200;font-weight:600}
.meta{color:#435466;overflow-wrap:anywhere}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:24px 0}
.metrics div{background:white;padding:16px;border-radius:8px}.metrics span{display:block;color:#435466;font-size:14px}.metrics strong{font-size:27px}
.table-wrap{overflow-x:auto;background:white}table{width:100%;border-collapse:collapse;text-align:left}th,td{padding:10px 12px;border-bottom:1px solid #d9e1e8;vertical-align:top}
td{white-space:pre-wrap;overflow-wrap:anywhere;min-width:90px;max-width:360px}th{background:#e9f0f5}.empty{color:#546575}code{overflow-wrap:anywhere}
@media(prefers-color-scheme:dark){body{background:#111922;color:#e5edf4}.metrics div,.table-wrap{background:#1b2835}th{background:#263746}.metrics span,.meta,.empty{color:#bbc9d6}th,td{border-color:#3c4b5a}.notice{background:#3d3219;color:#ffe1a0}}
</style></head><body><main>
"""
    report += '<div class="notice">' + DISCLAIMER + "</div><h1>Inquiry processing report</h1>"
    report += '<p class="meta">Input: ' + html.escape(summary["input_name"]) + " · Generated: " + summary["generated_at_utc"] + "</p>"
    report += '<p class="meta">Exact-file replay: <strong>' + str(summary["replayed"]).lower() + "</strong> · Stored synthetic contacts after run: " + str(summary["stored_customers"]) + "</p>"
    report += '<div class="metrics">' + metric_html + "</div>"
    report += "<p>This is a per-run report, without daily aggregation. Email is the synthetic contact key. The last valid row is selected within one file. Previously accepted old normalized versions are suppressed even when the CSV formatting changes. Unseen versions still update the current contact; without a source version or timestamp, this demo cannot establish whether an unseen version is newer. These reference rules need agreement before a real integration. No message is sent and no external CRM is changed.</p>"
    report += "<h2>New synthetic contacts</h2>" + table(FIELDS, new)
    report += "<h2>Existing synthetic contact updates</h2>" + table(FIELDS, updates)
    report += "<h2>Field-level change evidence</h2>" + table(("email", "field", "before", "after"), changes)
    report += "<h2>Within-file duplicate evidence</h2>" + table(("email", "replaced_line", "kept_line"), parsed["duplicates"])
    report += "<h2>Suppressed known old versions</h2>" + table(("email", "line_number", "suppressed_fingerprint", "current_fingerprint", "first_batch_id"), stale_versions)
    report += "<h2>Quarantined rows</h2>" + table(("line_number", "reason", "raw_values_json"), parsed["quarantined"])
    report += '<h2>Run receipt</h2><p class="meta">Batch ID: <code>' + summary["batch_id"] + "</code><br>Input SHA-256: <code>" + summary["input_sha256"] + "</code></p>"
    report += "<p>Counts describe this synthetic file only. Email checks cover syntax, not deliverability. No conversion rate, revenue, or customer savings is measured.</p></main></body></html>"
    path.write_text(report, encoding="utf-8")


def run_pipeline(input_path: Path, database_path: Path, output_dir: Path) -> dict:
    parsed = parse_input(input_path)
    # Refuse to overwrite any existing output directory; failed runs own their directory.
    output_dir.mkdir(parents=True, exist_ok=False)
    connection = None
    try:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS customers (
                email TEXT PRIMARY KEY, name TEXT NOT NULL, company TEXT NOT NULL,
                source TEXT NOT NULL, message TEXT NOT NULL, fingerprint TEXT NOT NULL,
                first_seen_utc TEXT NOT NULL, last_changed_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS processed_batches (
                batch_id TEXT PRIMARY KEY, input_sha256 TEXT NOT NULL,
                processed_at_utc TEXT NOT NULL, summary_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS processed_payloads (
                email TEXT NOT NULL, fingerprint TEXT NOT NULL,
                first_processed_at_utc TEXT NOT NULL, first_batch_id TEXT NOT NULL,
                PRIMARY KEY (email, fingerprint)
            );
        """)
        connection.execute("BEGIN IMMEDIATE")
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        # Preserve the current version if this database predates payload history.
        # Overwritten versions absent from such a database cannot be reconstructed.
        connection.execute("""INSERT OR IGNORE INTO processed_payloads
            SELECT email, fingerprint, last_changed_utc, 'existing-current-version' FROM customers""")
        replayed = connection.execute("SELECT 1 FROM processed_batches WHERE batch_id=?", (parsed["batch_id"],)).fetchone() is not None
        events = []
        stale_versions = []
        unchanged = 0
        if not replayed:
            for email in sorted(parsed["candidates"]):
                record = parsed["candidates"][email]
                digest = fingerprint(record)
                previous = connection.execute("SELECT * FROM customers WHERE email=?", (email,)).fetchone()
                if previous is not None and previous["fingerprint"] == digest:
                    unchanged += 1
                    continue
                historical = connection.execute(
                    "SELECT first_batch_id FROM processed_payloads WHERE email=? AND fingerprint=?",
                    (email, digest)).fetchone()
                if previous is not None and historical is not None:
                    stale_versions.append({"email": email, "line_number": record["line_number"],
                                           "suppressed_fingerprint": digest,
                                           "current_fingerprint": previous["fingerprint"],
                                           "first_batch_id": historical["first_batch_id"]})
                    continue
                action = "new" if previous is None else "update"
                changes = {key: {"before": previous[key] if previous else "", "after": record[key]}
                           for key in FIELDS if previous is None or previous[key] != record[key]}
                event_id = hashlib.sha256((parsed["batch_id"] + ":" + email).encode()).hexdigest()
                events.append({"event_id": event_id, "action": action, "line_number": record["line_number"],
                               **{key: record[key] for key in FIELDS}, "changes": changes})
                connection.execute("""INSERT INTO customers VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(email) DO UPDATE SET name=excluded.name, company=excluded.company,
                    source=excluded.source, message=excluded.message, fingerprint=excluded.fingerprint,
                    last_changed_utc=excluded.last_changed_utc""",
                    tuple(record[key] for key in FIELDS) + (digest, timestamp, timestamp))
                connection.execute("INSERT OR IGNORE INTO processed_payloads VALUES(?,?,?,?)",
                                   (email, digest, timestamp, parsed["batch_id"]))
        summary = {
            "synthetic_demo": True, "disclaimer": DISCLAIMER, "policy_version": POLICY_VERSION,
            "input_name": input_path.name, "input_sha256": parsed["sha256"], "batch_id": parsed["batch_id"],
            "generated_at_utc": timestamp, "input_rows": parsed["input_rows"], "valid_rows": parsed["valid_rows"],
            "quarantined_rows": len(parsed["quarantined"]), "duplicate_rows": len(parsed["duplicates"]),
            "unique_valid_emails": len(parsed["candidates"]), "new_customers": sum(e["action"] == "new" for e in events),
            "updated_customers": sum(e["action"] == "update" for e in events), "unchanged_customers": unchanged,
            "replay_candidates": len(parsed["candidates"]) if replayed else 0, "replayed": replayed,
            "suppressed_stale_versions": len(stale_versions),
            "stored_customers": connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
            "csv_formula_protection": "Leading apostrophe on spreadsheet-formula-like cell values; database values unchanged",
            "network_requests": 0, "messages_sent": 0, "external_crm_writes": 0
        }
        if not replayed:
            connection.execute("INSERT INTO processed_batches VALUES(?,?,?,?)",
                               (parsed["batch_id"], parsed["sha256"], timestamp, json.dumps(summary)))
        write_csv(output_dir / "crm_import.csv", ("action",) + FIELDS, events)
        write_csv(output_dir / "crm_new.csv", FIELDS, [e for e in events if e["action"] == "new"])
        write_csv(output_dir / "crm_updates.csv", FIELDS, [e for e in events if e["action"] == "update"])
        write_csv(output_dir / "quarantine.csv", ("line_number", "reason", "raw_values_json"), parsed["quarantined"])
        (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output_dir / "change_evidence.json").write_text(json.dumps({"synthetic_demo": True, "events": events,
            "within_file_duplicates": parsed["duplicates"], "suppressed_stale_versions": stale_versions}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_report(output_dir / "report.html", summary, events, parsed, stale_versions)
        connection.commit()
        return summary
    except Exception:
        if connection is not None:
            connection.rollback()
        shutil.rmtree(output_dir)
        raise
    finally:
        if connection is not None:
            connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=DISCLAIMER)
    parser.add_argument("input", type=Path, help="UTF-8 inquiry CSV")
    parser.add_argument("--database", type=Path, required=True, help="SQLite state retained between runs")
    parser.add_argument("--output", type=Path, required=True, help="New output directory (must not exist)")
    args = parser.parse_args()
    try:
        summary = run_pipeline(args.input, args.database, args.output)
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(2, f"Error: {error}\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
