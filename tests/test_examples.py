import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
import run
from merge_jobs import merge


def job(company='example', site='Careers', job_id='J1', title='Earlier title'):
    return {'companyTenant': company, 'careerSite': site, 'jobId': job_id, 'title': title}


def finished(kind='technology', status='SUCCEEDED'):
    return {'id': 'ExampleRun123', 'actId': run.ACTORS[kind][1], 'status': status,
            'defaultDatasetId': 'ExampleDataset', 'defaultKeyValueStoreId': 'ExampleStore'}


class StubClient:
    def __init__(self, summary=None):
        self.summary = {'complete': True, 'errors': [], 'limitReasons': []} if summary is None else summary
        self.rows = [{'key': 'https://example.com/', 'technologyNames': [], 'comparison': 'unchanged'}]
        self.polls = 0

    def get_run(self, run_id, wait=0):
        self.polls += 1
        return finished()

    def items(self, dataset):
        return self.rows

    def request(self, *args, **kwargs):
        if isinstance(self.summary, Exception):
            raise self.summary
        return self.summary


class ClientTests(unittest.TestCase):
    def test_start_has_cost_and_time_caps_and_no_retry(self):
        client = run.Apify('not-a-real-token')
        with patch.object(client, 'request', side_effect=run.ApiError('response unconfirmed')) as request:
            with self.assertRaises(run.ApiError):
                client.start('workday', {'maxResults': 10}, 0.10)
            self.assertEqual(request.call_count, 1)
            self.assertIn('maxTotalChargeUsd=0.1', request.call_args.args[0])
            self.assertIn('timeout=180', request.call_args.args[0])
            self.assertEqual(request.call_args.kwargs['method'], 'POST')

    def test_auth_header_is_not_a_url_parameter(self):
        client = run.Apify('test-only-value')
        with patch.object(client.opener, 'open', side_effect=urllib.error.URLError('offline')) as op:
            with self.assertRaises(run.ApiError) as error:
                client.get_run('ExampleRun123')
            req = op.call_args.args[0]
            self.assertEqual(req.get_header('Authorization'), 'Bearer test-only-value')
            self.assertNotIn('test-only-value', req.full_url)
            self.assertNotIn('test-only-value', str(error.exception))

    def test_dataset_pagination_includes_the_last_page(self):
        client = run.Apify('test-only-value')
        with patch.object(client, 'request', side_effect=[[{} for _ in range(1000)], [{'last': True}]]) as request:
            rows = client.items('ExampleDataset')
            self.assertEqual(len(rows), 1001)
            self.assertIn('offset=1000', request.call_args.args[0])

    def test_resume_does_not_start_a_run(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'APIFY_TOKEN': 'test-only-value'}), \
             patch.object(run.Apify, 'get_run', return_value=finished()) as get, \
             patch.object(run.Apify, 'start') as start, patch.object(run, 'collect', return_value=0):
            self.assertEqual(run.main(['technology', '--resume', 'ExampleRun123', '--out-dir', folder]), 0)
            start.assert_not_called();get.assert_called_once_with('ExampleRun123')

    def test_complete_technology_scan_writes_real_empty_baseline(self):
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run.collect(StubClient(), 'technology', finished(), folder), 0)
            out = json.loads((Path(folder) / 'ExampleRun123/next-baseline.json').read_text())
            self.assertEqual(out, [{'key': 'https://example.com/', 'technologyNames': []}])

    def test_partial_scan_keeps_rows_but_does_not_advance_baseline(self):
        stub = StubClient({'complete': False, 'errors': [], 'limitReasons': ['maxResults']})
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run.collect(stub, 'technology', finished(), folder), 0)
            self.assertTrue((Path(folder) / 'ExampleRun123/results.json').exists())
            self.assertFalse((Path(folder) / 'ExampleRun123/next-baseline.json').exists())

    def test_failed_run_returns_failure_and_preserves_diagnostics(self):
        stub = StubClient({'complete': False, 'errors': [{'message': 'example failure'}], 'limitReasons': []})
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run.collect(stub, 'technology', finished(status='FAILED'), folder), 1)
            self.assertTrue((Path(folder) / 'ExampleRun123/summary.json').exists())
            self.assertFalse((Path(folder) / 'ExampleRun123/next-baseline.json').exists())

    def test_missing_or_malformed_summary_does_not_claim_success(self):
        for summary in [run.ApiError('404 summary unavailable'), {'unexpected': True}]:
            with self.subTest(summary=str(summary)), tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(run.collect(StubClient(summary), 'technology', finished(), folder), 1)

    def test_wrong_actor_cannot_be_resumed_as_another_workflow(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                run.collect(StubClient(), 'workday', finished('technology'), folder)

    def test_polling_finishes_existing_run(self):
        stub = StubClient()
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(run.collect(stub, 'technology', finished(status='RUNNING'), folder), 0)
            self.assertEqual(stub.polls, 1)

    def test_missing_job_rows_are_retained_and_companies_do_not_collide(self):
        older = [job(job_id='old'), job(), job(company='another')]
        newer = [job(title='Updated title')]
        rows = merge(older, newer)
        self.assertEqual(len(rows), 3)
        self.assertEqual([r for r in rows if r['companyTenant']=='example' and r['jobId']=='J1'][0]['title'], 'Updated title')
        self.assertTrue(any(r['jobId']=='old' for r in rows))

    def test_missing_identity_is_rejected_instead_of_merging_unrelated_jobs(self):
        with self.assertRaises(ValueError):
            merge([], [{'jobId': None}])

    def test_csv_formula_cells_are_neutralized(self):
        self.assertEqual(run.csv_cell('=1+1'), "'=1+1")
        self.assertEqual(run.csv_cell('  @formula'), "'  @formula")
        self.assertEqual(run.csv_cell('ordinary title'), 'ordinary title')

    def test_inputs_and_real_empty_baselines_validate_offline(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(run.load_input('workday', root/'examples/inputs/workday.json')['maxResults'], 10)
        with tempfile.TemporaryDirectory() as folder:
            baseline = Path(folder)/'baseline.json'
            baseline.write_text('[{"key":"https://example.com/","technologyNames":[]}]')
            value = run.load_input('technology', root/'examples/inputs/technology.json', baseline)
            self.assertEqual(value['previousResults'][0]['technologyNames'], [])
            baseline.write_text('[{"key":"x","technologyNames":[]},{"key":"x","technologyNames":[]}]')
            with self.assertRaises(ValueError):
                run.load_input('technology', root/'examples/inputs/technology.json', baseline)


if __name__ == '__main__':
    unittest.main()
