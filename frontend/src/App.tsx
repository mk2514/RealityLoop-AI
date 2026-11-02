import { useEffect, useState } from "react";
import { ApiError, getReadiness, type ReadinessResponse } from "./api";
import faviconUrl from "../../dist/assets/favicon.svg";

type ConnectionState =
  | { kind: "loading" }
  | { kind: "readiness"; data: ReadinessResponse }
  | { kind: "unavailable"; message: string; requestId?: string };

export default function App() {
  const [connection, setConnection] = useState<ConnectionState>({ kind: "loading" });

  useEffect(() => {
    let active = true;
    getReadiness()
      .then((data) => {
        if (active) setConnection({ kind: "readiness", data });
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof ApiError) {
          setConnection({
            kind: "unavailable",
            message: error.message,
            requestId: error.requestId,
          });
        } else {
          setConnection({
            kind: "unavailable",
            message: "The application service could not be reached.",
          });
        }
      });

    return () => {
      active = false;
    };
  }, []);

  return (
    <main className="min-h-screen bg-paper text-ink">
      <header className="border-b border-rule">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-5">
          <a
            className="flex items-center gap-3 font-mono text-sm font-semibold tracking-widest focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
            href="/"
          >
            <img alt="" className="h-9 w-9" height="36" src={faviconUrl} width="36" />
            REALITYLOOP AI
          </a>
          <span className="font-mono text-xs tracking-wider text-ink/60">APPLICATION FOUNDATION</span>
        </div>
      </header>

      <section
        aria-labelledby="setup-title"
        className="mx-auto grid min-h-[70vh] max-w-7xl content-center gap-10 px-6 py-16 lg:grid-cols-[1.2fr_0.8fr]"
      >
        <div>
          <p className="font-mono text-xs tracking-[0.2em] text-accent">WORKSPACE / SETUP</p>
          <h1 className="mt-5 max-w-3xl text-4xl font-semibold leading-tight tracking-tight sm:text-6xl">
            Your application foundation is being set up.
          </h1>
          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-ink/75">
            Workspace and factory tools will appear here as they are implemented and connected
            to verified data.
          </p>
          <a
            className="mt-8 inline-flex border border-ink px-5 py-3 font-mono text-sm hover:bg-ink hover:text-paper focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            href="/"
          >
            RETURN TO REALITYLOOP.AI
          </a>
        </div>

        <aside className="self-center border border-rule bg-white/40 p-6 sm:p-8" aria-live="polite">
          <p className="font-mono text-xs tracking-widest">SERVICE READINESS</p>
          {connection.kind === "loading" && (
            <p className="mt-5 text-ink/70">Checking service dependencies…</p>
          )}
          {connection.kind === "readiness" && (
            <>
              <p
                className={`mt-5 font-mono text-sm ${
                  connection.data.status === "ready" ? "text-green-800" : "text-accent"
                }`}
              >
                {connection.data.status === "ready" ? "API READY" : "DEPENDENCIES NOT READY"}
              </p>
              <ul className="mt-4 space-y-2 text-sm text-ink/75">
                {Object.entries(connection.data.dependencies).map(([name, status]) => (
                  <li className="flex justify-between border-t border-rule py-2" key={name}>
                    <span className="capitalize">{name}</span>
                    <span className="font-mono uppercase">{status}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
          {connection.kind === "unavailable" && (
            <>
              <p className="mt-5 font-mono text-sm text-accent">SERVICE NOT READY</p>
              <p className="mt-2 text-sm leading-relaxed text-ink/75">{connection.message}</p>
              {connection.requestId && (
                <p className="mt-3 font-mono text-xs text-ink/60">
                  Request ID: {connection.requestId}
                </p>
              )}
              <button
                className="mt-5 border border-ink px-4 py-2 font-mono text-xs hover:bg-ink hover:text-paper focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                onClick={() => window.location.reload()}
                type="button"
              >
                RETRY CONNECTION
              </button>
            </>
          )}
        </aside>
      </section>
    </main>
  );
}
