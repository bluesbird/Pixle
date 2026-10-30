import { expect, test, type Page } from "@playwright/test";

const puzzleId = "1d79c84a0dd89e24dd601cfe";
const people = [
  { id: "adele", name: "Adele" },
  { id: "albert-einstein", name: "Albert Einstein" },
  { id: "beyonce", name: "Beyonce" },
  { id: "rihanna", name: "Rihanna" },
  { id: "taylor-swift", name: "Taylor Swift" },
  { id: "tom-hanks", name: "Tom Hanks" },
];
const tinyJpeg = Buffer.from("/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAkGBxAQEBUQEBAVFhUVFRUVFRUVFRUVFRUWFhUXFhUYHSggGBolHRUVITEhJSkrLi4uFx8zODMtNygtLisBCgoKDg0OGhAQGi0fHyUtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLf/AABEIAAEAAQMBIgACEQEDEQH/xAAXAAEAAwAAAAAAAAAAAAAAAAAAAQID/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEAMQAAAB0A//xAAXEAADAQAAAAAAAAAAAAAAAAAAAQIR/9oACAEBAAEFApWf/8QAFBEBAAAAAAAAAAAAAAAAAAAAEP/aAAgBAwEBPwEf/8QAFBEBAAAAAAAAAAAAAAAAAAAAEP/aAAgBAgEBPwEf/8QAFBABAAAAAAAAAAAAAAAAAAAAEP/aAAgBAQAGPwJf/8QAFBABAAAAAAAAAAAAAAAAAAAAEP/aAAgBAQABPyFf/9k=", "base64");

type Submission = { guess: string; request_id: string };

