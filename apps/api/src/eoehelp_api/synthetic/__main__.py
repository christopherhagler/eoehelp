"""Seed a development database with synthetic patients.

    python -m eoehelp_api.synthetic --patients 5 --months 18 --seed 42

Refuses to run against production, and requires --allow-staging for staging. See
writer.assert_writable for why that is a hard stop rather than a warning.
"""

import argparse
import asyncio
import sys

from eoehelp_api.config import get_settings
from eoehelp_api.db.session import dispose_engine
from eoehelp_api.observability import configure_logging
from eoehelp_api.synthetic.generator import HistoryGenerator
from eoehelp_api.synthetic.writer import SyntheticDataRefusedError, assert_writable, write_history


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m eoehelp_api.synthetic")
    parser.add_argument("--patients", type=int, default=3, help="how many to create")
    parser.add_argument("--months", type=int, default=18, help="length of each history")
    parser.add_argument(
        "--seed",
        type=int,
        default=1,
        help="base seed; patient N uses seed+N, so a run is reproducible",
    )
    parser.add_argument(
        "--allow-staging",
        action="store_true",
        help="required to write to staging; production is always refused",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(environment=settings.environment, debug=settings.debug)

    try:
        assert_writable(settings, allow_staging=args.allow_staging)
    except SyntheticDataRefusedError as refusal:
        print(f"error: {refusal}", file=sys.stderr)
        return 1

    print(f"seeding {args.patients} synthetic patient(s), {args.months} months each\n")
    try:
        for index in range(args.patients):
            plan = HistoryGenerator(seed=args.seed + index).generate(months=args.months)
            written = await write_history(plan, allow_staging=args.allow_staging)
            print(f"  {written.email}")
            print(f"    timezone {written.timezone}")
            print(
                f"    {written.symptom_entries} symptom entries "
                f"({written.first_day} to {written.last_day})"
            )
            print(f"    {written.medications} medications, {written.doses} doses")
            for epoch in written.epochs:
                print(f"    - {epoch}")
            print()
    finally:
        await dispose_engine()

    print("done. sign in as any address above; the magic link lands in Mailhog.")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_run(_parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
