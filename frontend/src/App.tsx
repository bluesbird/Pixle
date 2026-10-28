import { useEffect, useRef, useState } from "react";
import { z } from "zod";
import {
  ApiError, gameSchema, normalize, pendingSchema, peopleSchema, request, shareText, statsSchema,
  type Game, type Pending, type Person, type Stats,
} from "./api";

const PENDING_KEY = "pixle.pending.v1";

function message(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong. Please try again.";
}

export function App() {
  const [game, setGame] = useState<Game | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [statsError, setStatsError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [pending, setPending] = useState<Pending | null>(null);
  const [storageError, setStorageError] = useState("");
  const [share, setShare] = useState("");
  const [imageState, setImageState] = useState<"loading" | "ready" | "error">("loading");
  const [imageRetry, setImageRetry] = useState(0);
  const submitting = useRef(false);
  const input = useRef<HTMLInputElement>(null);
  const result = useRef<HTMLHeadingElement>(null);

  async function loadStats() {
    try {
      setStats(await request("/api/stats/me", statsSchema));
      setStatsError("");
    } catch (failure) {
      setStatsError(message(failure));
    }
  }

  async function load() {
    setLoading(true);
    setError("");
    try {
      await request("/api/session", z.object({ status: z.literal("ready") }), {});
      const [nextGame, catalogue] = await Promise.all([
        request("/api/puzzles/daily", gameSchema), request("/api/people", peopleSchema),
      ]);
      setGame(nextGame);
      setPeople(catalogue);
      try {
        const saved = sessionStorage.getItem(PENDING_KEY);
        if (saved) {
          const parsed = pendingSchema.safeParse(JSON.parse(saved));
          if (!parsed.success) {
            sessionStorage.removeItem(PENDING_KEY);
            setStorageError("An unreadable saved submission was removed. Server progress is unchanged.");
          } else if (parsed.data.date === nextGame.date) {
            setPending(parsed.data);
            setQuery(parsed.data.guess);
            setNotice("A submission is awaiting confirmation. Retry it safely below.");
          } else {
            sessionStorage.removeItem(PENDING_KEY);
            setPending(null);
            setNotice("A new daily puzzle is ready. Yesterday's pending submission has expired.");
          }
        }
      } catch {
        setStorageError("Browser storage is unavailable or unreadable. Keep this tab open while retrying a submission.");
      }
      void loadStats();
    } catch (failure) {
      setError(message(failure));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);
  useEffect(() => {
    setImageState("loading");
    setImageRetry(0);
  }, [game?.level.url]);
  useEffect(() => {
    if (game && game.status !== "playing") result.current?.focus();
  }, [game?.status]);

  function remember(value: Pending | null) {
    setPending(value);
    try {
      if (value) sessionStorage.setItem(PENDING_KEY, JSON.stringify(value));
      else sessionStorage.removeItem(PENDING_KEY);
    } catch {
      setStorageError("Browser storage is unavailable. Keep this tab open while retrying a submission.");
    }
  }

  async function submit() {
    if (!game || submitting.current || loading) return;
    const guess = query.trim();
    if (!pending && !normalize(guess)) {
      setError("Enter a person's name first.");
      input.current?.focus();
      return;
    }
    if (!pending && game.guesses.some((previous) => normalize(previous.name) === normalize(guess))) {
      setError("You have already guessed this person. Try another name.");
      return;
    }
    submitting.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    setOpen(false);
    const attempt = pending ?? { date: game.date, guess, request_id: crypto.randomUUID() };
    remember(attempt);
    try {
      const next = await request(`/api/puzzles/${attempt.date}/guesses`, gameSchema, {
        guess: attempt.guess, request_id: attempt.request_id,
      });
      setGame(next);
      remember(null);
      setQuery("");
      setNotice(next.status === "playing" ? "Not quite. A more detailed mosaic is now revealed." :
        next.status === "won" ? "That's right! You solved today's Pixle." : "Today's puzzle is finished.");
      if (next.status !== "playing") void loadStats();
      else input.current?.focus();
    } catch (failure) {
      // Network/server failures may follow a committed guess. Keep its UUID for a safe retry.
      if (failure instanceof ApiError && [401, 409, 422].includes(failure.status)) {
        remember(null);
      }
      setError(message(failure));
    } finally {
      setBusy(false);
      submitting.current = false;
    }
  }

  const matches = query.trim() ? people.filter((person) =>
    normalize(person.name).includes(normalize(query)) &&
    !game?.guesses.some((guess) => normalize(guess.name) === normalize(person.name))
  ).slice(0, 7) : [];
  const finished = game !== null && game.status !== "playing";
  const canGuess = game !== null && !finished && !loading && !busy;

  async function copyResult() {
    if (!game || !finished) return;
    const text = shareText(game);
    try {
      await navigator.clipboard.writeText(text);
      setShare("");
      setNotice("Result copied. No answer is included.");
    } catch {
      setShare(text);
      setNotice("Clipboard access is unavailable. Copy the result below.");
    }
  }

  return <div className="shell">
    <header className="masthead">
      <a className="brand" href="/" aria-label="Pixle home"><span className="brand-mark" aria-hidden="true">P</span>pixle<span className="brand-dot">.</span></a>
      <span className="edition">A new face, every day</span>
    </header>
    <main>
      <section className="intro" aria-labelledby="title">
        <p className="eyebrow">THE DAILY PHOTO MOSAIC</p>
        <h1 id="title">Familiar faces.<br /><span>One hidden identity.</span></h1>
        <p>Look at the bigger picture. Who do all these faces make?</p>
      </section>

      <div className="game-layout">
        <section className="mosaic-card" aria-label="Daily mosaic">
          <div className="card-heading">
            <span>{game ? <time dateTime={game.date}>{new Date(`${game.date}T12:00:00Z`).toLocaleDateString("en", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" })}</time> : "Today's puzzle"}</span>
            <span className="live-tag">DAILY / UTC</span>
          </div>
          <div className="mosaic-frame" aria-busy={loading || imageState === "loading"}>
            {game ? <>
              <img key={`${game.level.url}-${imageRetry}`}
                src={`${game.level.url}${imageRetry ? `?retry=${imageRetry}` : ""}`}
                alt={`Photo mosaic, detail level ${game.level.level} of ${game.max_attempts}. Identify the hidden person.`}
                width={game.level.width} height={game.level.height}
                onLoad={() => setImageState("ready")} onError={() => setImageState("error")} />
              {imageState === "loading" && <div className="image-overlay" role="status">Loading mosaic...</div>}
              {imageState === "error" && <div className="image-overlay">
                <p role="alert">The mosaic could not load.</p>
                <button onClick={() => { setImageState("loading"); setImageRetry((value) => value + 1); }}>Retry image</button>
              </div>}
            </> : <div className="placeholder" role="status">{loading ? "Preparing today's mosaic..." : "Your mosaic will appear here."}</div>}
          </div>
          <div className="mosaic-caption">
            <span>{game ? `Detail ${game.level.level} / ${game.max_attempts}` : "Made of familiar faces"}</span>
            {game && <a href={game.credits_url} target="_blank" rel="noreferrer">Photo credits <span aria-hidden="true">&#8599;</span></a>}
          </div>
        </section>

        <section className="play-panel" aria-label="Guess the person">
          {loading && <p role="status">Loading your saved progress...</p>}
          {error && <div className="error-box" role="alert"><p>{error}</p>
            {!pending && <button className="text-button" disabled={busy || loading} onClick={() => void load()}>Refresh progress</button>}
          </div>}
          {storageError && <p className="warning" role="alert">{storageError}</p>}
          <p className="feedback" role="status" aria-live="polite">{notice}</p>
          {game && <>
            <p className="eyebrow">{finished ? "THE BIG PICTURE" : `GUESS ${Math.min(game.attempts + 1, game.max_attempts)} OF ${game.max_attempts}`}</p>
            <div className="progress" aria-label={`${game.attempts} of ${game.max_attempts} guesses used`}>
              {Array.from({ length: game.max_attempts }, (_, index) =>
                <span key={index} className={index < game.attempts ? (game.guesses[index]?.correct ? "correct" : "used") : ""} />)}
            </div>
            {finished ? <div className="result">
              <h2 ref={result} tabIndex={-1}>{game.status === "won" ? "You saw it." : "Meet today's face."}</h2>
              <p className="answer">{game.answer}</p>
              <p><strong className="score">{game.score}</strong> points <span className="muted">/ {game.max_attempts * 100}</span></p>
              <p>{game.status === "won" ? `Solved in ${game.attempts} ${game.attempts === 1 ? "guess" : "guesses"}.` : "A fresh challenge arrives at midnight UTC."}</p>
              <button className="primary" onClick={() => void copyResult()}>Copy spoiler-free result <span aria-hidden="true">&#8599;</span></button>
              {share && <label className="share-fallback">Copy this result<textarea readOnly value={share} onFocus={(event) => event.target.select()} rows={5} /></label>}
            </div> : <form onSubmit={(event) => { event.preventDefault(); void submit(); }}
              onBlur={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
              }}>
              <h2>Who's the face?</h2>
              <p className="muted">Each miss reveals a little more.</p>
              <label htmlFor="guess">Your guess</label>
              <div className="suggestions">
                <input ref={input} id="guess" role="combobox" aria-autocomplete="list"
                  aria-expanded={open && !pending && query.trim().length > 0}
                  aria-controls={open && !pending && query.trim() ? "people-list" : undefined}
                  aria-activedescendant={open && active >= 0 && matches[active] ? `person-${active}` : undefined}
                  autoComplete="off" maxLength={200} placeholder="Start typing a name..."
                  value={query} disabled={!canGuess || pending !== null}
                  onFocus={() => setOpen(true)}
                  onChange={(event) => { setQuery(event.target.value); setOpen(true); setActive(-1); setError(""); }}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") { setOpen(false); setActive(-1); }
                    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                      event.preventDefault();
                      setOpen(true);
                      setActive((value) => matches.length ? (event.key === "ArrowDown" ?
                        (value + 1) % matches.length : (value <= 0 ? matches.length - 1 : value - 1)) : -1);
                    }
                    if (event.key === "Enter" && open && active >= 0 && matches[active]) {
                      event.preventDefault();
                      setQuery(matches[active].name); setOpen(false); setActive(-1);
                    }
                  }} />
                {open && !pending && query.trim() && <ul id="people-list" role="listbox" aria-label="People suggestions">
                  {matches.length ? matches.map((person, index) =>
                    <li key={person.id} id={`person-${index}`} role="option" aria-selected={index === active}
                      onPointerDown={(event) => { event.preventDefault(); setQuery(person.name); setOpen(false); setActive(-1); }}>
                      {person.name}
                    </li>) : <li role="presentation" className="no-match">No matching people. Try another name.</li>}
                </ul>}
              </div>
              <button className="primary" type="submit" disabled={!canGuess || (!pending && !query.trim())}>
                {busy ? "Checking..." : pending ? "Retry pending guess" : "Make a guess"} <span aria-hidden="true">&#8594;</span>
              </button>
            </form>}
            {pending && finished && <button disabled={busy} onClick={() => void submit()}>Confirm pending submission</button>}
            {game.guesses.length > 0 && <div className="history">
              <h3>Your guesses</h3>
              <ol>{game.guesses.map((guess) => <li key={guess.attempt}>
                <span className="attempt-number">{guess.attempt.toString().padStart(2, "0")}</span>
                <span>{guess.name}</span><span className={guess.correct ? "good" : "muted"}>{guess.correct ? "Correct" : "Not quite"}</span>
              </li>)}</ol>
            </div>}
          </>}
          {!game && !loading && !error && <p>No puzzle is available yet.</p>}
          <details className="how-to">
            <summary>How to play</summary>
            <p>Find the famous person hidden in the mosaic. Choose a name and make a guess.
              A wrong guess unlocks a finer mosaic. Fewer guesses mean more points.</p>
            <p>One puzzle worldwide, resetting at midnight UTC. Your progress is saved anonymously in this browser.</p>
          </details>
          <section className="stats" aria-label="Your statistics">
            <h3>Your daily record</h3>
            {stats ? <dl><div><dt>Played</dt><dd>{stats.played}</dd></div><div><dt>Won</dt><dd>{stats.won}</dd></div><div><dt>Points</dt><dd>{stats.total_score}</dd></div></dl> : !statsError && <p className="muted">Statistics load with your puzzle.</p>}
            {statsError && <div role="alert"><p>{statsError}</p><button className="text-button" onClick={() => void loadStats()}>Retry statistics</button></div>}
          </section>
        </section>
      </div>
    </main>
    <footer><span>A little perspective changes everything.</span><span>pixle / one puzzle a day</span></footer>
  </div>;
}
