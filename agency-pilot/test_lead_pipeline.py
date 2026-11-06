"""Behavioral checks using only synthetic records and temporary local files."""

import csv
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import lead_pipeline as pipeline


ROOT = Path(__file__).resolve().parent


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".test-", dir=ROOT)
        self.root = Path(self.temporary.name)
        self.database = self.root / "state.sqlite3"

    def tearDown(self):
        self.temporary.cleanup()

    def run_sample(self, name="inquiries.csv", output="result"):
        return pipeline.run_pipeline(ROOT / "data" / name, self.database, self.root / output)

    def rows(self, output, filename):
        with (self.root / output / filename).open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def state(self):
        with sqlite3.connect(self.database) as connection:
            return (connection.execute("SELECT * FROM customers ORDER BY email").fetchall(),
                    connection.execute("SELECT * FROM processed_batches ORDER BY batch_id").fetchall(),
                    connection.execute("SELECT * FROM processed_payloads ORDER BY email, fingerprint").fetchall())

    def custom(self, text, name="input.csv"):
        path = self.root / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        return path

    def test_first_run_normalizes_deduplicates_and_quarantines(self):
        summary = self.run_sample()
        self.assertEqual((summary["input_rows"], summary["valid_rows"], summary["quarantined_rows"],
                          summary["duplicate_rows"], summary["new_customers"], summary["stored_customers"]),
                         (8, 4, 4, 1, 3, 3))
        records = self.rows("result", "crm_new.csv")
        self.assertEqual([r["email"] for r in records], ["alice@example.com", "bob@example.com", "carol@example.com"])
        self.assertIn("revised", records[0]["message"])
        self.assertIn("\n", records[2]["message"])
        quarantined = self.rows("result", "quarantine.csv")
        self.assertEqual([r["line_number"] for r in quarantined], ["5", "6", "7", "8"])
        self.assertIn("invalid email", quarantined[0]["reason"])
        self.assertIn("missing required: name", quarantined[1]["reason"])
        self.assertIn("received 4", quarantined[2]["reason"])
        self.assertIn("received 6", quarantined[3]["reason"])
        self.assertEqual(self.rows("result", "crm_updates.csv"), [])

    def test_exact_replay_and_renamed_replay_do_not_mutate_state(self):
        self.run_sample()
        before = self.state()
        summary = self.run_sample(output="replay")
        renamed = self.root / "renamed.csv"
        renamed.write_bytes((ROOT / "data" / "inquiries.csv").read_bytes())
        second = pipeline.run_pipeline(renamed, self.database, self.root / "renamed")
        for actual in (summary, second):
            self.assertTrue(actual["replayed"])
            self.assertEqual(actual["replay_candidates"], 3)
            self.assertEqual(actual["new_customers"] + actual["updated_customers"], 0)
        self.assertEqual(before, self.state())
        self.assertEqual(self.rows("replay", "crm_import.csv"), [])

    def test_followup_separates_new_updated_unchanged_with_evidence(self):
        self.run_sample()
        summary = self.run_sample("followup.csv", "followup")
        self.assertEqual((summary["new_customers"], summary["updated_customers"], summary["unchanged_customers"],
                          summary["stored_customers"]), (1, 1, 1, 4))
        self.assertEqual(self.rows("followup", "crm_new.csv")[0]["email"], "dana@example.com")
        self.assertEqual(self.rows("followup", "crm_updates.csv")[0]["email"], "alice@example.com")
        evidence = json.loads((self.root / "followup" / "change_evidence.json").read_text())
        update = next(e for e in evidence["events"] if e["action"] == "update")
        self.assertEqual(set(update["changes"]), {"message"})
        self.assertIn("revised", update["changes"]["message"]["before"])
        self.assertIn("lead time", update["changes"]["message"]["after"])
        before = self.state()
        self.run_sample("followup.csv", "followup-replay")
        self.assertEqual(before, self.state())

    def test_replaying_older_batch_does_not_revert_newer_updates(self):
        self.run_sample()
        self.run_sample("followup.csv", "followup")
        before = self.state()
        self.run_sample(output="old-replay")
        self.assertEqual(before, self.state())

    def test_reformatted_known_old_payload_does_not_revert_current_version(self):
        old = self.custom("email,name,company,source,message\none@example.com,One,Example,Web,old value\n", "old.csv")
        newer = self.custom("email,name,company,source,message\none@example.com,One,Example,Web,new value\n", "new.csv")
        pipeline.run_pipeline(old, self.database, self.root / "old")
        pipeline.run_pipeline(newer, self.database, self.root / "new")
        before = self.state()
        variations = [old.read_text() + "\n", "message,source,company,name,email\nold value,Web,Example,One,ONE@EXAMPLE.COM\n"]
        for index, text in enumerate(variations):
            with self.subTest(index=index):
                path = self.custom(text, f"old-reformatted-{index}.csv")
                summary = pipeline.run_pipeline(path, self.database, self.root / f"suppressed-{index}")
                self.assertFalse(summary["replayed"])
                self.assertEqual(summary["suppressed_stale_versions"], 1)
                self.assertEqual((summary["new_customers"], summary["updated_customers"], summary["unchanged_customers"]), (0, 0, 0))
                self.assertEqual(self.rows(f"suppressed-{index}", "crm_import.csv"), [])
                self.assertEqual(before[0], self.state()[0])
                self.assertEqual(before[2], self.state()[2])
                evidence = json.loads((self.root / f"suppressed-{index}" / "change_evidence.json").read_text())
                self.assertEqual(evidence["events"], [])
                self.assertEqual(evidence["suppressed_stale_versions"][0]["email"], "one@example.com")

    def test_unseen_payload_updates_without_claiming_source_recency(self):
        first = self.custom("email,name,company,source,message\none@example.com,One,Example,Web,new value\n", "new.csv")
        unseen = self.custom("email,name,company,source,message\none@example.com,One,Example,Web,unknown older export\n", "unseen.csv")
        pipeline.run_pipeline(first, self.database, self.root / "first")
        summary = pipeline.run_pipeline(unseen, self.database, self.root / "unseen")
        self.assertEqual(summary["updated_customers"], 1)
        self.assertEqual(summary["suppressed_stale_versions"], 0)
        self.assertEqual(self.state()[0][0][4], "unknown older export")

    def test_changed_bytes_with_identical_normalized_data_are_unchanged(self):
        self.run_sample()
        records = self.rows("result", "crm_new.csv")
        path = self.root / "reordered.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=pipeline.FIELDS)
            writer.writeheader()
            writer.writerows(reversed(records))
        summary = pipeline.run_pipeline(path, self.database, self.root / "semantic-repeat")
        self.assertFalse(summary["replayed"])
        self.assertEqual((summary["new_customers"], summary["updated_customers"], summary["unchanged_customers"]), (0, 0, 3))
        self.assertEqual(len(self.state()[1]), 2)

    def test_invalid_headers_and_malformed_csv_fail_before_state_changes(self):
        texts = ["email,name\na@example.com,A\n", "email,name,company,source,email\n",
                 'email,name,company,source,message\na@example.com,A,Demo,Web,"unterminated\n', ""]
        for index, text in enumerate(texts):
            with self.subTest(index=index):
                path = self.custom(text, f"invalid-{index}.csv")
                output = self.root / f"invalid-{index}"
                with self.assertRaises(ValueError):
                    pipeline.run_pipeline(path, self.database, output)
                self.assertFalse(output.exists())
                self.assertFalse(self.database.exists())

    def test_utf8_bom_reordered_header_and_multiline_text(self):
        path = self.custom('\ufeffmessage,source,company,name,email\n"Line one\nLine two",Web,Synthetic,Example,EXAMPLE@EXAMPLE.COM\n')
        summary = pipeline.run_pipeline(path, self.database, self.root / "result")
        self.assertEqual(summary["new_customers"], 1)
        self.assertEqual(self.rows("result", "crm_new.csv")[0]["message"], "Line one\nLine two")

    def test_html_escaping_and_csv_formula_protection_preserve_database_values(self):
        path = self.custom('email,name,company,source,message\na@example.com,=1+1,Demo,Web,<script>alert(1)</script>\n')
        pipeline.run_pipeline(path, self.database, self.root / "result")
        self.assertEqual(self.rows("result", "crm_new.csv")[0]["name"], "'=1+1")
        report = (self.root / "result" / "report.html").read_text()
        self.assertNotIn("<script>", report)
        self.assertIn("&lt;script&gt;", report)
        self.assertIn("SYNTHETIC DATA DEMO", report)
        self.assertEqual(self.state()[0][0][1], "=1+1")

    def test_existing_output_is_never_overwritten(self):
        self.run_sample()
        before = self.state()
        report = (self.root / "result" / "report.html").read_bytes()
        with self.assertRaises(FileExistsError):
            self.run_sample("followup.csv")
        self.assertEqual(before, self.state())
        self.assertEqual(report, (self.root / "result" / "report.html").read_bytes())

    def test_output_failure_rolls_back_and_retry_succeeds(self):
        self.run_sample()
        before = self.state()
        with patch.object(pipeline, "write_report", side_effect=OSError("simulated disk failure")):
            with self.assertRaises(OSError):
                self.run_sample("followup.csv", "failed")
        self.assertFalse((self.root / "failed").exists())
        self.assertEqual(before, self.state())
        summary = self.run_sample("followup.csv", "retry")
        self.assertEqual((summary["new_customers"], summary["updated_customers"]), (1, 1))

    def test_header_only_input_has_zero_events_and_can_replay(self):
        path = self.custom(",".join(pipeline.FIELDS) + "\n")
        first = pipeline.run_pipeline(path, self.database, self.root / "first")
        replay = pipeline.run_pipeline(path, self.database, self.root / "replay")
        self.assertEqual(first["input_rows"], 0)
        self.assertEqual(first["stored_customers"], 0)
        self.assertTrue(replay["replayed"])

    def test_invalid_email_forms_are_quarantined(self):
        path = self.custom("email,name,company,source,message\n"
                           "a..b@example.com,A,Demo,Web,Invalid dots\n"
                           "a@localhost,A,Demo,Web,No TLD\n")
        summary = pipeline.run_pipeline(path, self.database, self.root / "result")
        self.assertEqual((summary["quarantined_rows"], summary["new_customers"]), (2, 0))

    def test_nul_and_invalid_utf8_reject_entire_input(self):
        for index, raw in enumerate((b"email,name,company,source,message\na@example.com,A,Demo,Web,NUL\x00test\n", b"\xff")):
            with self.subTest(index=index):
                path = self.root / f"invalid-bytes-{index}.csv"
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    pipeline.run_pipeline(path, self.database, self.root / f"output-{index}")
                self.assertFalse(self.database.exists())

    def test_size_and_record_limits_fail_without_existing_state_changes(self):
        self.run_sample()
        before = self.state()
        oversized = self.root / "too-large.csv"
        oversized.write_bytes(b"x" * (pipeline.MAX_INPUT_BYTES + 1))
        too_many = self.root / "too-many.csv"
        too_many.write_text(",".join(pipeline.FIELDS) + "\n" +
                            "a@example.com,A,Synthetic,Web,Demo\n" * (pipeline.MAX_INPUT_RECORDS + 1), encoding="utf-8")
        for index, path in enumerate((oversized, too_many)):
            with self.subTest(index=index):
                output = self.root / f"rejected-{index}"
                with self.assertRaisesRegex(ValueError, "exceeds"):
                    pipeline.run_pipeline(path, self.database, output)
                self.assertFalse(output.exists())
                self.assertEqual(before, self.state())


if __name__ == "__main__":
    unittest.main()
