import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
import { ApiError, apiRequest } from "./api";

type Sensor = { id: string; name: string };
type HierarchyMachine = {
  id: string;
  name: string;
  components: Array<{ sensors: Sensor[] }>;
};
type HierarchyLine = {
  id: string;
  name: string;
  machines: HierarchyMachine[];
};
type HierarchyFactory = {
  id: string;
  name: string;
  lines: HierarchyLine[];
};

export function findHierarchyMachine(factories: HierarchyFactory[], machineId: string): HierarchyMachine | undefined {
  return factories
    .flatMap((factory) => factory.lines)
    .flatMap((line) => line.machines)
    .find((machine) => machine.id === machineId);
}

function csvRows(text: string): { headers: string[]; rows: Array<Record<string, string>> } {
  const lines = text.replace(/\r/g, "").split("\n").filter((line) => line.trim());
  if (!lines.length) return { headers: [], rows: [] };
  const headers = lines[0].split(",").map((header) => header.trim());
  const rows = lines.slice(1).map((line) => {
    const values = line.split(",");
    return Object.fromEntries(headers.map((header, index) => [header, values[index]?.trim() ?? ""]));
  });
  return { headers, rows };
}

export function MetroReplay({ machineId, machineName, canEdit }: {
  machineId: string;
  machineName: string;
  canEdit: boolean;
}) {
  const chartRef = useRef<HTMLDivElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [rows, setRows] = useState<Array<Record<string, string>>>([]);
  const [headers, setHeaders] = useState<string[]>([]);
  const [sensors, setSensors] = useState<Sensor[]>([]);
  const [tp3Id, setTp3Id] = useState("");
  const [currentId, setCurrentId] = useState("");
  const [compId, setCompId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [analysisStatus, setAnalysisStatus] = useState("");
  const [analysis, setAnalysis] = useState<Record<string, unknown> | null>(null);
  const [importJobs, setImportJobs] = useState<Array<{ importId: string; status: string }>>([]);
  const [analysisJobId, setAnalysisJobId] = useState("");

  useEffect(() => {
    apiRequest<{ hierarchy: HierarchyFactory[] }>("/dashboard/hierarchy")
      .then((result) => {
        const machine = findHierarchyMachine(result.hierarchy, machineId);
        const found = machine?.components.flatMap((component) => component.sensors) ?? [];
        setSensors(found);
        setTp3Id(found.find((sensor) => /tp3/i.test(sensor.name))?.id ?? "");
        setCurrentId(found.find((sensor) => /current|motor/i.test(sensor.name))?.id ?? "");
        setCompId(found.find((sensor) => /comp|state|operating/i.test(sensor.name))?.id ?? "");
      })
      .catch((reason) => setError(reason instanceof ApiError ? reason.message : "Replay sensors could not be loaded."));
  }, [machineId]);

  async function selectFile(selected: File | undefined) {
    if (!selected) return;
    setFile(selected);
    setError("");
    setNotice("");
    const text = await selected.text();
    const parsed = csvRows(text);
    if (!parsed.headers.includes("timestamp") || !parsed.headers.includes("TP3")) {
      setError("This CSV is missing the required timestamp and TP3 columns.");
      setRows([]);
      return;
    }
    const invalid = parsed.rows.find((row) => Number.isNaN(Date.parse(String(row.timestamp).replace(" ", "T"))));
    if (invalid) {
      setError(`Invalid timestamp in source row ${parsed.rows.indexOf(invalid) + 2}: ${invalid.timestamp}`);
      setRows([]);
      return;
    }
    setHeaders(parsed.headers);
    setRows(parsed.rows);
    setStart(parsed.rows[0]?.timestamp.replace(" ", "T").slice(0, 16) ?? "");
    setEnd(parsed.rows.at(-1)?.timestamp.replace(" ", "T").slice(0, 16) ?? "");
  }

  async function importMappings() {
    if (!file || !rows.length) return;
    setBusy(true);
    setError("");
    setNotice("");
    const mappings = [
      { sensorId: tp3Id, column: "TP3", unit: "bar" },
      { sensorId: currentId, column: "Motor_current", unit: "A" },
      { sensorId: compId, column: "COMP", unit: "state" },
    ].filter((item) => item.sensorId && headers.includes(item.column));
    if (!mappings.length) {
      setError("Map at least one CSV column to an existing sensor before importing. No import was submitted.");
      setBusy(false);
      return;
    }
    try {
      const accepted: Array<{ importId: string; status: string }> = [];
      for (const item of mappings) {
        const body = new Headers({
          "Content-Type": "text/csv",
          "X-File-Name": file.name,
          "X-Import-Mapping": JSON.stringify({
            timestamp_column: "timestamp",
            timestamp_timezone: "UTC",
            value_column: item.column,
            fixed_unit: item.unit,
            unit_column: null,
            fixed_sensor_id: item.sensorId,
            sensor_column: null,
            source_event_id_column: null,
          }),
        });
        const result = await apiRequest<{ import: { import_id: string; status: string } }>(`/sensor-imports?sensor_id=${encodeURIComponent(item.sensorId)}`, {
          method: "POST",
          body: file,
          headers: body,
        });
        accepted.push({ importId: result.import.import_id, status: result.import.status });
      }
      setImportJobs(accepted);
      setNotice(`${accepted.length} import${accepted.length === 1 ? "" : "s"} accepted and queued for ${file.name}.`);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "The historical import could not be queued.");
    } finally {
      setBusy(false);
    }
  }

  async function drawReplay() {
    if (!chartRef.current || !rows.length) return;
    if (!selectedRows.length) {
      setError("No source readings fall inside the selected window.");
      return;
    }
    const chart = echarts.init(chartRef.current);
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: { data: ["TP3 pressure (bar)", "Motor current (A)", "COMP state"] },
      xAxis: { type: "category", data: selectedRows.map((row) => row.timestamp), axisLabel: { rotate: 35 } },
      yAxis: [{ type: "value", name: "bar / A" }, { type: "value", name: "COMP", min: 0, max: 1 }],
      series: [
        { name: "TP3 pressure (bar)", type: "line", showSymbol: false, data: selectedRows.map((row) => Number(row.TP3)) },
        { name: "Motor current (A)", type: "line", showSymbol: false, data: selectedRows.map((row) => Number(row.Motor_current)) },
        { name: "COMP state", type: "line", showSymbol: false, yAxisIndex: 1, data: selectedRows.map((row) => Number(row.COMP)) },
      ],
    });
    setError("");
  }

  const selectedRows = useMemo(() => rows.filter((row) => {
      const time = row.timestamp.replace(" ", "T");
      return (!start || time >= start) && (!end || time <= `${end}:59`);
    }), [rows, start, end]);
  useEffect(() => {
    if (selectedRows.length && chartRef.current) void drawReplay();
    // Range changes redraw chart and evidence together.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedRows]);

  const train = selectedRows.slice(0, Math.max(1, Math.floor(selectedRows.length * 0.7)));
  const heldout = selectedRows.slice(Math.max(1, Math.floor(selectedRows.length * 0.7)));
  const tp3 = heldout.map((row) => Number(row.TP3)).filter(Number.isFinite);
  const trainValues = train.map((row) => Number(row.TP3)).filter(Number.isFinite);
  const lastValueBaseline = trainValues.at(-1);
  const observedMean = tp3.length ? tp3.reduce((sum, value) => sum + value, 0) / tp3.length : null;
  const lastError = observedMean !== null && lastValueBaseline !== undefined ? Math.abs(observedMean - lastValueBaseline) : null;
  const heldStart = heldout[0]?.timestamp ?? "not available";
  const heldEnd = heldout.at(-1)?.timestamp ?? "not available";

  async function refreshImportJobs() {
    if (!importJobs.length) return;
    const refreshed: Array<{ importId: string; status: string }> = [];
    try {
      for (const item of importJobs) {
        const result = await apiRequest<{ import: { status: string } }>(
          `/sensor-imports/${encodeURIComponent(item.importId)}`,
        );
        refreshed.push({ importId: item.importId, status: result.import.status });
      }
      setImportJobs(refreshed);
      setNotice("Import status refreshed.");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Import status could not be refreshed.");
    }
  }

  async function refreshAnalysis() {
    if (!analysisJobId) return;
    try {
      const result = await apiRequest<{ status: string; result: Record<string, unknown> | null; error: { message: string } | null }>(
        `/historical-replay/analysis/${encodeURIComponent(analysisJobId)}`,
      );
      setAnalysisStatus(result.status.toUpperCase());
      if (result.status !== "queued" && result.status !== "processing") {
        setAnalysis(result.result);
        if (!result.result && result.error) setError(result.error.message);
      }
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Analysis status could not be refreshed.");
    }
  }

  async function requestAnalysis() {
    setAnalysisStatus("QUEUEING");
    setError("");
    try {
      const summary = {
        dataset: "MetroPT3 local source subset",
        machine_name: machineName,
        label: "real-recorded-source, not simulated or validated as fault labels",
        window: { train_end: train.at(-1)?.timestamp, heldout_start: heldStart, heldout_end: heldEnd, interval_seconds_hint: 10 },
        tp3_observed_mean_bar: observedMean,
        tp3_last_value_baseline_bar: lastValueBaseline,
        heldout_absolute_error_bar: lastError,
        sample_count: tp3.length,
        operating_states: Object.fromEntries(Array.from(new Set(selectedRows.map((row) => row.COMP))).map((state) => [
          state,
          selectedRows.filter((row) => row.COMP === state).length,
        ])),
      };
      const queued = await apiRequest<{ job_id: string; status: string }>("/historical-replay/analysis", {
        method: "POST",
        body: JSON.stringify({ evidence_summary: summary }),
      });
      setAnalysisStatus(queued.status.toUpperCase());
      setAnalysisJobId(queued.job_id);
      if (queued.status !== "queued") return;
      for (let attempt = 0; attempt < 6; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        const result = await apiRequest<{ status: string; result: Record<string, unknown> | null; error: { message: string } | null }>(
          `/historical-replay/analysis/${encodeURIComponent(queued.job_id)}`,
        );
        if (result.status !== "queued" && result.status !== "processing") {
          setAnalysisStatus(result.status.toUpperCase());
          setAnalysis(result.result);
          if (!result.result && result.error) setError(result.error.message);
          return;
        }
      }
      setAnalysisStatus("TIMEOUT");
      setError("Gemini analysis timed out; the numerical replay remains available.");
    } catch (reason) {
      setAnalysisStatus("UNAVAILABLE");
      setError(reason instanceof ApiError ? reason.message : "Gemini analysis is unavailable; numerical evidence remains visible.");
    }
  }

  return (
    <section className="mt-6 border border-rule bg-white/35 p-5" aria-label="MetroPT3 historical replay">
      <p className="font-mono text-xs tracking-widest text-ink/60">HISTORICAL REPLAY · MEASURED SOURCE</p>
      <h3 className="mt-2 text-lg font-semibold">Import and replay compressor history</h3>
      <p className="mt-2 text-sm text-ink/65">Dataset: MetroPT3 source subset. No fault label or independent validation claim is inferred.</p>
      <label className="form-field mt-5">
        <span>CSV file or bounded demo window</span>
        <input accept=".csv,text/csv" onChange={(event) => void selectFile(event.currentTarget.files?.[0])} type="file" />
      </label>
      {file && <p className="mt-2 text-sm">{file.name} · {rows.length} source rows selected</p>}
      {rows.length > 0 && (
        <>
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            <label className="form-field"><span>TP3 pressure sensor</span><select value={tp3Id} onChange={(event) => setTp3Id(event.target.value)}><option value="">Select sensor</option>{sensors.map((sensor) => <option key={sensor.id} value={sensor.id}>{sensor.name}</option>)}</select></label>
            <label className="form-field"><span>Motor current sensor</span><select value={currentId} onChange={(event) => setCurrentId(event.target.value)}><option value="">Select sensor</option>{sensors.map((sensor) => <option key={sensor.id} value={sensor.id}>{sensor.name}</option>)}</select></label>
            <label className="form-field"><span>COMP state sensor</span><select value={compId} onChange={(event) => setCompId(event.target.value)}><option value="">Select sensor</option>{sensors.map((sensor) => <option key={sensor.id} value={sensor.id}>{sensor.name}</option>)}</select></label>
          </div>
          <div className="mt-4 flex flex-wrap gap-3">
            <button className="secondary-button" disabled={!canEdit || busy || (!tp3Id && !currentId && !compId)} onClick={() => void importMappings()} type="button">{busy ? "IMPORTING…" : "IMPORT MAPPINGS"}</button>
            <button className="action-button" onClick={() => void drawReplay()} type="button">REPLAY WINDOW</button>
          </div>
          {importJobs.length > 0 && (
            <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
              <span>Accepted import IDs:</span>
              {importJobs.map((job) => <code key={job.importId}>{job.importId}: {job.status}</code>)}
              <button className="secondary-button" onClick={() => void refreshImportJobs()} type="button">REFRESH IMPORT STATUS</button>
            </div>
          )}
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <label className="form-field"><span>Start</span><input type="datetime-local" value={start} onChange={(event) => setStart(event.target.value)} /></label>
            <label className="form-field"><span>End</span><input type="datetime-local" value={end} onChange={(event) => setEnd(event.target.value)} /></label>
          </div>
          <div ref={chartRef} className="mt-5 h-[360px] w-full" aria-label="Synchronized compressor replay chart" />
          <div className="mt-5 border-t border-rule pt-5">
            <p className="font-mono text-xs tracking-widest text-ink/60">EVIDENCE · PAST-ONLY BASELINE</p>
            <p className="mt-2 text-sm">TP3 10-second next-record baseline trained on the first 70%; held-out observed mean {observedMean?.toFixed(3) ?? "unavailable"} bar, last-value baseline {lastValueBaseline?.toFixed(3) ?? "unavailable"} bar, absolute error {lastError?.toFixed(3) ?? "unavailable"} bar.</p>
            <p className="mt-2 text-sm text-ink/65">Held-out window: {heldStart} to {heldEnd} · {tp3.length} readings. COMP=1 is no air intake; it is not evidence that the motor is running.</p>
            <div className="mt-4 flex flex-wrap gap-3">
              <button className="secondary-button" disabled={analysisStatus === "QUEUEING" || analysisStatus === "PROCESSING"} onClick={() => void requestAnalysis()} type="button">ANALYZE EVIDENCE WITH GEMINI</button>
              {analysisStatus && <span className="self-center text-sm text-ink/65">{analysisStatus}</span>}
              {analysisJobId && ["QUEUED", "PROCESSING", "TIMEOUT"].includes(analysisStatus) && (
                <button className="secondary-button" onClick={() => void refreshAnalysis()} type="button">REFRESH PENDING ANALYSIS</button>
              )}
            </div>
            {analysis && <pre className="mt-4 max-h-72 overflow-auto border border-rule bg-white p-4 text-xs">{JSON.stringify(analysis, null, 2)}</pre>}
          </div>
        </>
      )}
      {notice && <p className="mt-4 border-l-2 border-accent pl-4 text-sm" role="status">{notice}</p>}
      {error && <p className="mt-4 border-l-2 border-red-700 pl-4 text-sm text-red-800" role="alert">{error}</p>}
    </section>
  );
}
