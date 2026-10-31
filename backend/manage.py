"""Database management and daily puzzle assignment."""

import argparse
from datetime import date
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from backend.catalog import configure_puzzle
from backend.database import Base, make_engine


ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI = ROOT / "alembic.ini"
APP_TABLES = {"people", "puzzles", "players", "games", "guesses", "results"}


def alembic_config(engine=None):
    config = Config(str(ALEMBIC_INI))
    if engine is not None:
        config.set_main_option("sqlalchemy.url", str(engine.url).replace("%", "%%"))
    return config


def migrate(engine):
    config = alembic_config(engine)
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        has_version = "alembic_version" in tables
        has_app_tables = bool(APP_TABLES & tables)
        if not has_version:
            if not has_app_tables:
                command.upgrade(config, "head")
                return "Applied migrations to an empty database."
            if APP_TABLES.issubset(tables):
                command.stamp(config, "head")
                command.upgrade(config, "head")
                return "Stamped existing schema to head and applied pending migrations."
            missing = ", ".join(sorted(APP_TABLES - tables))
            raise ValueError(
                f"Database schema is partially initialized; missing tables: {missing}. "
                "Back up and repair schema manually before Alembic migration."
            )
        command.upgrade(config, "head")
        return "Database already versioned; applied pending migrations."


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    commands.add_parser("migrate")
    stamp = commands.add_parser("stamp-head")
    stamp.add_argument("--revision", default="head")
    revision = commands.add_parser("make-migration")
    revision.add_argument("--message", required=True)
    revision.add_argument("--autogenerate", action="store_true")
    configure = commands.add_parser("configure-puzzle")
    configure.add_argument("--date", required=True, type=date.fromisoformat)
    configure.add_argument("--asset-id", required=True)
    args = parser.parse_args()
    engine = make_engine()
    try:
        if args.command == "init-db":
            Base.metadata.create_all(engine)
            print("Initialized Pixle schema.")
        elif args.command == "migrate":
            print(migrate(engine))
        elif args.command == "stamp-head":
            config = alembic_config(engine)
            with engine.begin() as connection:
                config.attributes["connection"] = connection
                command.stamp(config, args.revision)
            print(f"Stamped database at {args.revision}.")
        elif args.command == "make-migration":
            config = alembic_config(engine)
            with engine.connect() as connection:
                config.attributes["connection"] = connection
                command.revision(config, message=args.message, autogenerate=args.autogenerate)
            print("Created migration revision.")
        else:
            configure_puzzle(engine, args.date, args.asset_id)
            print(f"Configured puzzle for {args.date.isoformat()}.")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
