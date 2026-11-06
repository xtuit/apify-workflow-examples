# Build and compare a website technology inventory

Use this workflow for websites already in your client or prospect list. It returns supported technology matches with the public artifacts that produced them.

[Open the Website Tech Stack Detector and current pricing](https://apify.com/kirozhang/website-tech-stack-evidence?utm_source=github&utm_medium=example_repository&utm_campaign=workday_tech_202611&utm_content=technology_guide).

## 1. Start with two known sites

The [default input](../examples/inputs/technology.json) is:

```json
{
  "urls": ["https://www.wordpress.org/", "https://www.shopify.com/"],
  "maxResults": 10
}
```

From the repository root:

```bash
python3 examples/run.py technology --validate-only
python3 examples/run.py technology
```

The second command starts a real run with your token and a $0.10 charge ceiling. At the listed 6 November 2026 rate of $0.003 per delivered check, these two URLs cost at most $0.006 in Actor result charges. Review the current Pricing tab before use. Repeated checks are new, potentially billable checks.

## 2. Inspect evidence, not just technology names

The output directory includes full `results.json`, flat `results.csv` and `summary.json`.

| Fields | Meaning |
|---|---|
| `key`, `url`, `finalUrl` | Requested page identity and redirect destination |
| `technologyNames` | Supported names matched on that fetched page |
| `technologies[].evidence` | Observed technical artifacts behind a match |
| `checkedAt` | Collection time |
| `comparison`, `changedFields` | Comparison with the explicitly supplied baseline |

Keep JSON when you need nested evidence. The CSV is a convenient flat inventory, not a full replacement for JSON.

The hosted Actor checks 60 focused signatures in returned server HTML and selected headers. It does not execute JavaScript, discover companies or collect contacts. Client-only, consent-gated and unsupported technologies may be absent from the output. No match is **not** proof that a technology is absent from the website. A match also does not prove an active subscription or buying intent.

## 3. Use a real earlier result as the baseline

After a successful, complete, error-free technology run, the client writes `next-baseline.json`. It contains the actual `key` and `technologyNames` values from that run.

For the next check:

```bash
python3 examples/run.py technology \
  --baseline output/technology/EARLIER_RUN_ID/next-baseline.json
```

For your own URLs, pass the same target input as before:

```bash
python3 examples/run.py technology \
  --input path/to/client-sites.json \
  --baseline output/technology/EARLIER_RUN_ID/next-baseline.json
```

The client sends that baseline as the Actor's `previousResults` input. The Actor fetches the websites again and compares technology names for each matching `key`:

- `no_baseline`: no matching earlier key was supplied.
- `unchanged`: the detected technology-name set matches the supplied baseline.
- `changed`: the detected technology-name set differs.

A baseline with an empty technology list is still a valid earlier observation. It must come from a real check, not an assumption. A partial or failed run does not automatically produce a replacement baseline in this client.

## 4. Keep the baseline explicit when scheduling

A saved task with static `previousResults` always compares against the same reference. To make a moving comparison, your scheduler must pass the latest accepted run's baseline into the next run. Do not advance the baseline after a failed or incomplete check; keep the earlier accepted baseline and investigate.

This repository does not create a schedule or overwrite your baseline. Every run has a separate output folder. Source changes, consent gates or access failures can change observations; inspect the evidence before treating a changed label as a confirmed software migration.

## 5. Turn differences into a review queue

Filter `comparison == "changed"`, inspect the evidence, and compare the two dated datasets. For a migration project, use the separate [Redirect & Canonical Audit](https://apify.com/kirozhang/website-migration-redirect-audit?utm_source=github&utm_medium=example_repository&utm_campaign=workday_tech_202611&utm_content=technology_related) to check intended old-to-new URL mappings.

Ready-made examples:

- [Build a technology inventory](https://apify.com/kirozhang/website-tech-stack-evidence/examples/build-website-technology-inventory?utm_source=github&utm_medium=example_repository&utm_campaign=workday_tech_202611&utm_content=inventory_example)
- [Compare against a dated baseline](https://apify.com/kirozhang/website-tech-stack-evidence/examples/compare-website-technology-baseline?utm_source=github&utm_medium=example_repository&utm_campaign=workday_tech_202611&utm_content=baseline_example)

If the client disconnects, use `python3 examples/run.py technology --resume YOUR_RUN_ID`. Resume fetches the original run and its original comparison; it does not rerun the check or change its baseline.
