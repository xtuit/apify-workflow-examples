# Workday jobs & website technology: Apify examples

Export public company jobs or build a website technology inventory using two hosted Actors maintained by [kiroZhang](https://apify.com/kirozhang). These examples use **Python 3.9+ with no third-party dependencies**.

| Workflow | Start here | Hosted Actor |
|---|---|---|
| Workday company job feed | [Tutorial](docs/workday.md) · [10-row input](examples/inputs/workday.json) | [Workday Jobs Scraper](https://apify.com/kirozhang/workday-careers-job-exporter?utm_source=github&utm_medium=example_repository&utm_campaign=workday_tech_202611&utm_content=readme_workday) |
| Website technology inventory and comparison | [Tutorial](docs/technology.md) · [2-URL input](examples/inputs/technology.json) | [Website Tech Stack Detector](https://apify.com/kirozhang/website-tech-stack-evidence?utm_source=github&utm_medium=example_repository&utm_campaign=workday_tech_202611&utm_content=readme_technology) |

## Run a small example

Download this repository or clone it, then run from its root:

```bash
git clone https://github.com/xtuit/apify-workflow-examples.git
cd apify-workflow-examples

# Local checks only; no token, network request or charge.
python3 examples/run.py workday --validate-only
python3 examples/run.py technology --validate-only

# Each command below starts a real, potentially billable Apify run.
python3 examples/run.py workday
python3 examples/run.py technology
```

The script asks for your Apify token using hidden input. It also accepts an existing `APIFY_TOKEN` environment variable from your usual secret manager. It never writes the token to an output file or URL. You need your own Apify account and access to the chosen Actor.

Defaults: **$0.10 maximum run charge, 256 MB memory, 180-second cloud timeout, 10-row result cap**. The Workday example asks for ten NVIDIA engineering jobs; the technology example checks two URLs. Review current Actor pricing before running. As listed on 6 November 2026, result charges are $0.0015 per Workday job and $0.003 per website check. A ten-job sample is at most $0.015 in result charges; the two-URL sample is at most $0.006. Repeated runs can return and charge for the same item again. Later storage access can have separate platform usage costs.

## What the client saves

Each run gets a separate directory under `output/<workflow>/<run-id>/`:

- `run.json`: run ID, status, build and storage references.
- `results.json`: full delivered rows, preserving nested evidence.
- `results.csv`: a flat view for spreadsheets.
- `summary.json`: the Actor's `RUN_SUMMARY`, including source completeness, errors and limits.
- `next-baseline.json`: technology names for the next check, produced only after a successful, complete, error-free technology scan.

`SUCCEEDED` does **not** always mean complete source coverage. A capped Workday sample is intentionally partial. Inspect `summary.json` before treating a result as a complete inventory. Unknown source fields remain unknown. CSV text that starts like a spreadsheet formula is prefixed with an apostrophe; JSON preserves the source value.

If the client disconnects after printing a run ID, continue reading that run:

```bash
python3 examples/run.py workday --resume YOUR_RUN_ID
```

Resume does not start another Actor run. If the start response was never confirmed and no run ID was printed, check Apify Console before retrying. The client never automatically retries a start request. Stopping the local script does not cancel an already-started cloud run.

## Choose a workflow

**Workday:** public career-site URLs, requisition IDs, locations and job descriptions. The tutorial includes a local upsert utility and explains why a job missing from a capped scan is not proof of closure. [Read the Workday guide](docs/workday.md).

**Technology:** public server HTML and selected headers, with evidence for supported CMS, ecommerce, analytics and framework matches. Reuse the real previous output to compare technology names. [Read the technology guide](docs/technology.md).

Browse the [complete public product catalogue](https://kiro-data-tools.kiro9.chatgpt.site/?utm_source=github&utm_medium=example_repository&utm_campaign=workday_tech_202611&utm_content=readme_catalogue) for other workflows. The Actors have different source coverage; choose the one that matches your task.

## Test the examples without spending credits

```bash
python3 -m unittest discover -s tests -v
```

Tests use mocked API responses and make no network calls. Sanitized output excerpts in [samples/](samples/README.md) come from dated maintainer verification runs; they are not a live feed or customer testimonials.

## Support and scope

For a problem in these client examples, open a repository Issue with the command, Python version and sanitized error. For Actor results or billing, use the relevant Actor's **Issues** tab on Apify. Do not post tokens, private input, or customer data. A run ID can grant access to some run information; share it through the appropriate support channel with that in mind.

This repository contains public client examples and documentation. Scraping, detection signatures and hosted Actor implementation remain outside this repository. The examples send requests to the official Apify API; they have no maintainer telemetry or automatic external destination.

The maintainer operates the paid Actors linked here. This project is independent of Workday and the websites inspected. MIT covers this repository's original client code and documentation, not the hosted service or third-party source data. Documentation was AI-assisted and checked against the implementation and verification evidence.

References: [start an Actor](https://docs.apify.com/api/v2/actors-runs-post), [read a run](https://docs.apify.com/api/v2/actor-run-get), [read a dataset](https://docs.apify.com/api/v2/dataset-items-get).
