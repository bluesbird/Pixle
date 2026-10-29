import { useEffect, useMemo, useRef, useState } from "react";
import { z } from "zod";
import {
  ApiError, gameSchema, normalize, pendingSchema, peopleSchema, request, statsSchema,
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
  const [imageState, setImageState] = useState<"loading" | "ready" | "error">("loading");
  const [imageRetry, setImageRetry] = useState(0);
  const [preview, setPreview] = useState<"original" | number>(1);
  const submitting = useRef(false);
  const input = useRef<HTMLInputElement>(null);
  const result = useRef<HTMLHeadingElement>(null);
  const preloadedUrls = useRef(new Set<string>());

  async function loadStats() {
    try {
      setStats(await request("/api/stats/me", statsSchema));
      setStatsError("");
    } catch (failure) {
      setStatsError(message(failure));
    }
  }

  async function loadDaily() {
    const next = await request("/api/puzzles/daily", gameSchema);
    setGame(next);
    return next;
  }

  async function refreshProgress() {
    if (game?.mode === "practice" && game.practice_id) {
      setBusy(true);
      setError("");
      try {
        setGame(await request(`/api/practice/${game.practice_id}`, gameSchema));
      } catch (failure) {
        setError(message(failure));
      } finally {
        setBusy(false);
      }
      return;
    }
    await load();
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
          } else if (parsed.data.mode === "daily" && parsed.data.date === nextGame.date) {
            setPending(parsed.data);
            setQuery(parsed.data.guess);
            setNotice("A submission is awaiting confirmation. Retry it safely below.");
          } else {
            sessionStorage.removeItem(PENDING_KEY);
            setPending(null);
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

  const finished = game !== null && game.status !== "playing";
  const selectedLevel = useMemo(() => {
    if (!game) return null;
    if (preview === "original") return null;
    return game.levels.find((level) => level.level === preview) ?? game.level;
  }, [game, preview]);
  const imageUrl = !game ? "" : (preview === "original" && finished && game.original_image_url ? game.original_image_url : (selectedLevel?.url ?? game.level.url));
  const imageLevel = selectedLevel?.level ?? game?.level.level ?? 1;

  useEffect(() => {
    if (!game) return;
    if (game.status === "playing") setPreview(game.level.level);
    else setPreview(game.original_image_url ? "original" : game.level.level);
  }, [game?.puzzle_id, game?.practice_id, game?.status, game?.level.level, game?.original_image_url]);

  useEffect(() => {
    setImageState("loading");
    setImageRetry(0);
  }, [imageUrl]);

  useEffect(() => {
    if (!game) return;
    const urls = game.levels.map((level) => level.url);
    if (game.original_image_url) urls.push(game.original_image_url);
    for (const url of urls) {
      if (preloadedUrls.current.has(url)) continue;
      preloadedUrls.current.add(url);
      const image = new Image();
      image.src = url;
    }
  }, [game?.puzzle_id, game?.practice_id, game?.original_image_url, game?.levels]);

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
    const attempt = pending ?? (game.mode === "daily" ? {
      mode: "daily" as const, date: game.date, guess, request_id: crypto.randomUUID(),
    } : {
      mode: "practice" as const, practice_id: game.practice_id ?? "", guess, request_id: crypto.randomUUID(),
    });
    if (attempt.mode === "practice" && !attempt.practice_id) {
      setError("Practice game is unavailable. Start a new random face.");
      setBusy(false);
      submitting.current = false;
      return;
    }
    remember(attempt);
    try {
      const path = attempt.mode === "daily" ?
        `/api/puzzles/${attempt.date}/guesses` :
        `/api/practice/${attempt.practice_id}/guesses`;
      const next = await request(path, gameSchema, {
        guess: attempt.guess, request_id: attempt.request_id,
      });
      setGame(next);
      remember(null);
      setQuery("");
      setNotice(next.status === "playing" ? "Not quite. A more detailed image is now revealed." :
        next.status === "won" ? (next.mode === "daily" ? "That's right! You solved today's Pixle." : "Nice guess! Practice face solved.") :
          (next.mode === "daily" ? "Today's puzzle is finished." : "Practice round finished."));
      if (next.status !== "playing" && next.mode === "daily") void loadStats();
      else input.current?.focus();
    } catch (failure) {
      if (failure instanceof ApiError && [401, 409, 422].includes(failure.status)) remember(null);
      setError(message(failure));
    } finally {
      setBusy(false);
      submitting.current = false;
    }
  }

  async function startPractice(mode: "random" | "mosaic") {
    setBusy(true);
    setError("");
    setNotice("");
    setQuery("");
    remember(null);
    try {
      const next = await request(
        mode === "random" ? "/api/practice/random" : "/api/practice/mosaic",
        gameSchema, {}
      );
      setGame(next);
      setNotice(mode === "random" ?
        "Practice mode started (pixel style). These rounds are unscored." :
        "Practice mode started (random mosaic style). These rounds are unscored.");
    } catch (failure) {
      setError(message(failure));
    } finally {
      setBusy(false);
    }
  }

  async function skipReveal() {
    if (!game || finished || busy) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    setOpen(false);
    try {
      const requestId = crypto.randomUUID();
      if (game.mode === "practice" && !game.practice_id) {
        throw new Error("Practice game is unavailable. Start a new random face.");
      }
      const path = game.mode === "daily" ? `/api/puzzles/${game.date}/skip` : `/api/practice/${game.practice_id}/skip`;
      const next = await request(path, gameSchema, { request_id: requestId });
      setGame(next);
      setQuery("");
      setNotice(next.status === "playing" ? "Skipped. A more detailed image is now revealed." :
        next.mode === "daily" ? "Today's puzzle is finished." : "Practice round finished.");
      if (next.status !== "playing" && next.mode === "daily") void loadStats();
      else input.current?.focus();
    } catch (failure) {
      setError(message(failure));
    } finally {
      setBusy(false);
      submitting.current = false;
    }
  }

  const matches = query.trim() ? people.filter((person) =>
    normalize(person.name).includes(normalize(query)) &&
    !game?.guesses.some((guessItem) => normalize(guessItem.name) === normalize(person.name))
  ).slice(0, 7) : [];
  const canGuess = game !== null && !finished && !loading && !busy;

  return <div className="shell">
    <header className="masthead">
      <a className="brand" href="/" aria-label="Pixle home"><span className="brand-mark" aria-hidden="true">P</span>pixle<span className="brand-dot">.</span></a>
      <div className="masthead-actions">
        <span className="edition">A new face, every day</span>
        <div className="quick-actions">
          <button className="top-action" disabled={busy || loading} onClick={() => void startPractice("random")}>
            Pixel practice
          </button>
          <button className="top-action" disabled={busy || loading} onClick={() => void startPractice("mosaic")}>
            Mosaic practice
          </button>
          <a className="github-link" href="https://github.com/bluesbird/Pixle" target="_blank" rel="noreferrer">
            GitHub <span aria-hidden="true">&#8599;</span>
          </a>
        </div>
      </div>
    </header>
    <main>
      <section className="intro" aria-labelledby="title">
        <p className="eyebrow">THE DAILY PHOTO MOSAIC</p>
        <h1 id="title">Familiar faces.<br /><span>One hidden identity.</span></h1>
      </section>

      <div className="game-layout">
        <section className="mosaic-card" aria-label={game?.mode === "practice" ? "Practice face" : "Daily mosaic"}>
          <div className="card-heading">
            <span>{!game || game.mode === "daily" ? <time dateTime={game?.date ?? ""}>{game ? new Date(`${game.date}T12:00:00Z`).toLocaleDateString("en", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }) : "Today's puzzle"}</time> : "Practice mode"}</span>
            <span className="live-tag">{game?.mode === "practice" ? "PRACTICE / UNSCORED" : "DAILY / UTC"}</span>
          </div>
          <div className="mosaic-frame" aria-busy={loading || imageState === "loading"}>
            {game ? <>
              <img key={`${imageUrl}-${imageRetry}`}
                src={`${imageUrl}${imageRetry ? `?retry=${imageRetry}` : ""}`}
                alt={preview === "original" ? "Original portrait revealed after finishing the game." : `Photo reveal, detail level ${imageLevel} of ${game.max_attempts}. Identify the hidden person.`}
                width={selectedLevel?.width ?? game.level.width} height={selectedLevel?.height ?? game.level.height}
                onLoad={() => setImageState("ready")} onError={() => setImageState("error")} />
              {imageState === "loading" && <div className="image-overlay" role="status">Loading image...</div>}
              {imageState === "error" && <div className="image-overlay">
                <p role="alert">The image could not load.</p>
                <button onClick={() => { setImageState("loading"); setImageRetry((value) => value + 1); }}>Retry image</button>
              </div>}
            </> : <div className="placeholder" role="status">{loading ? "Preparing today's mosaic..." : "Your image will appear here."}</div>}
          </div>
          <div className="mosaic-caption">
            <span>{game ? (preview === "original" ? "Original portrait" : `Detail ${imageLevel} / ${game.max_attempts}`) : "Made of familiar faces"}</span>
            {game && <a href={game.credits_url} target="_blank" rel="noreferrer">Photo credits <span aria-hidden="true">&#8599;</span></a>}
          </div>
        </section>

        <section className="play-panel" aria-label="Guess the person">
          {loading && <p role="status">Loading your saved progress...</p>}
          {error && <div className="error-box" role="alert"><p>{error}</p>
            {!pending && <button className="text-button" disabled={busy || loading} onClick={() => void refreshProgress()}>Refresh progress</button>}
          </div>}
          {storageError && <p className="warning" role="alert">{storageError}</p>}
          <p className="feedback" role="status" aria-live="polite">{notice}</p>
          {game && <>
            <p className="eyebrow">{finished ? "THE BIG PICTURE" : `GUESS ${Math.min(game.attempts + 1, game.max_attempts)} OF ${game.max_attempts}`}</p>
            <div className={`progress${finished ? " finished" : ""}`} aria-label={`${game.attempts} of ${game.max_attempts} guesses used`}>
              {Array.from({ length: game.max_attempts }, (_, index) => {
                const className = index < game.attempts ? (game.guesses[index]?.correct ? "correct" : "used") : "";
                return finished ?
                  <button key={index} type="button" className={className}
                    onClick={() => setPreview(index + 1)}
                    aria-label={`Show detail level ${index + 1}`}
                    aria-pressed={preview === index + 1} /> :
                  <span key={index} className={className} />;
              })}
            </div>
            {finished && game.original_image_url && <button className="text-button"
              onClick={() => setPreview("original")} aria-pressed={preview === "original"}>
              Show original portrait
            </button>}
            {finished ? <div className="result">
              <h2 ref={result} tabIndex={-1}>{game.status === "won" ? "You saw it." : game.mode === "daily" ? "Meet today's face." : "Practice finished."}</h2>
              <p className="answer">{game.answer}</p>
              {game.mode === "daily" && <p><strong className="score">{game.score}</strong> points <span className="muted">/ {game.max_attempts * 100}</span></p>}
              <p>{game.status === "won" ?
                `Solved in ${game.attempts} ${game.attempts === 1 ? "guess" : "guesses"}.` :
                game.mode === "daily" ? "A fresh challenge arrives at midnight UTC." : "Start another random face to keep practicing."}</p>
              {game.mode === "practice" && <button className="primary" disabled={busy} onClick={() => void startPractice("random")}>
                Play another random face <span aria-hidden="true">&#8594;</span>
              </button>}
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
              <div className="turn-actions">
                <button type="button" disabled={!canGuess || pending !== null} onClick={() => void skipReveal()}>
                  Skip
                </button>
                <button className="primary" type="submit" disabled={!canGuess || (!pending && !query.trim())}>
                  {busy ? "Checking..." : pending ? "Retry pending guess" : "Make a guess"} <span aria-hidden="true">&#8594;</span>
                </button>
              </div>
            </form>}
            {pending && finished && <button disabled={busy} onClick={() => void submit()}>Confirm pending submission</button>}
            {game.guesses.length > 0 && <div className="history">
              <h3>Your guesses</h3>
              <ol>{game.guesses.map((guessItem) => <li key={guessItem.attempt}>
                <span className="attempt-number">{guessItem.attempt.toString().padStart(2, "0")}</span>
                <span>{guessItem.name}</span><span className={guessItem.correct ? "good" : "muted"}>{guessItem.correct ? "Correct" : "Not quite"}</span>
              </li>)}</ol>
            </div>}
          </>}
          {!game && !loading && !error && <p>No puzzle is available yet.</p>}
          <details className="how-to">
            <summary>How to play</summary>
            <p>Find the famous person hidden in the puzzle. Choose a name and make a guess.
              A wrong guess unlocks a clearer image. Fewer guesses mean more points in daily mode.</p>
            <p>One puzzle worldwide, resetting at midnight UTC. Random practice rounds are separate and unscored.</p>
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
