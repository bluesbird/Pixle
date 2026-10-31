from datetime import date
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.catalog import normalize_answer


class GuessInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guess: str = Field(min_length=1, max_length=200)
    request_id: UUID

    @field_validator("guess")
    @classmethod
    def meaningful_guess(cls, value):
        if not normalize_answer(value):
            raise ValueError("Guess must contain a person's name")
        return value


class SkipInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class PersonOutput(BaseModel):
    id: str
    name: str


class LevelOutput(BaseModel):
    level: int
    grid: int
    width: int
    height: int
    url: str


class GuessOutput(BaseModel):
    attempt: int
    name: str
    correct: bool


class GameOutput(BaseModel):
    date: date
    puzzle_id: str
    mode: str
    status: str
    attempts: int
    max_attempts: int
    level: LevelOutput
    levels: list[LevelOutput]
    guesses: list[GuessOutput]
    credits_url: str
    practice_id: str | None = None
    original_image_url: str | None = None
    score: int | None = None
    answer: str | None = None


class StatisticsOutput(BaseModel):
    played: int
    won: int
    total_score: int
