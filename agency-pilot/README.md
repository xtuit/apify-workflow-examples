# Inquiry CSV → clean CRM import and audit report

**SYNTHETIC DATA DEMO. These are fictional inquiries, not real customers, transactions, or revenue.**

This working example processes an inquiry export into a customer import, an exception queue, and a readable per-run report. It does not aggregate a day's runs. It demonstrates a small, testable delivery: no external APIs, network calls, API keys, paid packages, or AI service calls. Python 3.9 or later and its standard library are sufficient.

Open the included [first-run report](examples/first/report.html), [replay report](examples/replay/report.html), [follow-up report](examples/followup/report.html), and [reformatted old-version report](examples/stale_replay/report.html) in a browser after downloading the repository. GitHub normally shows HTML source; it does not serve these files as a website. The [first-run summary](examples/first/summary.json), [follow-up change evidence](examples/followup/change_evidence.json), and [old-version suppression evidence](examples/stale_replay/change_evidence.json) can be inspected directly on GitHub.

## What the sample proves

| Run | Input rows | Quarantined | Duplicate rows within file | New | Updates | Unchanged | Exact replay suppressed | Known old versions suppressed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Initial inquiries | 8 | 4 | 1 | 3 | 0 | 0 | 0 | 0 |
| Exact same file again | 8 | 4 | 1 | 0 | 0 | 0 | 3 | 0 |
| Follow-up inquiries | 3 | 0 | 0 | 1 | 1 | 1 | 0 | 0 |
| Alice's prior version, reformatted | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |

The first file includes an invalid email, a missing name, a short row, an extra-column row, a repeated email with changed text, and a multiline message. The follow-up contains one new email, one changed message, and one unchanged customer. Only new and changed records appear in the CRM import. The report shows the old and new message for the changed customer.

Replaying previously processed bytes creates a fresh audit report and empty CRM change files. Renaming an identical file does not bypass this check. Separately, SQLite retains each email's accepted normalized payload fingerprints. If an input matches a previously accepted version that differs from the current version, it is counted under `suppressed_stale_versions`, reported with fingerprint evidence, and excluded from customer changes. Blank lines, changed column order, email case, or other normalization-equivalent formatting cannot make that known old version overwrite the current version.

This history cannot establish the age of an **unseen** payload. Without a source version or trusted source timestamp, an unseen payload is still treated as an update under the agreed reference policy, even if it came from an older export. A requested return to a previously accepted payload is also suppressed by this demo; deliberate restores need a separately agreed version rule. Keep the database to retain the history. Earlier overwritten versions from a database created before history tracking cannot be recovered by this implementation.

## Run locally

From this directory:

```sh
python3 lead_pipeline.py data/inquiries.csv --database work/customers.sqlite3 --output work/first
python3 lead_pipeline.py data/inquiries.csv --database work/customers.sqlite3 --output work/replay
python3 lead_pipeline.py data/followup.csv --database work/customers.sqlite3 --output work/followup
python3 lead_pipeline.py data/reformatted_old.csv --database work/customers.sqlite3 --output work/stale_replay
```

Open the `report.html` file in each of those four output directories locally. No server is needed. Output directories must be new; choose another directory name to run again. Keep the same database to retain deduplication history. Use a different database for an independent demo.

## Inputs and outputs

The UTF-8 CSV must contain each header exactly once: `email,name,company,source,message`. Header order may vary. All five values are required. A UTF-8 byte-order mark and quoted multiline values are supported. Empty physical records are ignored. Inputs are limited to 10 MiB (10,485,760 bytes) and 10,000 nonempty CSV data records, including invalid records. Files above either limit are rejected before database or output changes.

Email addresses are trimmed and lowercased as an explicit demo matching policy. The format validator accepts common ASCII email syntax; it does not check delivery, domains, or mailbox ownership. Internationalized addresses and uncommon valid RFC forms are outside this demo's accepted format. Email case handling must be agreed with a real client. Names, company names, and sources have surrounding and repeated whitespace normalized. Messages retain their interior text and normalized line endings.

Malformed field counts, missing required values, and invalid email syntax go to quarantine. Unrecoverable CSV syntax, NUL characters, invalid encoding, or an incorrect header rejects the whole input before customer state changes. Within a file, the last **valid** record for an email is selected, then checked against current state and accepted-version history. An unseen version updates the contact. A real deployment should agree on the business rule before treating later exports as authoritative updates.

Each successful run creates:

- `crm_import.csv`: new and updated records together, with an `action` column.
- `crm_new.csv` and `crm_updates.csv`: separate files containing the five input fields.
- `quarantine.csv`: physical source line, reason, and original row values.
- `summary.json`: counts, input hash, batch ID, and synthetic-data disclosure.
- `change_evidence.json`: individual change events, field-level before/after values, and suppressed known old-version fingerprints.
- `report.html`: standalone readable report containing the same evidence.

CSV cells that resemble spreadsheet formulas receive a leading apostrophe; the database retains the original value. A production CRM import must confirm its field mapping and how it handles these escaped values. HTML output escapes input text. Records and quarantined values remain on disk; no data is sent anywhere by this program.

## Run the checks

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s . -p 'test_*.py' -v
```

The tests cover new/change/unchanged separation, normalization and deduplication, bad rows, exact and renamed replay, old→new→reformatted old with blank lines or reordered columns, the explicitly accepted unseen-payload limitation, semantic repeats, reordered headers, BOM and multiline input, malformed-file and input-limit rejection, output overwrite refusal, HTML/CSV escaping, and database plus payload-history rollback after a simulated output failure. Temporary test files are created inside this demo directory and removed afterward.

## Delivery boundary

This is a local file-processing demo, not a live CRM integration or proof that a separate sales offer has been delivered. The reference policy selects the last valid row within a file, suppresses previously accepted old versions, and accepts unseen versions; it does **not** quarantine all conflicting versions of the same contact or determine source chronology. Any client policy requiring conflict quarantine needs a separately agreed implementation and acceptance test. It sends no email, changes no external CRM, and measures no revenue, conversion rate, or time savings. The included outputs come from executing the bundled synthetic inputs. SQLite and export writes are coordinated for ordinary errors, but abrupt process or machine failure can leave partial artifacts; this is not a claim of end-to-end exactly-once delivery. A client integration would additionally require agreed fields and update rules, permission to handle its data, an import destination, retention rules, and acceptance tests using its own approved sample.

For review, this folder is self-contained. It does not depend on any Apify actor, private account, or deployment in the surrounding repository.
