import { useEffect, useMemo, useRef, useState } from "react";
import { z } from "zod";
import {
  ApiError, gameSchema, normalize, pendingSchema, peopleSchema, request, statsSchema,
  type Game, type Pending, type Person, type Stats,
} from "./api";

const PENDING_KEY = "pixle.pending.v1";
const EXAMPLE_PUZZLE_ID = "1d79c84a0dd89e24dd601cfe";
const HOWTO_SEEN_KEY = "pixle.howto.seen.v1";

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
  const [clock, setClock] = useState(() => Date.now());
  const [panelMinHeight, setPanelMinHeight] = useState<number | null>(null);
  const [showHowTo, setShowHowTo] = useState(false);
  const submitting = useRef(false);
  const input = useRef<HTMLInputElement>(null);
  const result = useRef<HTMLHeadingElement>(null);
  const preloadedUrls = useRef(new Set<string>());
  const mosaicCard = useRef<HTMLElement>(null);
  const mosaicImage = useRef<HTMLImageElement>(null);
  const touchSuggestionStart = useRef<{ x: number; y: number } | null>(null);
  const shouldAutoFocusGuess = useMemo(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return true;
    return window.matchMedia("(hover: hover) and (pointer: fine)").matches;
  }, []);

  function focusGuessField() {
    if (!shouldAutoFocusGuess) return;
    input.current?.focus();
  }

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
      const catalogue = await request("/api/people", peopleSchema);
      setPeople(catalogue);
      let nextGame: Game | null = null;
      try {
        nextGame = await request("/api/puzzles/daily", gameSchema);
      } catch (failure) {
        if (!(failure instanceof ApiError && failure.status === 404)) throw failure;
        setGame(null);
        setError(message(failure));
      }
      if (nextGame) setGame(nextGame);
      try {
        const saved = sessionStorage.getItem(PENDING_KEY);
        if (saved) {
          const parsed = pendingSchema.safeParse(JSON.parse(saved));
          if (!parsed.success) {
            sessionStorage.removeItem(PENDING_KEY);
            setStorageError("An unreadable saved submission was removed. Server progress is unchanged.");
          } else if (nextGame && parsed.data.mode === "daily" && parsed.data.date === nextGame.date) {
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
    const image = mosaicImage.current;
    if (!image || imageState !== "loading") return;
    if (image.complete) {
      setImageState(image.naturalWidth > 0 ? "ready" : "error");
    }
  }, [imageUrl, imageRetry, imageState]);

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

  useEffect(() => {
    if (!game || game.status !== "playing" || showHowTo) return;
    requestAnimationFrame(() => focusGuessField());
  }, [game?.puzzle_id, game?.practice_id, game?.status, game?.attempts, showHowTo, shouldAutoFocusGuess]);

  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    try {
      if (localStorage.getItem(HOWTO_SEEN_KEY) !== "1") {
        setShowHowTo(true);
        localStorage.setItem(HOWTO_SEEN_KEY, "1");
      }
    } catch {
      setShowHowTo(true);
    }
  }, []);

  useEffect(() => {
    const card = mosaicCard.current;
    if (!card) return;
    const syncHeight = () => {
      if (window.innerWidth <= 760) {
        setPanelMinHeight(null);
        return;
      }
      setPanelMinHeight(Math.round(card.getBoundingClientRect().height));
    };
    syncHeight();
    const observer = new ResizeObserver(syncHeight);
    observer.observe(card);
    window.addEventListener("resize", syncHeight);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", syncHeight);
    };
  }, []);

  function remember(value: Pending | null) {
    setPending(value);
    try {
      if (value) sessionStorage.setItem(PENDING_KEY, JSON.stringify(value));
      else sessionStorage.removeItem(PENDING_KEY);
    } catch {
      setStorageError("Browser storage is unavailable. Keep this tab open while retrying a submission.");
    }
  }

  async function submit(guessOverride?: string) {
    if (!game || submitting.current || loading) return;
    const guess = (guessOverride ?? query).trim();
    if (!pending && !normalize(guess)) {
      setError("Enter a person's name first.");
      focusGuessField();
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
      setNotice("");
      if (next.status !== "playing" && next.mode === "daily") void loadStats();
      else focusGuessField();
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
      setNotice("");
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
      setNotice("");
      if (next.status !== "playing" && next.mode === "daily") void loadStats();
      else focusGuessField();
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
  const currentPracticeMode = game?.mode === "practice" && game.puzzle_id.startsWith("practice-") ? "random" : "mosaic";
  const nextPuzzleCountdown = useMemo(() => {
    const now = new Date(clock);
    const nextUtcMidnight = Date.UTC(
      now.getUTCFullYear(),
      now.getUTCMonth(),
      now.getUTCDate() + 1,
      0,
      0,
      0,
      0,
    );
    const remaining = Math.max(0, Math.floor((nextUtcMidnight - clock) / 1000));
    const hours = Math.floor(remaining / 3600).toString().padStart(2, "0");
    const minutes = Math.floor((remaining % 3600) / 60).toString().padStart(2, "0");
    const seconds = (remaining % 60).toString().padStart(2, "0");
    return `${hours}:${minutes}:${seconds}`;
  }, [clock]);

  return <div className="shell">
    <header className="masthead">
      <a className="brand" href="/" aria-label="Pixle home">
        <img className="brand-mark" src="/favicon.svg" alt="" aria-hidden="true" />
        pixle
        <span className="brand-dot">.</span>
      </a>
      <div className="masthead-actions">
        <div className="quick-actions">
          <button className="top-action" disabled={busy || loading} onClick={() => void startPractice("random")}>
            Pixle practice
          </button>
          <button className="top-action" disabled={busy || loading} onClick={() => void startPractice("mosaic")}>
            Mosaic practice
          </button>
        </div>
        <div className="masthead-utility">
          <button className="top-help-button" type="button" onClick={() => setShowHowTo(true)} aria-label="How to play">
            ?
          </button>
          <a className="github-link" href="https://github.com/bluesbird/Pixle" target="_blank" rel="noreferrer" aria-label="Pixle on GitHub">
            <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
              <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38
              0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52
              -.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.5-1.07-1.78-.2
              -3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82
              .64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12
              .51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93
              -.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
            </svg>
          </a>
        </div>
      </div>
    </header>
    <main>
      <section className="intro" aria-label="Daily photo mosaic">
        <div className="intro-row">
          <p className="eyebrow">The Daily Photo Mosaic</p>
          <div className="intro-utility">
            <button className="top-help-button" type="button" onClick={() => setShowHowTo(true)} aria-label="How to play">
              ?
            </button>
            <a className="github-link" href="https://github.com/bluesbird/Pixle" target="_blank" rel="noreferrer" aria-label="Pixle on GitHub">
              <svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
                <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38
                0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52
                -.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.5-1.07-1.78-.2
                -3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82
                .64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12
                .51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93
                -.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
              </svg>
            </a>
          </div>
        </div>
        <h1 className="hero-title">Guess the famous person.</h1>
      </section>

      <div className="game-layout">
        <section
          ref={mosaicCard}
          className={`mosaic-card${game?.status === "won" ? " won" : game?.status === "lost" ? " lost" : ""}`}
          aria-label={game?.mode === "practice" ? "Practice face" : "Daily mosaic"}
        >
          <div className="card-heading">
            <span>{!game || game.mode === "daily" ? <time dateTime={game?.date ?? ""}>{game ? new Date(`${game.date}T12:00:00Z`).toLocaleDateString("en", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }) : "Today's puzzle"}</time> : "Practice mode"}</span>
            <span className="live-tag">{game?.mode === "practice" ? "PRACTICE / UNSCORED" : "DAILY / UTC"}</span>
          </div>
          <div className="mosaic-frame" aria-busy={loading || imageState === "loading"}>
            {game ? <>
              <img key={`${imageUrl}-${imageRetry}`}
                ref={mosaicImage}
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

        <section className="play-panel" style={panelMinHeight ? { minHeight: `${panelMinHeight}px` } : undefined} aria-label="Guess the person">
          {loading && <p role="status">Loading your saved progress...</p>}
          {error && <div className="error-box" role="alert"><p>{error}</p>
            {!pending && <button className="text-button" disabled={busy || loading} onClick={() => void refreshProgress()}>Refresh progress</button>}
          </div>}
          {storageError && <p className="warning" role="alert">{storageError}</p>}
          <p className="feedback" role="status" aria-live="polite">{notice}</p>
          {game && <>
            {game.mode === "practice" && <p className="eyebrow practice-mode-tag">Practice mode (unscored)</p>}
            {finished && game.original_image_url ? (
              <button className="eyebrow eyebrow-button" onClick={() => setPreview("original")} aria-pressed={preview === "original"}>
                THE BIG PICTURE
              </button>
            ) : (
              <p className="eyebrow">{finished ? "THE BIG PICTURE" : `GUESS ${Math.min(game.attempts + 1, game.max_attempts)} OF ${game.max_attempts}`}</p>
            )}
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
            {finished ? <div className="result">
              <h2 ref={result} tabIndex={-1}>{game.mode === "daily" ? "Meet today's face." : "Meet this face."}</h2>
              <h3 className="answer">{game.answer}</h3>
              {game.mode === "daily" && <p><strong className="score">{game.score}</strong> points <span className="muted">/ {game.max_attempts * 100}</span>{game.status === "won" ? <span className="muted"> · Solved in {game.attempts} {game.attempts === 1 ? "guess" : "guesses"}.</span> : null}</p>}
              {game.mode === "practice" && <button className="primary primary-compact" disabled={busy} onClick={() => void startPractice(currentPracticeMode)}>
                Play next <span aria-hidden="true">&#8594;</span>
              </button>}
            </div> : <form onSubmit={(event) => { event.preventDefault(); void submit(); }}
              onBlur={(event) => {
                const form = event.currentTarget;
                window.setTimeout(() => {
                  if (!form.contains(document.activeElement)) setOpen(false);
                }, 0);
              }}>
              <h2>Who is it?</h2>
              <div className="suggestions">
                <input ref={input} id="guess" role="combobox" aria-autocomplete="list"
                  aria-label="Your guess"
                  aria-expanded={open && !pending && query.trim().length > 0}
                  aria-controls={open && !pending && query.trim() ? "people-list" : undefined}
                  aria-activedescendant={open && active >= 0 && matches[active] ? `person-${active}` : undefined}
                  autoComplete="off" maxLength={200} placeholder="Your guess..."
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
                      onPointerDown={(event) => {
                        if (event.pointerType === "touch") {
                          touchSuggestionStart.current = { x: event.clientX, y: event.clientY };
                          return;
                        }
                        event.preventDefault();
                        setQuery(person.name);
                        setOpen(false);
                        setActive(-1);
                        void submit(person.name);
                      }}
                      onPointerMove={(event) => {
                        if (event.pointerType !== "touch" || touchSuggestionStart.current === null) return;
                        if (Math.abs(event.clientX - touchSuggestionStart.current.x) > 8 ||
                            Math.abs(event.clientY - touchSuggestionStart.current.y) > 8) {
                          touchSuggestionStart.current = null;
                        }
                      }}
                      onPointerUp={(event) => {
                        if (event.pointerType !== "touch" || touchSuggestionStart.current === null) return;
                        touchSuggestionStart.current = null;
                        setQuery(person.name);
                        setOpen(false);
                        setActive(-1);
                      }}>
                      {person.name}
                    </li>) : <li role="presentation" className="no-match">No matching people. Try another name.</li>}
                </ul>}
              </div>
              <div className="turn-actions">
                <button type="button" disabled={!canGuess || pending !== null} onClick={() => void skipReveal()}>
                  Skip
                </button>
                <button className="primary primary-compact" type="submit" disabled={!canGuess || (!pending && !query.trim())}>
                  {busy ? "Checking..." : pending ? "Retry pending guess" : "Make a guess"} <span aria-hidden="true">&#8594;</span>
                </button>
              </div>
            </form>}
            {pending && finished && <button disabled={busy} onClick={() => void submit()}>Confirm pending submission</button>}
            {game.guesses.length > 0 && <div className="history">
              <h3>Your guesses</h3>
              <ol>{game.guesses.map((guessItem) => <li key={guessItem.attempt}>
                <span className="attempt-number">{guessItem.attempt.toString().padStart(2, "0")}</span>
                <span className={guessItem.correct ? "good-name" : "bad"}>{guessItem.name}</span><span className={guessItem.correct ? "good" : "bad"}>{guessItem.correct ? "Correct" : (guessItem.name === "Skipped" ? "" : "Not quite")}</span>
              </li>)}</ol>
            </div>}
          </>}
          {!game && !loading && !error && <p>No puzzle is available yet.</p>}
          <div className="panel-tail">
            <section className="stats" aria-label="Your statistics">
              <h3>Your daily record</h3>
              {stats ? <dl><div><dt>Played</dt><dd>{stats.played}</dd></div><div><dt>Won</dt><dd>{stats.won}</dd></div><div><dt>Points</dt><dd>{stats.total_score}</dd></div></dl> : !statsError && <p className="muted">Statistics load with your puzzle.</p>}
              {statsError && <div role="alert"><p>{statsError}</p><button className="text-button" onClick={() => void loadStats()}>Retry statistics</button></div>}
            </section>
          </div>
        </section>
      </div>
    </main>
    {showHowTo && <div className="modal-backdrop" role="presentation" onClick={() => setShowHowTo(false)}>
      <section className="howto-modal" role="dialog" aria-modal="true" aria-labelledby="howto-title" onClick={(event) => event.stopPropagation()}>
        <h2 id="howto-title">How to play</h2>
        <p>Guess the famous person. Wrong guesses reveal more detail, and fewer guesses give more points.</p>
        <div className="howto-example" aria-label="Reveal example levels">
          {[1, 3, 5].map((level) => <figure key={level}>
            <img src={`/puzzles/${EXAMPLE_PUZZLE_ID}/level-${level.toString().padStart(2, "0")}.jpg`} alt={`Einstein example level ${level}`} loading="lazy" />
            <figcaption>Level {level}</figcaption>
          </figure>)}
        </div>
        <p className="howto-tip">Tip: Try looking at the image from a little farther away. You might recognize the face more easily!</p>
        <img className="howto-tip-image" src="/how-to-tip.png" alt="Example tip image for stepping farther away." loading="lazy" />
        <div className="howto-actions">
          <button className="top-action" type="button" onClick={() => setShowHowTo(false)}>Got it</button>
        </div>
      </section>
    </div>}
    <footer>
      <span>A new face, every day</span>
      <span className="footer-countdown" role="status" aria-live="polite">Next puzzle: {nextPuzzleCountdown}</span>
    </footer>
  </div>;
}
