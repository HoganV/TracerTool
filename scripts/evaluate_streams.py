#!/usr/bin/env python3
"""Run a frozen paired-stream manifest. Exit 2 means thresholds failed; 1 input error."""
import argparse
import json
from pathlib import Path
import sys

from tracertool.evaluation import run_pair, threshold_passed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--method', choices=('legacy', 'auto'), default='legacy')
    parser.add_argument('--spacing', type=float, default=1.)
    parser.add_argument('--max-dimension', type=int, default=2500)
    parser.add_argument('--max-p95', type=float)
    parser.add_argument('--max-non-candidate-fraction', type=float, default=0.)
    args = parser.parse_args(argv)
    try:
        if args.max_dimension < 2:
            raise ValueError('max-dimension must be at least two')
        report = run_pair(args.manifest, args.data_dir, args.method, args.spacing, args.max_dimension)
        passed = threshold_passed(report, args.max_p95, args.max_non_candidate_fraction)
        report['threshold_passed'] = passed
        report['thresholds'] = dict(max_p95=args.max_p95, max_non_candidate_fraction=args.max_non_candidate_fraction)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
        print(json.dumps(dict(output=str(args.output), counts=report['counts'],
                              reach_summary=report['reach_summary'], threshold_passed=passed)))
        return 0 if passed else 2
    except (ValueError, KeyError, OSError, ImportError) as error:
        print(f'Evaluation input/engine error: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
