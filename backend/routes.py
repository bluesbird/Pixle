from datetime import date

from fastapi import Depends, Request, Response
from sqlalchemy import text

from backend.schemas import GameOutput, GuessInput, PersonOutput, SkipInput, StatisticsOutput


def register_routes(app, session_dependency, daily_service, practice_service):
    @app.get("/api/health")
    def health(session=Depends(session_dependency)):
        session.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.post("/api/session", status_code=201)
    def create_session(request: Request, response: Response, session=Depends(session_dependency)):
        return daily_service.create_session(request, response, session)

    @app.get("/api/people", response_model=list[PersonOutput])
    def people(session=Depends(session_dependency)):
        return daily_service.people(session)

    @app.get("/api/people/{person_id}/photo")
    def person_photo(person_id: str):
        return daily_service.person_photo(person_id)

    @app.get("/api/puzzles/daily", response_model=GameOutput, response_model_exclude_none=True)
    def daily(request: Request, session=Depends(session_dependency)):
        return daily_service.retrieve(daily_service.context.current_date(), request, session)

    @app.get("/api/puzzles/{puzzle_date}", response_model=GameOutput, response_model_exclude_none=True)
    def puzzle(puzzle_date: date, request: Request, session=Depends(session_dependency)):
        return daily_service.retrieve(puzzle_date, request, session)

    @app.get("/api/puzzles/{puzzle_date}/original")
    def daily_original(puzzle_date: date, request: Request, session=Depends(session_dependency)):
        return daily_service.daily_original(puzzle_date, request, session)

    @app.post("/api/puzzles/{puzzle_date}/guesses", response_model=GameOutput,
              response_model_exclude_none=True)
    def submit_guess(puzzle_date: date, body: GuessInput, request: Request, session=Depends(session_dependency)):
        return daily_service.submit_guess(puzzle_date, body, request, session)

    @app.post("/api/puzzles/{puzzle_date}/skip", response_model=GameOutput,
              response_model_exclude_none=True)
    def skip_guess(puzzle_date: date, body: SkipInput, request: Request, session=Depends(session_dependency)):
        return daily_service.skip_guess(puzzle_date, body, request, session)

    @app.post("/api/practice/random", response_model=GameOutput, response_model_exclude_none=True)
    def start_practice_random(request: Request, session=Depends(session_dependency)):
        return practice_service.start_practice_random(request, session)

    @app.post("/api/practice/mosaic", response_model=GameOutput, response_model_exclude_none=True)
    def start_practice_mosaic(request: Request, session=Depends(session_dependency)):
        return practice_service.start_practice_mosaic(request, session)

    @app.get("/api/practice/{practice_id}", response_model=GameOutput, response_model_exclude_none=True)
    def get_practice(practice_id: str, request: Request, session=Depends(session_dependency)):
        return practice_service.get_practice(practice_id, request, session)

    @app.post("/api/practice/{practice_id}/guesses", response_model=GameOutput, response_model_exclude_none=True)
    def submit_practice_guess(practice_id: str, body: GuessInput, request: Request, session=Depends(session_dependency)):
        return practice_service.submit_practice_guess(practice_id, body, request, session)

    @app.post("/api/practice/{practice_id}/skip", response_model=GameOutput, response_model_exclude_none=True)
    def skip_practice_guess(practice_id: str, body: SkipInput, request: Request, session=Depends(session_dependency)):
        return practice_service.skip_practice_guess(practice_id, body, request, session)

    @app.get("/api/practice/{practice_id}/level-{level}.jpg")
    def practice_level(practice_id: str, level: int, request: Request, session=Depends(session_dependency)):
        return practice_service.practice_level(practice_id, level, request, session)

    @app.get("/api/practice/{practice_id}/original")
    def practice_original(practice_id: str, request: Request, session=Depends(session_dependency)):
        return practice_service.practice_original(practice_id, request, session)

    @app.get("/api/stats/me", response_model=StatisticsOutput)
    def statistics(request: Request, session=Depends(session_dependency)):
        return daily_service.statistics(request, session)
