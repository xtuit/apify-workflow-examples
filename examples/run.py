#!/usr/bin/env python3
"""Call two hosted Apify Actors; this file contains no scraping implementation."""
import argparse
import csv
import getpass
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ACTORS = {
    'workday': ('kirozhang~workday-careers-job-exporter', 'vxR5bmv07v9DfdGjN'),
    'technology': ('kirozhang~website-tech-stack-evidence', 'gI5WbWjweESDVs5mg'),
}
TERMINAL = {'SUCCEEDED', 'FAILED', 'ABORTED', 'TIMED-OUT'}


class ApiError(RuntimeError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Authorization must never follow a redirect to a different service.
        return None


class Apify:
    def __init__(self, token):
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def request(self, path, method='GET', payload=None, unwrap=True):
        if not path.startswith('/v2/'):
            raise ValueError('Only the official Apify v2 API is supported')
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        req = urllib.request.Request('https://api.apify.com' + path,
            data=None if payload is None else json.dumps(payload).encode(),
            method=method, headers=headers)
        try:
            with self.opener.open(req, timeout=45) as response:
                value = json.load(response)
        except urllib.error.HTTPError as exc:
            raise ApiError('Apify returned HTTP %s during %s. Check Console and credentials.' % (exc.code, method)) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise ApiError('Apify response was not confirmed during %s. Check Console before retrying a start.' % method) from None
        return value.get('data', value) if unwrap and isinstance(value, dict) else value

    def start(self, kind, actor_input, max_charge):
        query = urllib.parse.urlencode({'memory': 256, 'timeout': 180,
                                       'maxTotalChargeUsd': max_charge})
        # Intentionally one POST: an unconfirmed response may still have created a run.
        return self.request('/v2/acts/' + ACTORS[kind][0] + '/runs?' + query,
                            method='POST', payload=actor_input)

    def get_run(self, run_id, wait=0):
        if not re.fullmatch(r'[A-Za-z0-9]+', run_id):
            raise ValueError('Invalid run ID')
        return self.request('/v2/actor-runs/' + run_id + '?waitForFinish=' + str(wait))

    def items(self, dataset_id):
        rows = []
        while True:
            # No clean/skip filters: short pages must genuinely mean pagination ended.
            page = self.request('/v2/datasets/' + dataset_id + '/items?' +
                urllib.parse.urlencode({'format': 'json', 'offset': len(rows), 'limit': 1000}))
            if not isinstance(page, list):
                raise ApiError('Dataset response is not a JSON array')
            rows.extend(page)
            if len(page) < 1000:
                return rows


def load_input(kind, path, baseline=None):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Input must be a JSON object')
    limit = value.get('maxResults')
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError('Example input requires maxResults between 1 and 1000')
    key = 'careerSiteUrls' if kind == 'workday' else 'urls'
    urls = value.get(key)
    if not isinstance(urls, list) or not urls or not all(isinstance(u, str) for u in urls):
        raise ValueError(key + ' must contain at least one public URL')
    if baseline is not None:
        if kind != 'technology':
            raise ValueError('--baseline is for technology checks only')
        previous = json.loads(Path(baseline).read_text(encoding='utf-8'))
        if not isinstance(previous, list) or any(not isinstance(r, dict) or
            not isinstance(r.get('key'), str) or not isinstance(r.get('technologyNames'), list) or
            not all(isinstance(x, str) for x in r['technologyNames']) for r in previous):
            raise ValueError('Baseline must be an array with real key and technologyNames values')
        if len({r['key'] for r in previous}) != len(previous):
            raise ValueError('Baseline contains duplicate keys')
        value['previousResults'] = previous
    return value


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def csv_cell(value):
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + value
    return value


def write_csv(path, rows, kind):
    fields = (['companyTenant', 'careerSite', 'jobId', 'title', 'location', 'country',
               'timeType', 'postedOn', 'postingStartDate', 'url', 'collectedAt', 'description']
              if kind == 'workday' else ['key', 'url', 'finalUrl', 'title', 'technologyNames',
               'technologyCount', 'comparison', 'changedFields', 'checkedAt'])
    with Path(path).open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_cell(row.get(key)) for key in fields})


