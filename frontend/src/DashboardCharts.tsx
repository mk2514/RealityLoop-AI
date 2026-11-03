import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent, DataZoomComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { ApiError, apiRequest, apiUrl } from "./api";
import { navigate } from "./router";

echarts.use([LineChart, GridComponent, TooltipComponent, DataZoomComponent, CanvasRenderer]);

type SensorNode = { id: string; name: string; kind: "sensor" };
type ComponentNode = { id: string; name: string; kind: "component"; sensors: SensorNode[] };
type MachineNode = { id: string; name: string; kind: "machine"; components: ComponentNode[] };
type LineNode = { id: string; name: string; kind: "line"; machines: MachineNode[] };
type FactoryNode = { id: string; name: string; kind: "factory"; lines: LineNode[] };

type ReadingResponse = {
  kind: "observed";
  sensor_id: string;
  quantity: string;
  unit: string;
  timezone: string;
  window: { start: string; end: string };
  view: "raw" | "aggregated";
  bucket_size_seconds: number | null;
  row_count: number;
  bucket_count: number;
  quality_summary: Record<string, number>;
  freshness: { connection_state: string; stale: boolean | null; last_seen_at: string | null };
  samples: Array<Record<string, unknown>>;
};

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "The dashboard service could not be reached.";
}

