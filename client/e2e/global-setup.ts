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

/**
 * How many single-use session sets to mint.
 *
 * One per test that destroys a session: the sign-out test in `auth.spec.ts` and
 * the CSRF happy path in `security.spec.ts`, plus one in hand.
 */
export const SPARE_SESSION_COUNT = 3;

export function sparePath(index: number): string {
  return join(__dirname, ".auth", `spare-${index}.json`);
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

  /*
   * Block on the database, not on "not perfectly healthy".
   *
   * The message here has always said that Redis being down degrades rather
   * than blocks, and the check did not agree with it: any status other than
   * "ready" stopped the run, and a Redis outage reports "degraded". So the
   * one scenario the suite most wants to exercise -- the application running
   * with its cache gone -- was the one it refused to start for.
   *
   * The database is different. Every data assertion in the suite reads real
   * rows, so without PostgreSQL the run would fail everywhere at once and
   * report nothing useful.
   */
  const database = body.data.dependencies.find((dependency) => dependency.name === "database");
  if (!database?.healthy) {
    throw new Error(
      `The backend is "${body.data.status}" and the database is unreachable.` +
        `  The suite asserts against real rows, so it cannot run without it.`,
    );
  }
  if (unhealthy.length > 0) {
    process.stdout.write(
      `[global-setup] backend is "${body.data.status}"; degraded: ` +
        `${unhealthy.map((dependency) => dependency.name).join(", ")}. Continuing.\n`,
    );
  }

  const pythonPath = existsSync(PYTHON) ? PYTHON : "python";
  try {
    const output = execFileSync(pythonPath, ["-m", "tools.mint_test_sessions", SESSIONS_PATH], {
      cwd: SERVER_DIR,
      encoding: "utf8",
    });

    /*
     * Spare, single-use session sets for the tests that destroy a session.
     *
     * Signing out revokes a token for good, so a test that signs out cannot use
     * the shared pool -- see `signInDisposable` in `fixtures.ts`. Those spares
     * are minted here rather than mid-run for one reason: minting reaches the
     * database, and doing that from inside a test makes every such test share
     * the network's luck. A DNS blip on this machine failed one of them with
     * `getaddrinfo failed` in the middle of a CSRF assertion, which reads as a
     * CSRF defect and is nothing of the sort.
     *
     * Doing it here concentrates the network dependency at one labelled point:
     * if it fails, the run stops before a single test has claimed anything.
     */
    for (let index = 0; index < SPARE_SESSION_COUNT; index += 1) {
      execFileSync(pythonPath, ["-m", "tools.mint_test_sessions", sparePath(index)], {
        cwd: SERVER_DIR,
        encoding: "utf8",
      });
    }
    // Prints role names only; the tool never writes tokens to stdout.
    process.stdout.write(`[global-setup] ${output.trim()}\n`);
  } catch (error) {
    throw new Error(
      `Could not mint test sessions.\n  ${(error as Error).message}\n` +
        `  Has the database been seeded? cd server && python -m app.db.seed`,
    );
  }
}
