import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent, DataZoomComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { ApiError, apiRequest } from "./api";

echarts.use([LineChart, GridComponent, TooltipComponent, DataZoomComponent, CanvasRenderer]);

type NumericPoint = { timestamp: string; values: Record<string, number> };
type Finding = {
  column: string;
  unit: string;
  baseline_mean: number;
  comparison_mean: number;
  absolute_change: number;
  percent_change: number;
  anomaly_candidate: boolean;
};
type Analysis = Record<string, unknown> & {
  anomaly_prediction?: unknown;
  possible_causes?: unknown;
  effects?: unknown;
  cost?: unknown;
  suggestions?: unknown;
  alternatives?: unknown;
};

function parseCsv(text: string): { headers: string[]; rows: string[][]; error?: string } {
  const lines = text.replace(/^\uFEFF/, "").replace(/\r/g, "").split("\n").filter((line) => line.trim());
  if (lines.length < 2) return { headers: [], rows: [], error: "CSV must contain a header and at least two data rows." };
  const headers = lines[0].split(",").map((value) => value.trim());
  if (headers.some((header) => !header) || new Set(headers).size !== headers.length) {
    return { headers: [], rows: [], error: "CSV headers must be non-empty and unique." };
  }
  const rows = lines.slice(1).map((line) => line.split(",").map((value) => value.trim()));
  if (rows.some((row) => row.length !== headers.length)) {
    return { headers, rows: [], error: "A CSV row has a different column count than its header." };
  }
  return { headers, rows };
}

function mean(values: number[]): number {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;
}

function findFindings(headers: string[], rows: string[][]): { points: NumericPoint[]; findings: Finding[] } {
  const timestampIndex = headers.findIndex((header) => /timestamp|time|date/i.test(header));
  const numericIndices = headers.map((header, index) => ({ header, index })).filter(({ index }) =>
    index !== timestampIndex && rows.slice(0, 1000).some((row) => Number.isFinite(Number(row[index]))) && rows.slice(0, 1000).every((row) => row[index] === "" || Number.isFinite(Number(row[index]))),
  );
  const points = rows.slice(-1000).map((row) => {
    const timestamp = timestampIndex >= 0 ? row[timestampIndex] : "";
    const values: Record<string, number> = {};
    numericIndices.forEach(({ header, index }) => {
      const value = Number(row[index]);
      if (Number.isFinite(value)) values[header] = value;
    });
    return { timestamp, values };
  }).filter((point) => Object.keys(point.values).length > 0);

  const findings = numericIndices.map(({ header }) => {
    const values = points.map((point) => point.values[header]).filter((value) => Number.isFinite(value));
    const split = Math.max(1, Math.floor(values.length * 0.7));
    const baseline = values.slice(0, split);
    const comparison = values.slice(split);
    const baselineMean = mean(baseline);
    const comparisonMean = mean(comparison.length ? comparison : baseline);
    const absoluteChange = comparisonMean - baselineMean;
    const percentChange = baselineMean !== 0 ? (absoluteChange / Math.abs(baselineMean)) * 100 : 0;
    const variance = baseline.length > 1 ? baseline.reduce((sum, value) => sum + Math.pow(value - baselineMean, 2), 0) / baseline.length : 0;
    const baselineStd = Math.sqrt(variance);
    const anomalyCandidate = comparison.length >= 3 && Math.abs(percentChange) >= 10 &&
      (Math.abs(absoluteChange) >= Math.max(baselineStd * 3, Math.abs(baselineMean) * 0.15));
    return {
      column: header,
      unit: "CSV unit · verify against sensor definition",
      baseline_mean: Number(baselineMean.toFixed(4)),
      comparison_mean: Number(comparisonMean.toFixed(4)),
      absolute_change: Number(absoluteChange.toFixed(4)),
      percent_change: Number(percentChange.toFixed(2)),
      anomaly_candidate: anomalyCandidate,
    };
  });
  return { points, findings };
}

function AnalysisCard({ title, value }: { title: string; value: unknown }) {
  return (
    <article className="border border-rule bg-white/40 p-4">
      <p className="font-mono text-xs tracking-widest text-accent">{title}</p>
      <pre className="mt-3 whitespace-pre-wrap text-sm leading-relaxed">{typeof value === "string" ? value : JSON.stringify(value ?? "unknown", null, 2)}</pre>
    </article>
  );
}

