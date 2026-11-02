import { useEffect, useState, type FormEvent } from "react";
import { ApiError, apiRequest } from "./api";

type Run = {
  _id?: string;
  run_id: string;
  line_version: number;
  status: "queued" | "running" | "completed" | "failed" | "cancelled" | "limit_exceeded";
  seed: number;
  created_at: string;
  event_count: number;
  event_log_hash: string | null;
  metrics: {
    throughput_per_second: number;
    cycle_completions: Record<string, number>;
    station_utilization: Record<string, number>;
  } | null;
  error: { code: string; message: string } | null;
};

function message(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "The simulation service could not be reached.";
}

export function SimulationRuns() {
  const [lineId, setLineId] = useState("");
  const [version, setVersion] = useState("1");
  const [recipeId, setRecipeId] = useState("");
  const [productId, setProductId] = useState("");
  const [entities, setEntities] = useState("100");
  const [horizon, setHorizon] = useState("3600");
  const [seed, setSeed] = useState("0");
  const [runs, setRuns] = useState<Run[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    setError("");
    try {
      const result = await apiRequest<{ runs: Run[] }>(
        `/simulation/runs${lineId ? `?line_id=${encodeURIComponent(lineId)}` : ""}`,
      );
      setRuns(result.runs);
    } catch (reason) {
      setError(message(reason));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!lineId || !recipeId || !productId) {
      setError("Line ID, recipe ID and product ID are required.");
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await apiRequest<{ run: Run }>(
        `/lines/${encodeURIComponent(lineId)}/versions/${encodeURIComponent(version)}/runs`,
        {
          method: "POST",
          body: JSON.stringify({
            recipe_id: recipeId,
            product_id: productId,
            entity_count: Number(entities),
            simulated_time_seconds: Number(horizon),
            seed: Number(seed),
          }),
        },
      );
      setNotice(`Queued simulation run ${result.run.run_id}.`);
      await load();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  }

  async function cancel(runId: string) {
    setBusy(true);
    setError("");
    try {
      await apiRequest(`/simulation/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
      setNotice(`Cancellation requested for ${runId}.`);
      await load();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  }

  async function retry(runId: string) {
    setBusy(true);
    setError("");
    try {
      await apiRequest(`/simulation/runs/${encodeURIComponent(runId)}/retry`, { method: "POST" });
      setNotice(`Retry queued for ${runId}.`);
      await load();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="border border-rule bg-white/40 p-6" aria-labelledby="simulation-runs-title">
      <p className="font-mono text-xs tracking-widest text-ink/60">SIMULATION · PINNED REPLAY</p>
      <h2 className="mt-2 text-2xl font-semibold" id="simulation-runs-title">Production runs</h2>
      <form className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3" onSubmit={create}>
        <label className="form-field"><span>Line ID</span><input required value={lineId} onChange={(event) => setLineId(event.target.value)} /></label>
        <label className="form-field"><span>Saved version</span><input min="1" required type="number" value={version} onChange={(event) => setVersion(event.target.value)} /></label>
        <label className="form-field"><span>Recipe ID</span><input required value={recipeId} onChange={(event) => setRecipeId(event.target.value)} /></label>
        <label className="form-field"><span>Product ID</span><input required value={productId} onChange={(event) => setProductId(event.target.value)} /></label>
        <label className="form-field"><span>Entities</span><input min="1" max="100000" required type="number" value={entities} onChange={(event) => setEntities(event.target.value)} /></label>
        <label className="form-field"><span>Horizon (seconds)</span><input min="0.001" required type="number" value={horizon} onChange={(event) => setHorizon(event.target.value)} /></label>
        <label className="form-field"><span>Random seed</span><input min="0" max="2147483647" required type="number" value={seed} onChange={(event) => setSeed(event.target.value)} /></label>
        <button className="action-button self-end" disabled={busy} type="submit">{busy ? "QUEUING…" : "CREATE SIMULATION"}</button>
      </form>
      {notice && <p className="mt-4 border-l-2 border-accent pl-4 text-sm" role="status">{notice}</p>}
      {error && <p className="mt-4 border-l-2 border-red-700 pl-4 text-sm text-red-800" role="alert">{error}</p>}
      <div className="mt-6 divide-y divide-rule border-y border-rule">
        {runs.length === 0 && <p className="py-5 text-sm text-ink/65">No simulation runs in this workspace.</p>}
        {runs.map((run) => (
          <article className="py-4" key={run.run_id}>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="font-mono text-xs">RUN {run.run_id.slice(0, 8)} · V{run.line_version} · SEED {run.seed} · {run.status.toUpperCase()}</p>
                <p className="mt-2 text-sm text-ink/65">Events: {run.event_count} · Created: {new Date(run.created_at).toLocaleString()}</p>
                {run.metrics && <p className="mt-2 text-sm">Simulated throughput: {run.metrics.throughput_per_second.toFixed(6)} parts/second · source: simulated</p>}
                {run.error && <p className="mt-2 text-sm text-red-800">{run.error.code}: {run.error.message}</p>}
              </div>
              <div className="flex gap-3">
                {["queued", "running"].includes(run.status) && (
                  <button className="text-link" disabled={busy} onClick={() => void cancel(run.run_id)} type="button">CANCEL</button>
                )}
                {["failed", "cancelled", "limit_exceeded"].includes(run.status) && (
                  <button className="text-link" disabled={busy} onClick={() => void retry(run.run_id)} type="button">RETRY</button>
                )}
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
