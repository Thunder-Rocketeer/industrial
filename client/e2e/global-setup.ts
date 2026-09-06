import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";

/**
 * Mint fresh sessions before the suite runs, and check the stack is actually up.
 *
 * Sessions are minted here rather than by hand because access tokens live
 * fifteen minutes. A suite that reuses a file from an earlier run starts
 * failing partway through with "Sign in" where a dashboard should be — which
 * looks exactly like an authentication bug and is not one. Minting on every run
 * removes that whole class of false failure.
 *
 * The pre-flight checks are equally deliberate. Without them, a stack that is
 * merely not running produces forty confusing assertion failures instead of one
 * clear message.
 */

const SERVER_DIR = resolve(__dirname, "..", "..", "server");
const SESSIONS_PATH = join(__dirname, ".auth", "sessions.json");
const PYTHON = join(SERVER_DIR, ".venv", "Scripts", "python.exe");
const API = "http://localhost:8000/api/v1";
const APP = "http://localhost:3000";

async function requireReachable(label: string, url: string, expected: number[]): Promise<void> {
  let status: number;
  try {
    const response = await fetch(url, { redirect: "manual" });
    status = response.status;
  } catch (error) {
    throw new Error(
      `${label} is not reachable at ${url}.\n` +
        `  ${(error as Error).message}\n` +
        `  Start it before running the browser suite; see playwright.config.ts.`,
    );
  }
  if (!expected.includes(status)) {
    throw new Error(`${label} answered ${status} at ${url}; expected one of ${expected}.`);
  }
}

export default async function globalSetup(): Promise<void> {
  await requireReachable("The backend", `${API}/health`, [200]);
  await requireReachable("The frontend", `${APP}/login`, [200]);

  // Readiness, not just liveness: the suite asserts against real data, so a
  // backend that cannot reach PostgreSQL should stop the run here rather than
  // fail every data assertion separately.
  const ready = await fetch(`${API}/health/ready`);
  const body = (await ready.json()) as {
    data: { status: string; dependencies: { name: string; healthy: boolean }[] };
  };
  const unhealthy = body.data.dependencies.filter((dependency) => !dependency.healthy);
  if (body.data.status !== "ready") {
    throw new Error(
      `The backend is "${body.data.status}". Unhealthy: ` +
        `${unhealthy.map((dependency) => dependency.name).join(", ") || "none"}.\n` +
        `  The suite needs a live database. Redis being down degrades but does not block.`,
    );
  }

  const pythonPath = existsSync(PYTHON) ? PYTHON : "python";
  try {
    const output = execFileSync(
      pythonPath,
      ["-m", "tools.mint_test_sessions", SESSIONS_PATH],
      { cwd: SERVER_DIR, encoding: "utf8" },
    );
    // Prints role names only; the tool never writes tokens to stdout.
    process.stdout.write(`[global-setup] ${output.trim()}\n`);
  } catch (error) {
    throw new Error(
      `Could not mint test sessions.\n  ${(error as Error).message}\n` +
        `  Has the database been seeded? cd server && python -m app.db.seed`,
    );
  }
}