export function DashboardCharts() {
  const chartRef = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const [hierarchy, setHierarchy] = useState<FactoryNode[]>([]);
  const [sensorId, setSensorId] = useState("");
  const [view, setView] = useState<"raw" | "aggregated">("aggregated");
  const [start, setStart] = useState(() => new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString().slice(0, 16));
  const [end, setEnd] = useState(() => new Date().toISOString().slice(0, 16));
  const [timezone, setTimezone] = useState("UTC");
  const [unit, setUnit] = useState("");
  const [result, setResult] = useState<ReadingResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [live, setLive] = useState(false);
  const [error, setError] = useState("");
  const [thresholdNotice, setThresholdNotice] = useState("");

  useEffect(() => {
    void apiRequest<{ hierarchy: FactoryNode[] }>("/dashboard/hierarchy")
      .then((data) => {
        setHierarchy(data.hierarchy);
        const requested = new URL(window.location.href).searchParams.get("sensor");
        setSensorId(requested || "");
      })
      .catch((reason) => setError(errorText(reason)));
  }, []);

  useEffect(() => {
    if (!chartRef.current) return;
    chart.current = echarts.init(chartRef.current, undefined, { renderer: "canvas" });
    const resize = () => chart.current?.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    if (!chart.current || !result) return;
    const labels = result.samples.map((sample) => {
      const value = String(sample.bucket_start_utc ?? sample.event_time_utc ?? "");
      if (!value) return "";
      try {
        return new Intl.DateTimeFormat(undefined, {
          timeZone: result.timezone,
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }).format(new Date(value));
      } catch {
        return value;
      }
    });
    const values = result.samples.map((sample) => {
      const value = result.view === "aggregated" ? sample.avg : sample.value;
      return typeof value === "number" ? value : null;
    });
    chart.current.setOption({
      animation: false,
      grid: { left: 52, right: 20, top: 24, bottom: 48 },
      tooltip: { trigger: "axis" },
      dataZoom: [{ type: "inside" }],
      xAxis: { type: "category", data: labels, axisLabel: { rotate: 0 } },
      yAxis: { type: "value", name: result.unit, scale: true },
      series: [{
        name: `${result.quantity} · observed`,
        type: "line",
        data: values,
        connectNulls: false,
        showSymbol: values.length <= 200,
        lineStyle: { width: 1.5 },
      }],
    });
  }, [result]);

  // Live-refresh interval — polls every 5 s when live mode is active
  useEffect(() => {
    if (!live || !sensorId) return;
    const refresh = window.setInterval(() => {
      const endAt = new Date();
      const startAt = new Date(endAt.getTime() - 15 * 60 * 1000);
      setStart(startAt.toISOString().slice(0, 16));
      setEnd(endAt.toISOString().slice(0, 16));
      void load(startAt.toISOString().slice(0, 16), endAt.toISOString().slice(0, 16));
    }, 5_000);
    return () => window.clearInterval(refresh);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, sensorId]);

  async function load(windowStart = start, windowEnd = end) {
    if (!sensorId) {
      setError("Select a sensor before loading readings.");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        start: new Date(windowStart).toISOString(),
        end: new Date(windowEnd).toISOString(),
        view,
        timezone,
      });
      if (unit) params.set("display_unit", unit);
      const data = await apiRequest<ReadingResponse>(`/sensors/${encodeURIComponent(sensorId)}/readings?${params}`);
      setResult(data);
      const target = new URL(window.location.href);
      target.searchParams.set("sensor", sensorId);
      target.searchParams.set("view", view);
      navigate(`${target.pathname}${target.search}${target.hash}`);
    } catch (reason) {
      setResult(null);
      setError(errorText(reason));
    } finally {
      setLoading(false);
    }
  }

  function exportCsv() {
    if (!sensorId) return;
    const params = new URLSearchParams({
      start: new Date(start).toISOString(),
      end: new Date(end).toISOString(),
      view,
      timezone,
    });
    if (unit) params.set("display_unit", unit);
    void fetch(apiUrl(`/sensors/${encodeURIComponent(sensorId)}/readings-export?${params}`), {
      credentials: "include",
      headers: { Accept: "text/csv" },
    }).then(async (response) => {
      if (!response.ok) throw new Error(response.status === 413 ? "The export exceeds the configured row cap." : "The export could not be generated.");
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `sensor-${sensorId}-${view}.csv`;
      link.click();
      URL.revokeObjectURL(url);
    }).catch((reason) => setError(reason instanceof Error ? reason.message : "The export could not be generated."));
  }

  async function saveLayout() {
    try {
      await apiRequest("/dashboard/layouts/dashboard", {
        method: "PUT",
        body: JSON.stringify({
          schema_version: 1,
          scope_key: "dashboard",
          panels: sensorId ? [{ sensor_id: sensorId, view_mode: view, unit, timezone }] : [],
        }),
      });
      setThresholdNotice("Dashboard layout saved.");
    } catch (reason) {
      setError(errorText(reason));
    }
  }

  const sensors = hierarchy.flatMap((factory) =>
    factory.lines.flatMap((line) =>
      line.machines.flatMap((machine) =>
        machine.components.flatMap((component) =>
          component.sensors.map((sensor) => ({ ...sensor, path: `${factory.name} / ${line.name} / ${machine.name} / ${component.name}` })),
        ),
      ),
    ),
  );

  return (
    <section className="border border-rule bg-white/40 p-6" aria-labelledby="dashboard-charts-title">
      <p className="font-mono text-xs tracking-widest text-ink/60">OBSERVED DATA · MEASURED</p>
      <h2 className="mt-2 text-2xl font-semibold" id="dashboard-charts-title">Sensor dashboard</h2>
      <div className="mt-5 grid gap-4 lg:grid-cols-6">
        <label className="form-field lg:col-span-2">
          <span>Sensor</span>
          <select value={sensorId} onChange={(event) => setSensorId(event.target.value)}>
            <option value="">Select sensor</option>
            {sensors.map((sensor) => <option key={sensor.id} value={sensor.id}>{sensor.path} / {sensor.name}</option>)}
          </select>
        </label>
        <label className="form-field"><span>View</span><select value={view} onChange={(event) => setView(event.target.value as "raw" | "aggregated")}><option value="aggregated">Aggregated</option><option value="raw">Raw</option></select></label>
        <label className="form-field"><span>Start</span><input type="datetime-local" value={start} onChange={(event) => setStart(event.target.value)} /></label>
        <label className="form-field"><span>End</span><input type="datetime-local" value={end} onChange={(event) => setEnd(event.target.value)} /></label>
        <label className="form-field"><span>Timezone</span><input value={timezone} onChange={(event) => setTimezone(event.target.value)} placeholder="UTC" /></label>
        <label className="form-field"><span>Display unit (optional)</span><input value={unit} onChange={(event) => setUnit(event.target.value)} /></label>
      </div>
      <div className="mt-4 flex flex-wrap gap-3">
        <button className="action-button" disabled={loading || !sensorId} onClick={() => void load()} type="button">{loading ? "LOADING…" : "LOAD READINGS"}</button>
        <button className="secondary-button" disabled={!sensorId} onClick={() => {
          setLive((current) => !current);
          if (!live) void load();
        }} type="button">{live ? "STOP LIVE" : "START LIVE"}</button>
        <button className="secondary-button" disabled={!sensorId || loading} onClick={exportCsv} type="button">EXPORT CSV</button>
        <button className="secondary-button" disabled={!sensorId || loading} onClick={() => void saveLayout()} type="button">SAVE PANEL</button>
      </div>
      {error && <p className="mt-4 border-l-2 border-red-700 pl-4 text-sm text-red-800" role="alert">{error}</p>}
      {thresholdNotice && <p className="mt-4 border-l-2 border-accent pl-4 text-sm" role="status">{thresholdNotice}</p>}
      {result && (
        <div className="mt-6">
          <div className="flex flex-wrap gap-x-6 gap-y-2 border-b border-rule pb-4 text-sm text-ink/70">
            <span>Kind: observed</span>
            <span>Unit: {result.unit}</span>
            <span>Timezone: {result.timezone}</span>
            <span>Rows/buckets: {result.row_count}/{result.bucket_count}</span>
            <span>Status: {result.freshness.connection_state}</span>
            <span>Quality gaps: uncertain {result.quality_summary.uncertain} · bad {result.quality_summary.bad}</span>
          </div>
          <div ref={chartRef} className="mt-5 h-[360px] w-full" aria-label="Observed sensor readings chart" />
        </div>
      )}
    </section>
  );
}
