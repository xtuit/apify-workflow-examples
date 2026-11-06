#!/usr/bin/env python3
"""Upsert exported jobs locally; missing rows are retained, never marked closed."""
import argparse
import json
from pathlib import Path


def merge(previous, current):
    inventory = {}
    for row in previous + current:
        if not isinstance(row, dict):
            raise ValueError('Each row must be an object')
        values = [row.get(k) for k in ['companyTenant', 'careerSite', 'jobId']]
        if not all(isinstance(v, str) and v for v in values):
            raise ValueError('Missing companyTenant, careerSite or jobId; inspect the original row')
        inventory[tuple(values)] = row
    return list(inventory.values())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Merge dated job exports; this is a retained inventory, not a current-open-jobs list.')
    parser.add_argument('previous', type=Path)
    parser.add_argument('current', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    previous = json.loads(args.previous.read_text(encoding='utf-8'))
    current = json.loads(args.current.read_text(encoding='utf-8'))
    if not isinstance(previous, list) or not isinstance(current, list):
        parser.error('Both exports must be JSON arrays')
    if args.output.resolve() in {args.previous.resolve(), args.current.resolve()}:
        parser.error('Write to a new file to preserve both source snapshots')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(merge(previous, current), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
