# Build a Workday company job feed

Use this workflow when you already know which employers to follow and need structured public job listings for a job board, recruiting research or company analysis.

[Open the Workday Actor and current pricing](https://apify.com/kirozhang/workday-careers-job-exporter?utm_source=github&utm_medium=example_repository&utm_campaign=workday_tech_202611&utm_content=workday_guide).

## 1. Find the career-site URL

Use a public Workday-hosted URL such as:

```text
https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite
```

Include the career-site name after the domain. A custom employer website may link to its Workday-hosted board; copy that board URL. Employee portals, applicant records and authenticated HR systems are outside this Actor's scope.

## 2. Validate a small input

The [default input](../examples/inputs/workday.json) contains:

```json
{
  "careerSiteUrls": ["https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"],
  "searchText": "engineer",
  "includeDescription": true,
  "maxJobs": 10,
  "maxResults": 10
}
```

From the repository root:

```bash
python3 examples/run.py workday --validate-only
python3 examples/run.py workday
```

The first command validates local input. The second starts a real run using your token, with a $0.10 maximum charge. The default ten delivered jobs are at most $0.015 in Actor result charges at the 6 November 2026 listed rate. Source content and pricing can change; review the current Pricing tab.

To use your own input, keep a result cap:

```bash
python3 examples/run.py workday --input path/to/your-input.json
```

The example client accepts result caps up to 1,000. Broader exports may need different cloud timeouts or separate runs; this client keeps its 180-second timeout. A request cap is not a guarantee of complete coverage.

## 3. Check the output

The command prints the run ID and output directory. Open `results.json`, `results.csv` and `summary.json` there.

| Fields | Use |
|---|---|
| `companyTenant`, `careerSite`, `jobId` | A composite key for repeated exports |
| `title`, `location`, `country`, `timeType` | Available public job attributes |
| `description`, `descriptionHtml` | Public detail when enabled and successfully fetched |
| `postedOn`, `postingStartDate` | Preserve source text and dates separately |
| `url`, `collectedAt` | Provenance and collection time |

Text such as `Posted 30+ Days Ago` stays source text. Do not treat it as an exact posting date. Unknown attributes stay `null`. If a requested job detail fails, that job is omitted and the failure appears in the summary.

Inspect `summary.boards`: the reported source total, returned count, detail errors and `complete` flag. Ten rows from a company with more matches are a partial sample, even when the run succeeds.

## 4. Keep dated exports and upsert locally

Every run gets its own output folder. After two exports, merge them without another API call:

```bash
python3 examples/merge_jobs.py \
  output/workday/EARLIER_RUN_ID/results.json \
  output/workday/LATER_RUN_ID/results.json \
  output/workday/inventory.json
```

The utility matches `(companyTenant, careerSite, jobId)`, lets the later file replace matching rows, and retains earlier rows not seen in the later export. **This retained inventory is not a list of currently open jobs.** It neither deletes unseen jobs nor labels them closed. Keep both dated source exports for audit.

A missing listing could be outside the sampled pages, excluded by a changed search or affected by a source failure. Consider a closure only after comparable, complete scans with the same employer, career site and search. The Actor itself does not maintain a persistent job history or emit inferred closure events.

## 5. Add repetition after a useful first result

Save your working input as an Apify task and configure an [Apify schedule](https://docs.apify.com/actors/running/schedules), or run this client from your existing scheduler. Keep credentials in your scheduler's secret store. Neither this repository nor the sample input creates a schedule automatically.

Use one task per company when each employer needs predictable coverage. With several career sites in one input, `maxJobs` and `maxResults` are shared and earlier sites can consume the cap. Repeated exports can be charged again.

## Ready-made examples and recovery

- [NVIDIA engineering jobs](https://apify.com/kirozhang/workday-careers-job-exporter/examples/export-nvidia-engineering-jobs?utm_source=github&utm_medium=example_repository&utm_campaign=workday_tech_202611&utm_content=nvidia_example)
- [Adobe career jobs](https://apify.com/kirozhang/workday-careers-job-exporter/examples/export-adobe-career-jobs?utm_source=github&utm_medium=example_repository&utm_campaign=workday_tech_202611&utm_content=adobe_example)

If polling or downloading is interrupted, run `python3 examples/run.py workday --resume YOUR_RUN_ID`. This reads the same run; it does not start a replacement. If the run failed or timed out, inspect its summary and Console before deciding whether a new run is justified.

For Greenhouse, Lever, Ashby and other supported career platforms, see the separate [Company Hiring Monitor](https://apify.com/kirozhang/company-hiring-monitor?utm_source=github&utm_medium=example_repository&utm_campaign=workday_tech_202611&utm_content=workday_related). Its coverage differs from the Workday Actor.
