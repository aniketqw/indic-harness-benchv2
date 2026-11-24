
import argparse
import json
import re

from bench.lease import ControllerLease

from .controller import RESULTS, build_images, pause, run, state
from .suite import ROOT, catalog, review
from .validate import validate


def main():
    parser = argparse.ArgumentParser(description='Phase-two Indic Harness Bench')
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('review')
    commands.add_parser('build')
    commands.add_parser('validate')
    for name in ('start', 'resume', 'pause', 'status'):
        command = commands.add_parser(name)
        command.add_argument('campaign', help='Local campaign name')
        if name == 'start':
            command.add_argument('--scope', choices=('full', 'pilot'), required=True)
        if name in ('start', 'resume'):
            command.add_argument('--limit', type=int, help='Maximum new conditions in this session')
            command.add_argument('--workers', type=int, default=3, help='Conditions run in parallel (1-3)')
        if name == 'pause':
            command.add_argument('--wait', action='store_true')
    args = parser.parse_args()
    if args.action == 'review':
        destination = ROOT / 'work/phase2-review'
        review(destination, catalog())
        print(destination / 'README.md')
        return
    if args.action in ('build', 'validate'):
        with ControllerLease(RESULTS / 'controller.lock'):
            (build_images if args.action == 'build' else validate)()
        return
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,49}', args.campaign):
        parser.error('Use a short campaign name with lowercase letters, digits and hyphens.')
    if args.campaign in {'con', 'prn', 'aux', 'nul'} or re.fullmatch(r'(?:com|lpt)[1-9]', args.campaign):
        parser.error('Use a campaign name that is valid on Windows.')
    folder = RESULTS / args.campaign
    if args.action in ('start', 'resume'):
        if args.limit is not None and args.limit < 1:
            parser.error('--limit must be positive')
        if not 1 <= args.workers <= 3:
            parser.error('--workers must be between 1 and 3')
        run(folder, resume=args.action == 'resume', scope=getattr(args, 'scope', None),
            limit=args.limit, workers=args.workers)
    elif args.action == 'pause':
        print(json.dumps(pause(folder, wait=args.wait), indent=2))
    else:
        print(json.dumps(state(folder), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(str(error)) from None