async function mockApi(page: Page, options: { empty?: boolean; commitAndDrop?: boolean } = {}) {
  const guesses: { attempt: number; name: string; correct: boolean }[] = [];
  const requests = new Map<string, string>();
  const practiceRequests = new Map<string, string>();
  const submissions: Submission[] = [];
  const practiceGuesses: { attempt: number; name: string; correct: boolean }[] = [];
  const practiceId = "abcdef0123456789abcdef0123456789";
  const practiceTarget = "tom-hanks";
  let dropped = false;
  let failDaily = false;
  const levels = [8, 12, 24, 48, 96].map((grid, index) => ({
    level: index + 1, grid, width: 768, height: 768, url: `/puzzles/${puzzleId}/level-0${index + 1}.jpg`,
  }));
  const current = () => {
    const won = guesses.at(-1)?.correct ?? false;
    const status = won ? "won" : guesses.length === 5 ? "lost" : "playing";
    const level = Math.min(status === "playing" ? guesses.length + 1 : Math.max(1, guesses.length), 5);
    return {
      date: "2026-10-28", puzzle_id: puzzleId, mode: "daily", status, attempts: guesses.length, max_attempts: 5,
      level: levels[level - 1], levels,
      guesses, credits_url: `/puzzles/${puzzleId}/credits.md`,
      ...(status === "playing" ? {} : {
        answer: "Albert Einstein", score: won ? (6 - guesses.length) * 100 : 0,
        original_image_url: "/api/people/albert-einstein/photo",
      }),
    };
  };
  const practice = () => {
    const won = practiceGuesses.at(-1)?.correct ?? false;
    const status = won ? "won" : practiceGuesses.length === 5 ? "lost" : "playing";
    const level = Math.min(status === "playing" ? practiceGuesses.length + 1 : Math.max(1, practiceGuesses.length), 5);
    const practiceLevels = [8, 12, 24, 48, 96].map((grid, index) => ({
      level: index + 1, grid, width: 768, height: 768, url: `/api/practice/${practiceId}/level-0${index + 1}.jpg`,
    }));
    return {
      date: "2026-10-28", puzzle_id: "practice-abcdef0123456789", mode: "practice",
      practice_id: practiceId, status, attempts: practiceGuesses.length, max_attempts: 5,
      level: practiceLevels[level - 1], levels: practiceLevels, guesses: practiceGuesses, credits_url: "/api/people",
      ...(status === "playing" ? {} : { answer: "Tom Hanks", original_image_url: `/api/people/${practiceTarget}/photo` }),
    };
  };
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/session") return route.fulfill({ json: { status: "ready" } });
    if (url.pathname.startsWith(`/api/practice/${practiceId}/level-`)) {
      return route.fulfill({ status: 200, body: tinyJpeg, contentType: "image/jpeg" });
    }
    if (url.pathname.startsWith("/api/people/") && url.pathname.endsWith("/photo")) {
      return route.fulfill({ status: 200, body: tinyJpeg, contentType: "image/jpeg" });
    }
    if (url.pathname === "/api/people") return route.fulfill({ json: people });
    if (url.pathname === "/api/stats/me") {
      return route.fulfill({ json: {
        played: current().status === "playing" ? 0 : 1,
        won: current().status === "won" ? 1 : 0, total_score: current().score ?? 0,
      } });
    }
    if (url.pathname === "/api/puzzles/daily") {
      if (options.empty) return route.fulfill({ status: 404, json: { detail: "No puzzle" } });
      if (failDaily) return route.fulfill({ status: 503, json: { detail: "Unavailable" } });
      return route.fulfill({ json: current() });
    }
    if (url.pathname === "/api/practice/random") {
      practiceGuesses.length = 0;
      practiceRequests.clear();
      return route.fulfill({ json: practice() });
    }
    if (url.pathname === "/api/practice/mosaic") {
      practiceGuesses.length = 0;
      practiceRequests.clear();
      const daily = current();
      return route.fulfill({ json: {
        ...daily,
        mode: "practice",
        practice_id: practiceId,
        status: "playing",
        attempts: 0,
        level: daily.levels[0],
        guesses: [],
        score: undefined,
        answer: undefined,
        original_image_url: undefined,
      } });
    }
    if (url.pathname === `/api/practice/${practiceId}`) return route.fulfill({ json: practice() });
    if (url.pathname.endsWith("/skip")) {
      const body = route.request().postDataJSON() as { request_id: string };
      submissions.push({ guess: "__skip__", request_id: body.request_id });
      if (url.pathname === `/api/practice/${practiceId}/skip`) {
        if (!practiceRequests.has(body.request_id)) {
          practiceGuesses.push({ attempt: practiceGuesses.length + 1, name: "Skipped", correct: false });
          practiceRequests.set(body.request_id, "__skip__");
        }
        return route.fulfill({ json: practice() });
      }
      if (!requests.has(body.request_id)) {
        guesses.push({ attempt: guesses.length + 1, name: "Skipped", correct: false });
        requests.set(body.request_id, "__skip__");
      }
      return route.fulfill({ json: current() });
    }
    if (url.pathname.endsWith("/guesses")) {
      const body = route.request().postDataJSON() as Submission;
      submissions.push(body);
      if (url.pathname === `/api/practice/${practiceId}/guesses`) {
        if (!practiceRequests.has(body.request_id)) {
          const person = people.find((p) => p.name.toLowerCase() === body.guess.toLowerCase());
          if (!person) return route.fulfill({ status: 422, json: { detail: "Unknown" } });
          if (practiceGuesses.some((g) => g.name === person.name)) {
            return route.fulfill({ status: 409, json: { detail: "Duplicate" } });
          }
          practiceGuesses.push({ attempt: practiceGuesses.length + 1, name: person.name, correct: person.id === practiceTarget });
          practiceRequests.set(body.request_id, body.guess);
        }
        return route.fulfill({ json: practice() });
      }
      if (!requests.has(body.request_id)) {
        const person = people.find((p) => p.name.toLowerCase() === body.guess.toLowerCase());
        if (!person) return route.fulfill({ status: 422, json: { detail: "Unknown" } });
        if (guesses.some((g) => g.name === person.name)) {
          return route.fulfill({ status: 409, json: { detail: "Duplicate" } });
        }
        guesses.push({ attempt: guesses.length + 1, name: person.name, correct: person.id === "albert-einstein" });
        requests.set(body.request_id, body.guess);
        if (options.commitAndDrop && !dropped) { dropped = true; return route.abort("failed"); }
      }
      return route.fulfill({ json: current() });
    }
    return route.fulfill({ status: 404 });
  });
  return { submissions, guesses, setFailDaily: (value: boolean) => { failDaily = value; } };
}

async function guess(page: Page, name: string) {
  await page.getByRole("combobox", { name: "Your guess" }).fill(name);
  await page.getByRole("button", { name: "Make a guess" }).click();
}

async function openGame(page: Page) {
  await page.goto("/");
  const gotIt = page.getByRole("button", { name: "Got it" });
  if (await gotIt.isVisible()) {
    await gotIt.click();
  }
}