def collect(client, kind, initial_run, output, wait_seconds=240):
    run = initial_run
    if not isinstance(run.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9]+', run['id']):
        raise ValueError('Invalid run ID returned by the API')
    if run.get('actId') != ACTORS[kind][1]:
        raise ValueError('Run belongs to a different Actor; choose the correct workflow')
    folder = Path(output) / run['id']
    folder.mkdir(parents=True, exist_ok=True)
    run_fields = ['id', 'actId', 'status', 'startedAt', 'finishedAt', 'buildId',
                  'defaultDatasetId', 'defaultKeyValueStoreId']
    def save_run():
        write_json(folder / 'run.json', {k: run.get(k) for k in run_fields})
    save_run()
    print('Run %s saved. Resume without starting again: python3 examples/run.py %s --resume %s --out-dir %s' %
          (run['id'], kind, run['id'], output), flush=True)
    deadline = time.monotonic() + wait_seconds
    while run['status'] not in TERMINAL:
        if time.monotonic() >= deadline:
            raise ApiError('Local wait ended. Cloud run may continue; use --resume with the saved run ID.')
        run = client.get_run(run['id'], wait=30)
        save_run()
    rows = client.items(run['defaultDatasetId'])
    write_json(folder / 'results.json', rows)
    write_csv(folder / 'results.csv', rows, kind)
    summary_error = None
    try:
        summary = client.request('/v2/key-value-stores/' + run['defaultKeyValueStoreId'] + '/records/RUN_SUMMARY', unwrap=False)
    except ApiError as exc:
        summary = None
        summary_error = str(exc)
    write_json(folder / 'summary.json', summary)
    complete = summary.get('complete') if isinstance(summary, dict) else None
    errors = summary.get('errors') if isinstance(summary, dict) else None
    if not isinstance(complete, bool) or not isinstance(errors, list):
        summary_error = summary_error or 'RUN_SUMMARY is missing completeness or error information; inspect Console.'
    # An old baseline is never overwritten automatically after a partial or failed scan.
    if kind == 'technology' and run['status'] == 'SUCCEEDED' and complete is True and errors == []:
        write_json(folder / 'next-baseline.json', [{'key': r['key'], 'technologyNames': r['technologyNames']} for r in rows])
    result = {'runId': run['id'], 'status': run['status'], 'rows': len(rows),
              'sourceScanComplete': complete, 'summaryError': summary_error,
              'limitReasons': summary.get('limitReasons') if isinstance(summary, dict) else None,
              'outputFolder': str(folder)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if run['status'] != 'SUCCEEDED' or summary_error:
        return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Run hosted Workday or technology Actors with a cost ceiling.')
    parser.add_argument('kind', choices=ACTORS)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--baseline', type=Path, help='Previous technology results.json or next-baseline.json')
    parser.add_argument('--resume', help='Read an existing run; does not start or charge for a new run')
    parser.add_argument('--out-dir', type=Path)
    parser.add_argument('--max-charge-usd', type=float, default=0.10)
    parser.add_argument('--validate-only', action='store_true', help='Check local JSON without an API call')
    args = parser.parse_args(argv)
    if not math.isfinite(args.max_charge_usd) or args.max_charge_usd <= 0:
        parser.error('--max-charge-usd must be finite and positive')
    if args.resume and (args.baseline or args.input or args.validate_only):
        parser.error('--resume reads the original run; do not combine it with input or baseline changes')
    try:
        actor_input = None if args.resume else load_input(args.kind, args.input or
            Path(__file__).parent / 'inputs' / (args.kind + '.json'), args.baseline)
        if args.validate_only:
            print(json.dumps({'valid': True, 'actor': ACTORS[args.kind][0], 'input': actor_input}, indent=2))
            return 0
        token = os.environ.get('APIFY_TOKEN') or getpass.getpass('Apify token (hidden input): ')
        if not token.strip():
            raise ValueError('An Apify token is required')
        client = Apify(token.strip())
        run = client.get_run(args.resume) if args.resume else client.start(args.kind, actor_input, args.max_charge_usd)
        return collect(client, args.kind, run, args.out_dir or Path('output') / args.kind)
    except (ApiError, ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Client stopped. Check Console and the saved run ID; the cloud run may still be active.', file=sys.stderr)
        return 130


if __name__ == '__main__':
    sys.exit(main())
