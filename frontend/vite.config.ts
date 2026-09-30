import path from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const root = path.dirname(fileURLToPath(import.meta.url));

function blockUnsafeFs(): Plugin {
  const blocked = [
    "/proc/",
    "/sys/",
    "/etc/",
    "/.env",
    ".bash_history",
    ".zsh_history",
    ".ash_history",
    ".sh_history",
    "fish_history",
    ".node_repl_history",
    ".psql_history",
    ".mysql_history",
    ".sqlite_history",
    ".rediscli_history",
    ".mongo_history",
    "mountinfo",
  ];
  return {
    name: "block-unsafe-fs",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const raw = req.url || "";
        let decoded = raw;
        try {
          decoded = decodeURIComponent(raw);
        } catch {
          /* keep raw */
        }
        const hit = blocked.some((item) => decoded.includes(item));
        const outside =
          decoded.startsWith("/@fs/") && !decoded.startsWith(`/@fs/${root}`);
        if (hit || outside) {
          res.statusCode = 403;
          res.end("Forbidden");
          return;
        }
        next();
      });
    },
  };
}

export default defineConfig({
  plugins: [blockUnsafeFs(), react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    fs: {
      strict: true,
      allow: [root],
      deny: [".env", ".env.*", "**/.git/**"],
    },
    hmr: {
      overlay: false,
    },
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        timeout: 180_000,
        proxyTimeout: 180_000,
        configure(proxy) {
          proxy.on("error", (_err, _req, res) => {
            if (res && "writeHead" in res && !res.headersSent) {
              res.writeHead(502, { "Content-Type": "application/json" });
              res.end(JSON.stringify({ error: "backend unavailable" }));
            }
          });
        },
      },
    },
  },
});