test("keyboard suggestions, reveals, completion, and reload", async ({ page }) => {
  await mockApi(page);
  await openGame(page);
  await expect(page.getByRole("img", { name: /detail level 1/ })).toBeVisible();
  await page.getByRole("combobox").fill("Tay");
  await page.getByRole("combobox").press("ArrowDown");
  await expect(page.getByRole("option", { name: "Taylor Swift" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("combobox").press("Enter");
  await page.getByRole("button", { name: "Make a guess" }).click();
  await expect(page.getByRole("img", { name: /detail level 2/ })).toBeVisible();
  await expect(page.getByText("Not quite", { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText("Taylor Swift", { exact: true })).toBeVisible();
  await guess(page, "Albert Einstein");
  await expect(page.getByRole("heading", { name: "Meet today's face." })).toBeFocused();
  await expect(page.getByText("400", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Show detail level 1" }).click();
  await expect(page.getByRole("img", { name: /detail level 1/ })).toBeVisible();
  await page.getByRole("button", { name: "THE BIG PICTURE" }).click();
  await expect(page.getByRole("img", { name: /original portrait/i })).toBeVisible();
  await expect(page.getByRole("link", { name: /Photo credits/ })).toHaveAttribute("href", `/puzzles/${puzzleId}/credits.md`);
  await page.reload();
  await expect(page.getByRole("heading", { name: "Meet today's face." })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("committed but interrupted submissions retain UUID across reload", async ({ page }) => {
  const api = await mockApi(page, { commitAndDrop: true });
  await openGame(page);
  await guess(page, "Adele");
  await expect(page.getByRole("alert").filter({ hasText: "Connection interrupted" })).toBeVisible();
  await expect(page.getByRole("combobox")).toHaveValue("Adele");
  await page.reload();
  await page.getByRole("button", { name: "Retry pending guess" }).click();
  await expect(page.getByRole("button", { name: "Make a guess" })).toBeVisible();
  expect(api.submissions).toHaveLength(2);
  expect(api.submissions[0]).toEqual(api.submissions[1]);
  expect(api.guesses).toHaveLength(1);
});

test("five misses end the game and disable further guesses", async ({ page }) => {
  await mockApi(page);
  await openGame(page);
  for (const name of ["Adele", "Beyonce", "Rihanna", "Taylor Swift", "Tom Hanks"]) {
    await guess(page, name);
  }
  await expect(page.getByRole("heading", { name: "Meet today's face." })).toBeVisible();
  await expect(page.getByText("Albert Einstein", { exact: true })).toBeVisible();
  await expect(page.getByRole("combobox")).toHaveCount(0);
  await expect(page.getByText("0", { exact: true }).first()).toBeVisible();
});

test("empty daily puzzle offers a clear retry without invented game state", async ({ page }) => {
  await mockApi(page, { empty: true });
  await openGame(page);
  await expect(page.getByRole("alert")).toContainText("No puzzle is available");
  await expect(page.getByRole("button", { name: "Refresh progress" })).toBeEnabled();
  await expect(page.getByRole("combobox")).toHaveCount(0);
  await page.getByRole("button", { name: "Pixle practice" }).click();
  await page.getByRole("combobox", { name: "Your guess" }).fill("A");
  await expect(page.getByRole("option", { name: "Adele" })).toBeVisible();
});

test("refresh failure preserves the current mosaic and guess history", async ({ page }) => {
  const api = await mockApi(page);
  await openGame(page);
  await guess(page, "Adele");
  await guess(page, "Unknown");
  await expect(page.getByRole("alert")).toContainText("Choose a name");
  api.setFailDaily(true);
  await page.getByRole("button", { name: "Refresh progress" }).click();
  await expect(page.getByRole("alert")).toContainText("temporarily unavailable");
  await expect(page.getByRole("img", { name: /detail level 2/ })).toBeVisible();
  await expect(page.getByText("Adele", { exact: true })).toBeVisible();
  await expect(page.getByRole("combobox")).toHaveValue("Unknown");
});

test("broken mosaic can be retried and no-match suggestions are explained", async ({ page }) => {
  await mockApi(page);
  let fail = true;
  await page.route("**/puzzles/**/level-*.jpg*", (route) => fail ? route.abort() : route.continue());
  await openGame(page);
  await expect(page.getByText("The image could not load.")).toBeVisible();
  fail = false;
  await page.getByRole("button", { name: "Retry image" }).click();
  await expect(page.getByText("The image could not load.")).toHaveCount(0);
  await page.getByRole("combobox").fill("zzzzz");
  await expect(page.getByText("No matching people. Try another name.")).toBeVisible();
  await page.getByRole("combobox").press("Escape");
  await expect(page.getByRole("combobox")).toHaveAttribute("aria-expanded", "false");
});

test("random practice rounds are unscored and replayable", async ({ page }) => {
  await mockApi(page);
  await openGame(page);
  await page.getByRole("button", { name: "Pixle practice" }).click();
  await expect(page.getByText("Practice mode (unscored)")).toBeVisible();
  await expect(page.getByRole("img", { name: /detail level 1/ })).toBeVisible();
  await page.getByRole("button", { name: "Skip" }).click();
  await expect(page.getByText("Skipped", { exact: true })).toBeVisible();
  await expect(page.getByRole("img", { name: /detail level 2/ })).toBeVisible();
  await guess(page, "Tom Hanks");
  await expect(page.getByRole("heading", { name: "Meet this face." })).toBeVisible();
  await expect(page.locator(".result .score")).toHaveCount(0);
  await page.getByRole("button", { name: "Play next" }).click();
  await expect(page.getByText("Practice mode (unscored)")).toBeVisible();
  await expect(page.getByRole("img", { name: /detail level 1/ })).toBeVisible();
});

test("random mosaic practice mode can be started", async ({ page }) => {
  await mockApi(page);
  await openGame(page);
  await page.getByRole("button", { name: "Mosaic practice" }).click();
  await expect(page.getByText("Practice mode (unscored)")).toBeVisible();
  await expect(page.getByText("PRACTICE / UNSCORED")).toBeVisible();
  await expect(page.getByRole("img", { name: /detail level 1/ })).toBeVisible();
});
