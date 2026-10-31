import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from backend.daily import DailyService
from backend.database import Puzzle, make_engine
from backend.practice import PracticeService
from backend.routes import register_routes
from backend.services import (
    COOKIE,
    load_context,
    player,
    resolve_secure_cookie,
    session_dependency_factory,
)


LOGGER = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent


def create_app(engine=None, today=None, secure_cookie=None):
    owns_engine = engine is None
    database = engine if engine is not None else make_engine()
    current_date = today or (lambda: datetime.now(timezone.utc).date())
    secure_cookie = resolve_secure_cookie(secure_cookie)

    @asynccontextmanager
    async def lifespan(_):
        try:
            with database.connect() as connection:
                connection.execute(text("SELECT 1"))
                connection.execute(select(Puzzle.date).limit(1))
            yield
        finally:
            if owns_engine:
                database.dispose()

    app = FastAPI(title="Pixle API", version="0.1.0", lifespan=lifespan)
    context = load_context(ROOT, database, current_date, secure_cookie)
    session_dependency = session_dependency_factory(database)
    daily_service = DailyService(context, player)
    practice_service = PracticeService(context, player, daily_service.level_outputs)

    @app.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error):
        LOGGER.error("Database operation failed for %s", request.url.path, exc_info=error)
        return JSONResponse(status_code=503, content={"detail": "Database temporarily unavailable"})

    register_routes(app, session_dependency, daily_service, practice_service)
    return app
