"""initial schema

Revision ID: 20261031_0001
Revises:
Create Date: 2026-10-31 16:55:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20261031_0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "people",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "players",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_table(
        "puzzles",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("asset_id", sa.String(length=24), nullable=False),
        sa.Column("target_id", sa.String(length=100), nullable=False),
        sa.Column("levels", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["target_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("date"),
    )
    op.create_table(
        "games",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.String(length=64), nullable=False),
        sa.Column("puzzle_date", sa.Date(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.CheckConstraint("attempts >= 0"),
        sa.CheckConstraint("status IN ('playing', 'won', 'lost')"),
        sa.ForeignKeyConstraint(["player_id"], ["players.token_hash"]),
        sa.ForeignKeyConstraint(["puzzle_date"], ["puzzles.date"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("player_id", "puzzle_date"),
    )
    op.create_index("ix_games_player_id", "games", ["player_id"], unique=False)
    op.create_table(
        "guesses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("person_id", sa.String(length=100), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.CheckConstraint("attempt > 0"),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_id", "attempt"),
        sa.UniqueConstraint("game_id", "person_id"),
        sa.UniqueConstraint("game_id", "request_id"),
    )
    op.create_index("ix_guesses_game_id", "guesses", ["game_id"], unique=False)
    op.create_table(
        "results",
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("score >= 0"),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"]),
        sa.PrimaryKeyConstraint("game_id"),
    )


def downgrade() -> None:
    op.drop_table("results")
    op.drop_index("ix_guesses_game_id", table_name="guesses")
    op.drop_table("guesses")
    op.drop_index("ix_games_player_id", table_name="games")
    op.drop_table("games")
    op.drop_table("puzzles")
    op.drop_table("players")
    op.drop_table("people")
