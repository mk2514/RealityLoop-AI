import { useEffect, useState, type FormEvent } from "react";
import { ApiError, apiRequest } from "./api";

type Candidate = {
  candidate_id: string;
  candidate_name: string;
  delta_hash: string;
  resolved_snapshot_hash: string;
  kind: "simulated";
  baseline_throughput: { mean: number; min: number; max: number; stddev: number };
  candidate_throughput: { mean: number; min: number; max: number; stddev: number };
  paired_throughput_difference: { mean: number; ci95: number[]; difference_distinguishable: boolean };
  bottleneck_frequency: Record<string, number>;
};

type Comparison = {
  comparison_id: string;
  result_hash: string;
  replication_count: number;
  kind: "simulated";
  candidates: Candidate[];
};

function message(error: unknown): string {
  return error instanceof ApiError ? error.message : "The scenario service could not be reached.";
}

export function ScenarioWorkspace() {
  const [lineId, setLineId] = useState("");
  const [version, setVersion] = useState("1");
  const [recipeId, setRecipeId] = useState("");
  const [productId, setProductId] = useState("");
  const [replications, setReplications] = useState("20");
  const [deltaJson, setDeltaJson] = useState(
    '[{"type":"parallel_equipment","station_id":"","resource_quantity":2}]',
  );
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    setError("");
  }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    setComparison(null);
    try {
      const deltas = JSON.parse(deltaJson) as Array<Record<string, unknown>>;
      const scenarioResult = await apiRequest<{ scenario: { scenario_id: string } }>(
        "/simulation/scenarios",
        {
          method: "POST",
          body: JSON.stringify({
            line_id: lineId,
            line_version: Number(version),
            recipe_id: recipeId,
            product_id: productId,
            entity_count: 100,
            simulated_time_seconds: 3600,
            seed: 42,
            candidates: [{ name: "Candidate 1", deltas }],
          }),
        },
      );
      const comparisonResult = await apiRequest<{ comparison: Comparison }>(
        "/simulation/comparisons",
        {
          method: "POST",
          body: JSON.stringify({
            scenario_id: scenarioResult.scenario.scenario_id,
            replications: Number(replications),
            seed: 42,
          }),
        },
      );
      setComparison(comparisonResult.comparison);
      setNotice("Scenario comparison completed. Results are simulated and must not be read as observed performance.");
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="border border-rule bg-white/40 p-6" aria-labelledby="scenario-title">
      <p className="font-mono text-xs tracking-widest text-ink/60">SIMULATED · CHAOS AND WHAT-IF</p>
      <h2 className="mt-2 text-2xl font-semibold" id="scenario-title">Scenario comparison</h2>
      <p className="mt-3 text-sm text-ink/65">
        Candidate changes are copied from a pinned saved line version. Approval or execution of a scenario sends no machine command.
      </p>
      <form className="mt-5 grid gap-4 sm:grid-cols-2" onSubmit={create}>
        <label className="form-field"><span>Line ID</span><input required value={lineId} onChange={(event) => setLineId(event.target.value)} /></label>
        <label className="form-field"><span>Saved version</span><input min="1" required type="number" value={version} onChange={(event) => setVersion(event.target.value)} /></label>
        <label className="form-field"><span>Recipe ID</span><input required value={recipeId} onChange={(event) => setRecipeId(event.target.value)} /></label>
        <label className="form-field"><span>Product ID</span><input required value={productId} onChange={(event) => setProductId(event.target.value)} /></label>
        <label className="form-field"><span>Paired replications</span><input min="1" max="100" required type="number" value={replications} onChange={(event) => setReplications(event.target.value)} /></label>
        <label className="form-field sm:col-span-2">
          <span>Candidate delta JSON</span>
          <textarea className="min-h-28" value={deltaJson} onChange={(event) => setDeltaJson(event.target.value)} />
        </label>
        <button className="action-button" disabled={busy} type="submit">{busy ? "COMPARING…" : "RUN PAIRED COMPARISON"}</button>
      </form>
      {notice && <p className="mt-4 border-l-2 border-accent pl-3 text-sm" role="status">{notice}</p>}
      {error && <p className="mt-4 border-l-2 border-red-700 pl-3 text-sm text-red-800" role="alert">{error}</p>}
      {comparison && (
        <div className="mt-6 border-t border-rule pt-5">
          <p className="font-mono text-xs">COMPARISON {comparison.comparison_id.slice(0, 8)} · {comparison.replication_count} PAIRED REPLICATIONS</p>
          <p className="mt-2 text-xs text-ink/60">Result hash: {comparison.result_hash}</p>
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            {comparison.candidates.map((candidate) => (
              <article className="border border-rule p-4" key={candidate.candidate_id}>
                <p className="font-semibold">{candidate.candidate_name}</p>
                <p className="mt-2 text-sm">Simulated throughput: {candidate.candidate_throughput.mean.toFixed(6)} parts/second</p>
                <p className="mt-1 text-sm">
                  Paired difference: {candidate.paired_throughput_difference.mean.toFixed(6)} parts/second
                  {candidate.paired_throughput_difference.difference_distinguishable
                    ? ""
                    : " · Difference not distinguishable from noise"}
                </p>
                <p className="mt-1 text-xs text-ink/65">
                  95% CI [{candidate.paired_throughput_difference.ci95[0].toFixed(6)}, {candidate.paired_throughput_difference.ci95[1].toFixed(6)}]
                </p>
                <p className="mt-3 text-xs">
                  Bottleneck frequency: {Object.entries(candidate.bottleneck_frequency).map(([station, frequency]) =>
                    `${station} ${(frequency * 100).toFixed(1)}%`).join(" · ") || "No station identified"}
                </p>
                <p className="mt-3 text-xs text-ink/60">Model-based what-if; association and simulation outputs are not proven causal effects.</p>
              </article>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
