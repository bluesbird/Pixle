"""Explicit offline schema initialization and daily puzzle assignment."""

import argparse
from datetime import date

from backend.catalog import configure_puzzle
from backend.database import Base, make_engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    configure = commands.add_parser("configure-puzzle")
    configure.add_argument("--date", required=True, type=date.fromisoformat)
    configure.add_argument("--asset-id", required=True)
    args = parser.parse_args()
    engine = make_engine()
    try:
        if args.command == "init-db":
            Base.metadata.create_all(engine)
            print("Initialized Pixle schema.")
        else:
            configure_puzzle(engine, args.date, args.asset_id)
            print(f"Configured puzzle for {args.date.isoformat()}.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
