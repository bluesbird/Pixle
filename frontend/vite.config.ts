import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig({
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
  plugins: [react(), {
    name: "local-public-puzzles",
    configureServer(server) {
      // Only public mosaics are available here, never private answers or portraits.
      server.middlewares.use("/puzzles", async (request, response, next) => {
        const { createReadStream } = await import("node:fs");
        const { stat } = await import("node:fs/promises");
        const { resolve, sep } = await import("node:path");
        const root = fileURLToPath(new URL("../puzzles/public", import.meta.url));
        let relative: string;
        try {
          relative = decodeURIComponent((request.url ?? "/").split("?")[0]);
        } catch {
          response.statusCode = 400;
          response.end();
          return;
        }
        const path = resolve(root, "." + relative);
        if (!path.startsWith(root + sep)) {
          response.statusCode = 404;
          response.end();
          return;
        }
        try {
          if (!(await stat(path)).isFile()) return next();
          response.setHeader("Content-Type", path.endsWith(".jpg") ? "image/jpeg" :
            path.endsWith(".json") ? "application/json" : "text/plain; charset=utf-8");
          const stream = createReadStream(path);
          stream.on("error", (error) => response.destroy(error));
          stream.pipe(response);
        } catch (error) {
          if (error instanceof Error && "code" in error && error.code === "ENOENT") return next();
          next(error);
        }
      });
    },
  }],
});
