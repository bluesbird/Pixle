import { z } from "zod";

const publicPath = z.string().regex(/^\/puzzles\/[a-f0-9]{24}\/(?:level-\d+\.jpg|credits\.md)$/);
export const gameSchema = z.object({
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  puzzle_id: z.string().regex(/^[a-f0-9]{24}$/),
  status: z.enum(["playing", "won", "lost"]),
  attempts: z.number().int().nonnegative(),
  max_attempts: z.number().int().positive(),
  level: z.object({
    level: z.number().int().positive(),
    grid: z.number().int().positive(),
    width: z.number().int().positive(),
    height: z.number().int().positive(),
    url: publicPath,
  }),
  guesses: z.array(z.object({
    attempt: z.number().int().positive(), name: z.string(), correct: z.boolean(),
  })),
  credits_url: publicPath,
  score: z.number().int().nonnegative().optional(),
  answer: z.string().optional(),
});
export type Game = z.infer<typeof gameSchema>;
export const peopleSchema = z.array(z.object({ id: z.string(), name: z.string() }));
export type Person = z.infer<typeof peopleSchema>[number];
export const statsSchema = z.object({
  played: z.number().int().nonnegative(),
  won: z.number().int().nonnegative(),
  total_score: z.number().int().nonnegative(),
});
export type Stats = z.infer<typeof statsSchema>;
export const pendingSchema = z.object({
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  guess: z.string().min(1).max(200),
  request_id: z.string().uuid(),
});
export type Pending = z.infer<typeof pendingSchema>;

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function request<T>(path: string, schema: z.ZodType<T>, body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      credentials: "same-origin",
      ...(body === undefined ? {} : {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
      signal: AbortSignal.timeout(15000),
    });
  } catch {
    throw new ApiError(0, "Connection interrupted. Your progress is safe. Please try again.");
  }
  if (!response.ok) {
    throw new ApiError(response.status,
      response.status === 401 ? "Your session is unavailable. Enable cookies or clear an expired Pixle session." :
      response.status === 404 ? "No puzzle is available for today yet. Please check back soon." :
      response.status === 409 ? "This guess conflicts with your saved game. Refresh your progress before continuing." :
      response.status === 422 ? "Choose a name from the suggestions and try again." :
      "The game service is temporarily unavailable. Please try again.");
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError(502, "The game service returned an unreadable response. Please try again.");
  }
  const parsed = schema.safeParse(payload);
  if (!parsed.success) throw new ApiError(502, "The game service returned unexpected data. Please try again.");
  return parsed.data;
}

export function normalize(value: string) {
  return value.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().replace(/[^\p{L}\p{N}]/gu, "");
}

export function shareText(game: Game) {
  if (game.status === "playing") throw new Error("Finish the puzzle before sharing");
  const blocks = game.guesses.map((guess) => guess.correct ? "\u{1f7e9}" : "\u{1f7e5}").join("");
  return `Pixle ${game.date}\n${game.status === "won" ? game.attempts : "X"}/${game.max_attempts} | ${game.score ?? 0} points\n${blocks}\n${window.location.origin}`;
}
