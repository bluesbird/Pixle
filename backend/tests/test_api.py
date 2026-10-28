from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from backend.app import COOKIE, create_app
from backend.catalog import ROOT, configure_puzzle, normalize_answer
from backend.database import Base, Game, Guess, Player, Puzzle, Result, make_engine


DAY = date(2026, 10, 28)
ASSET = "1d79c84a0dd89e24dd601cfe"


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        test_url = os.environ.get("PIXLE_TEST_DATABASE_URL")
        if test_url:
            base_engine = make_engine(test_url)
            self.schema = "pixle_test_" + uuid4().hex
            with base_engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
            self.engine = base_engine.execution_options(schema_translate_map={None: self.schema})

            def cleanup():
                with base_engine.begin() as connection:
                    connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
                base_engine.dispose()
            self.addCleanup(cleanup)
        else:
            self.engine = make_engine("sqlite:///" + str(self.root / "api.db"))
            self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        configure_puzzle(self.engine, DAY, ASSET)
        self.today = DAY
        self.app = create_app(self.engine, today=lambda: self.today, secure_cookie=False)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.assertEqual(self.client.post("/api/session").status_code, 201)

    def guess(self, name, request_id=None, client=None):
        return (client or self.client).post(
            f"/api/puzzles/{DAY}/guesses",
            json={"guess": name, "request_id": request_id or str(uuid4())},
        )

    def practice_guess(self, practice_id, name, request_id=None, client=None):
        return (client or self.client).post(
            f"/api/practice/{practice_id}/guesses",
            json={"guess": name, "request_id": request_id or str(uuid4())},
        )

    def skip(self, request_id=None, client=None):
        return (client or self.client).post(
            f"/api/puzzles/{DAY}/skip",
            json={"request_id": request_id or str(uuid4())},
        )

    def practice_skip(self, practice_id, request_id=None, client=None):
        return (client or self.client).post(
            f"/api/practice/{practice_id}/skip",
            json={"request_id": request_id or str(uuid4())},
        )

    def test_daily_initial_state_and_suggestions_do_not_identify_target(self):
        response = self.client.get("/api/puzzles/daily")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["date"], DAY.isoformat())
        self.assertEqual((body["attempts"], body["max_attempts"], body["level"]["level"]), (0, 5, 1))
        self.assertNotIn("answer", body)
        self.assertNotIn("target_id", body)
        self.assertNotIn("score", body)
        self.assertNotIn("einstein", response.text.lower())
        self.assertEqual(response.headers["cache-control"], "no-store")
        people = self.client.get("/api/people").json()
        self.assertEqual(len(people), 116)
        self.assertTrue(all(set(person) == {"id", "name"} for person in people))
        self.assertTrue(body["credits_url"].endswith("/credits.md"))
        self.assertEqual(self.client.get("/puzzles/private/" + ASSET + ".json").status_code, 404)

    def test_wrong_guess_reveals_next_level_and_reload_preserves_progress(self):
        body = self.guess("Taylor Swift").json()
        self.assertEqual(body["status"], "playing")
        self.assertEqual(body["level"]["level"], 2)
        self.assertEqual(body["attempts"], 1)
        self.assertFalse(body["guesses"][0]["correct"])
        self.assertNotIn("answer", body)
        self.assertEqual(self.client.get("/api/puzzles/daily").json(), body)

    def test_correct_guess_and_statistics(self):
        self.guess("Taylor Swift")
        body = self.guess(" ALBERT--Einstein! ").json()
        self.assertEqual(body["status"], "won")
        self.assertEqual(body["attempts"], 2)
        self.assertEqual(body["score"], 400)
        self.assertEqual(body["level"]["level"], 2)
        self.assertEqual(body["answer"], "Albert Einstein")
        self.assertTrue(body["guesses"][-1]["correct"])
        self.assertEqual(self.client.get("/api/stats/me").json(),
                         {"played": 1, "won": 1, "total_score": 400})
        self.assertEqual(self.guess("Adele").status_code, 409)
        self.assertTrue(body["original_image_url"].startswith("/api/people/"))
        self.assertEqual(self.client.get(f"/api/puzzles/{DAY}/original").status_code, 200)

    def test_original_image_is_hidden_until_finish(self):
        initial = self.client.get("/api/puzzles/daily").json()
        self.assertNotIn("original_image_url", initial)
        self.assertEqual(self.client.get(f"/api/puzzles/{DAY}/original").status_code, 409)
        self.guess("Albert Einstein")
        self.assertEqual(self.client.get(f"/api/puzzles/{DAY}/original").status_code, 200)

    def test_practice_round_is_unscored_and_separate_from_daily_stats(self):
        practice = self.client.post("/api/practice/random").json()
        self.assertEqual(practice["mode"], "practice")
        self.assertEqual(practice["status"], "playing")
        self.assertIn("practice_id", practice)
        self.assertNotIn("score", practice)
        self.assertTrue(all("/api/practice/" + practice["practice_id"] + "/" in level["url"]
                            for level in practice["levels"]))
        self.assertEqual(self.client.get(practice["levels"][0]["url"]).status_code, 200)
        self.assertEqual(self.client.get("/api/practice/" + practice["practice_id"]).status_code, 200)
        self.assertEqual(self.client.get("/api/practice/" + practice["practice_id"] + "/original").status_code, 409)
        body = practice
        for person in self.client.get("/api/people").json():
            if body["status"] != "playing":
                break
            response = self.practice_guess(practice["practice_id"], person["name"])
            self.assertEqual(response.status_code, 200)
            body = response.json()
            if body["status"] == "won":
                break
        self.assertIn(body["status"], ("won", "lost"))
        self.assertNotIn("score", body)
        self.assertIn("original_image_url", body)
        self.assertEqual(self.client.get("/api/practice/" + practice["practice_id"] + "/original").status_code, 200)
        self.assertEqual(self.client.get("/api/stats/me").json(),
                         {"played": 0, "won": 0, "total_score": 0})

    def test_mosaic_practice_uses_daily_puzzle_levels(self):
        practice = self.client.post("/api/practice/mosaic").json()
        self.assertEqual(practice["mode"], "practice")
        self.assertEqual(practice["status"], "playing")
        self.assertIn("practice_id", practice)
        self.assertTrue(practice["level"]["url"].startswith("/puzzles/" + ASSET + "/level-"))
        self.assertEqual(practice["credits_url"], f"/puzzles/{ASSET}/credits.md")

    def test_skip_advances_level_without_name_guess(self):
        body = self.skip().json()
        self.assertEqual(body["status"], "playing")
        self.assertEqual(body["attempts"], 1)
        self.assertEqual(body["level"]["level"], 2)
        self.assertEqual(body["guesses"][-1]["name"], "Skipped")
        self.assertFalse(body["guesses"][-1]["correct"])
        self.assertEqual(self.client.get("/api/puzzles/daily").json()["guesses"][-1]["name"], "Skipped")
        replay_id = str(uuid4())
        first = self.skip(replay_id).json()
        second = self.skip(replay_id).json()
        self.assertEqual(first, second)

    def test_practice_skip_advances_without_scoring(self):
        practice = self.client.post("/api/practice/random").json()
        body = self.practice_skip(practice["practice_id"]).json()
        self.assertEqual(body["status"], "playing")
        self.assertEqual(body["attempts"], 1)
        self.assertEqual(body["guesses"][-1]["name"], "Skipped")
        for _ in range(4):
            body = self.practice_skip(practice["practice_id"]).json()
        self.assertEqual(body["status"], "lost")
        self.assertNotIn("score", body)

    def test_first_and_last_guess_scoring(self):
        self.assertEqual(self.guess("albert-einstein").json()["score"], 500)
        with TestClient(self.app) as other:
            other.post("/api/session")
            for name in ["Adele", "Beyonce", "Rihanna", "Taylor Swift"]:
                self.assertEqual(self.guess(name, client=other).status_code, 200)
            body = self.guess("Albert Einstein", client=other).json()
            self.assertEqual((body["status"], body["score"], body["attempts"]), ("won", 100, 5))

    def test_loss_persists_one_zero_score_result(self):
        for name in ["Adele", "Beyonce", "Rihanna", "Taylor Swift", "Drake"]:
            response = self.guess(name)
            self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["status"], body["score"], body["level"]["level"]), ("lost", 0, 5))
        self.assertEqual(body["answer"], "Albert Einstein")
        self.assertEqual(self.guess("Albert Einstein").status_code, 409)
        self.assertEqual(self.client.get("/api/stats/me").json(),
                         {"played": 1, "won": 0, "total_score": 0})

    def test_idempotent_submission_and_conflicting_replay(self):
        request_id = str(uuid4())
        original = self.guess("Albert Einstein", request_id)
        self.assertEqual(self.guess("Albert Einstein", request_id).json(), original.json())
        self.assertEqual(self.guess("Adele", request_id).status_code, 409)
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(func.count(Result.game_id))), 1)
            self.assertEqual(session.scalar(select(func.count(Guess.id))), 1)

    def test_duplicate_person_does_not_consume_attempt(self):
        self.guess("Beyonce")
        self.assertEqual(self.guess("BEYONCE").status_code, 409)
        self.assertEqual(self.client.get("/api/puzzles/daily").json()["attempts"], 1)

    def test_invalid_inputs_cannot_submit_score_or_consume_attempt(self):
        cases = [
            {"guess": "", "request_id": str(uuid4())},
            {"guess": "!!!", "request_id": str(uuid4())},
            {"guess": "x" * 201, "request_id": str(uuid4())},
            {"guess": "Adele", "request_id": "invalid"},
            {"guess": "Adele", "request_id": str(uuid4()), "score": 500},
            {"guess": "Adele", "request_id": str(uuid4()), "correct": True},
            {"guess": 42, "request_id": str(uuid4())},
            {"guess": "not-a-person", "request_id": str(uuid4())},
        ]
        for body in cases:
            with self.subTest(body=body):
                response = self.client.post(f"/api/puzzles/{DAY}/guesses", json=body)
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.client.get("/api/puzzles/daily").json()["attempts"], 0)
        self.assertEqual(self.client.get("/api/stats/me").json()["played"], 0)
        self.assertEqual(self.client.get("/api/puzzles/not-a-date").status_code, 422)

    def test_date_selection_no_future_leak_and_expired_submissions(self):
        tomorrow = DAY + timedelta(days=1)
        configure_puzzle(self.engine, tomorrow, ASSET)
        self.assertEqual(self.client.get(f"/api/puzzles/{tomorrow}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/puzzles/{DAY - timedelta(days=1)}").status_code, 404)
        self.today = tomorrow
        self.assertEqual(self.client.get("/api/puzzles/daily").json()["date"], tomorrow.isoformat())
        self.assertEqual(self.guess("Adele").status_code, 409)
        self.assertEqual(self.client.get(f"/api/puzzles/{DAY}").status_code, 200)

    def test_missing_daily_puzzle(self):
        self.today = DAY + timedelta(days=2)
        self.assertEqual(self.client.get("/api/puzzles/daily").status_code, 404)

    def test_player_isolation_cookie_and_hashed_storage(self):
        self.guess("Adele")
        with TestClient(self.app) as other:
            self.assertEqual(other.get("/api/puzzles/daily").status_code, 401)
            self.assertEqual(other.get("/api/stats/me").status_code, 401)
            self.assertEqual(self.guess("Adele", client=other).status_code, 401)
            response = other.post("/api/session")
            self.assertIn("HttpOnly", response.headers["set-cookie"])
            self.assertIn("SameSite=lax", response.headers["set-cookie"])
            self.assertNotIn("token", response.text)
            self.assertEqual(other.get("/api/puzzles/daily").json()["attempts"], 0)
        token = self.client.cookies.get(COOKIE)
        self.assertEqual(self.client.post("/api/session").status_code, 201)
        self.assertEqual(self.client.cookies.get(COOKIE), token)
        with Session(self.engine) as session:
            self.assertIsNotNone(session.get(Player, hashlib.sha256(token.encode()).hexdigest()))
            self.assertIsNone(session.get(Player, token))

    def test_secure_cookie_default(self):
        app = create_app(self.engine, today=lambda: DAY, secure_cookie=True)
        with TestClient(app, base_url="https://testserver") as client:
            response = client.post("/api/session")
            self.assertIn("Secure", response.headers["set-cookie"])
            self.assertEqual(client.get("/api/puzzles/daily").status_code, 200)

    def test_catalogue_import_idempotency_and_conflict(self):
        configure_puzzle(self.engine, DAY, ASSET)
        with Session(self.engine) as session, session.begin():
            session.get(Puzzle, DAY).asset_id = "0" * 24
        with self.assertRaisesRegex(ValueError, "already assigned"):
            configure_puzzle(self.engine, DAY, ASSET)
        with self.assertRaisesRegex(ValueError, "24 lowercase"):
            configure_puzzle(self.engine, DAY, "../private")

    def test_import_rejects_tampered_asset(self):
        copy = self.root / "puzzles"
        shutil.copytree(ROOT / "puzzles", copy)
        path = copy / "public" / ASSET / "level-01.jpg"
        path.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            configure_puzzle(self.engine, DAY + timedelta(days=1), ASSET, puzzle_root=copy)

    def test_postgresql_schema_compiles(self):
        for table in Base.metadata.sorted_tables:
            sql = str(CreateTable(table).compile(dialect=postgresql.dialect()))
            self.assertIn("CREATE TABLE", sql)

    def test_concurrent_first_guesses_are_serialized_on_postgresql(self):
        if self.engine.dialect.name != "postgresql":
            self.skipTest("Requires PIXLE_TEST_DATABASE_URL for PostgreSQL row-lock verification")
        token = self.client.cookies.get(COOKIE)

        def submit(name):
            with TestClient(self.app) as client:
                client.cookies.set(COOKIE, token, path="/api")
                return self.guess(name, client=client)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(submit, ["Adele", "Rihanna"]))
        self.assertEqual([response.status_code for response in responses], [200, 200])
        self.assertEqual(self.client.get("/api/puzzles/daily").json()["attempts"], 2)
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(func.count(Game.id))), 1)

    def test_concurrent_terminal_retries_create_one_result_on_postgresql(self):
        if self.engine.dialect.name != "postgresql":
            self.skipTest("Requires PIXLE_TEST_DATABASE_URL for PostgreSQL row-lock verification")
        token = self.client.cookies.get(COOKIE)
        request_id = str(uuid4())

        def submit(_):
            with TestClient(self.app) as client:
                client.cookies.set(COOKIE, token, path="/api")
                return self.guess("Albert Einstein", request_id, client)
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(submit, range(2)))
        self.assertEqual([response.status_code for response in responses], [200, 200])
        self.assertEqual(responses[0].json(), responses[1].json())
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(func.count(Guess.id))), 1)
            self.assertEqual(session.scalar(select(func.count(Result.game_id))), 1)


class NormalizationTests(unittest.TestCase):
    def test_accents_punctuation_spacing_and_case(self):
        self.assertEqual(normalize_answer(" Beyoncé "), normalize_answer("BEYONCE"))
        self.assertEqual(normalize_answer("J. K. Rowling"), normalize_answer("jk-rowling"))
        self.assertNotEqual(normalize_answer("Albert Einstein"), normalize_answer("Albert E"))


if __name__ == "__main__":
    unittest.main()