export function Esp32AnomalyDashboard() {
  const chartRef = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const [fileName, setFileName] = useState("");
  const [points, setPoints] = useState<NumericPoint[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);

  useEffect(() => {
    if (!chartRef.current || !points.length) return;
    chart.current?.dispose();
    chart.current = echarts.init(chartRef.current, undefined, { renderer: "canvas" });
    const columns = Array.from(new Set(points.flatMap((point) => Object.keys(point.values))));
    chart.current.setOption({
      animation: false,
      grid: { left: 48, right: 20, top: 34, bottom: 48 },
      tooltip: { trigger: "axis" },
      dataZoom: [{ type: "inside" }],
      legend: { data: columns },
      xAxis: { type: "category", data: points.map((point, index) => point.timestamp || String(index + 1)) },
      yAxis: { type: "value", scale: true },
      series: columns.map((column) => ({
        name: column,
        type: "line",
        showSymbol: points.length <= 300,
        data: points.map((point) => point.values[column] ?? null),
        connectNulls: false,
      })),
    });
    const resize = () => chart.current?.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.current?.dispose();
      chart.current = null;
    };
  }, [points]);

  async function loadCsv(selected: File | undefined) {
    if (!selected) return;
    setError("");
    setStatus("");
    setAnalysis(null);
    try {
      const parsed = parseCsv(await selected.text());
      if (parsed.error) throw new Error(parsed.error);
      const result = findFindings(parsed.headers, parsed.rows);
      if (!result.points.length) throw new Error("No numeric measurement columns were found.");
      setFileName(selected.name);
      setPoints(result.points);
      setFindings(result.findings);
    } catch (reason) {
      setFileName("");
      setPoints([]);
      setFindings([]);
      setError(reason instanceof Error ? reason.message : "The CSV could not be read.");
    }
  }

  async function analyzeWithGemini() {
    if (!findings.length) return;
    setBusy(true);
    setError("");
    setStatus("ANALYZING WITH GEMINI");
    try {
      const summary = {
        dataset: fileName || "ESP32 CSV upload",
        data_type: "observed",
        row_count: points.length,
        anomaly_findings: findings,
        interpretation: "Numerical findings are pattern candidates from the first 70% compared with the final 30%; not confirmed fault labels.",
        cost: { time: "unknown", money: "unknown", downtime_hours: null, monetary_rates: null },
      };
      const result = await apiRequest<{ status: string; result: Analysis | null; error: { message?: string } | null }>(
        "/historical-replay/analysis",
        { method: "POST", body: JSON.stringify({ evidence_summary: summary }) },
      );
      setStatus(result.status.toUpperCase());
      setAnalysis(result.result);
      if (!result.result) setError(result.error?.message ?? "Gemini did not return an analysis.");
    } catch (reason) {
      setStatus("UNAVAILABLE");
      setError(reason instanceof ApiError ? reason.message : "Gemini analysis is unavailable.");
    } finally {
      setBusy(false);
    }
  }

  const anomalyCount = findings.filter((finding) => finding.anomaly_candidate).length;

  return (
    <section className="border border-rule bg-white/40 p-6" aria-labelledby="esp32-anomaly-title">
      <p className="font-mono text-xs tracking-widest text-ink/60">ESP32 CSV · OBSERVED DATA · GEMINI ANALYSIS</p>
      <h2 className="mt-2 text-2xl font-semibold" id="esp32-anomaly-title">Pattern and anomaly dashboard</h2>
      <label className="form-field mt-5 max-w-xl">
        <span>Upload ESP32 CSV</span>
        <input accept=".csv,text/csv" disabled={busy} onChange={(event) => void loadCsv(event.currentTarget.files?.[0])} type="file" />
      </label>
      {fileName && <p className="mt-3 text-sm text-ink/65">{fileName} · {points.length} numeric rows loaded</p>}
      {findings.length > 0 && (
        <>
          <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <article className="border border-rule p-4"><p className="font-mono text-xs text-ink/60">NUMERIC COLUMNS</p><p className="mt-2 text-2xl font-semibold">{findings.length}</p></article>
            <article className="border border-rule p-4"><p className="font-mono text-xs text-ink/60">ANOMALY CANDIDATES</p><p className="mt-2 text-2xl font-semibold text-accent">{anomalyCount}</p></article>
            <article className="border border-rule p-4"><p className="font-mono text-xs text-ink/60">DATA TYPE</p><p className="mt-2 font-semibold">MEASURED</p></article>
            <article className="border border-rule p-4"><p className="font-mono text-xs text-ink/60">GEMINI STATUS</p><p className="mt-2 font-semibold">{status || "READY"}</p></article>
          </div>
          <div ref={chartRef} className="mt-5 h-[360px] w-full border border-rule" aria-label="ESP32 numeric CSV chart" />
          <div className="mt-5 overflow-x-auto border border-rule">
            <table className="w-full text-left text-sm">
              <thead><tr className="border-b border-rule"><th className="p-3">Column</th><th className="p-3">Baseline mean</th><th className="p-3">Final 30% mean</th><th className="p-3">Change</th><th className="p-3">Result</th></tr></thead>
              <tbody>{findings.map((finding) => (
                <tr className="border-b border-rule" key={finding.column}><td className="p-3 font-semibold">{finding.column}</td><td className="p-3">{finding.baseline_mean}</td><td className="p-3">{finding.comparison_mean}</td><td className="p-3">{finding.percent_change}%</td><td className={`p-3 font-semibold ${finding.anomaly_candidate ? "text-red-800" : ""}`}>{finding.anomaly_candidate ? "ANOMALY CANDIDATE" : "NO SIGNIFICANT CHANGE"}</td></tr>
              ))}</tbody>
            </table>
          </div>
          <button className="action-button mt-5" disabled={busy} onClick={() => void analyzeWithGemini()} type="button">{busy ? "ANALYZING…" : "ANALYZE FIVE TASKS WITH GEMINI"}</button>
        </>
      )}
      {analysis && (
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <AnalysisCard title="1 · ANOMALY PREDICTION" value={analysis.anomaly_prediction} />
          <AnalysisCard title="2 · POSSIBLE CAUSES" value={analysis.possible_causes} />
          <AnalysisCard title="3 · COST" value={analysis.cost} />
          <AnalysisCard title="4 · EFFECTS" value={analysis.effects} />
          <AnalysisCard title="5 · SUGGESTIONS" value={analysis.suggestions} />
          <AnalysisCard title="6 · ALTERNATIVES" value={analysis.alternatives} />
        </div>
      )}
      {error && <p className="mt-5 border-l-2 border-red-700 pl-4 text-sm text-red-800" role="alert">{error}</p>}
    </section>
  );
}
