import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, apiRequest } from "./api";
import { DeviceCredentials } from "./DeviceCredentials";

type PreviewRow = {
  row_number: number;
  values: string[];
  parse_status: "mapping_required" | "valid" | "review" | "rejected";
  warnings: string[];
};

type Preview = {
  headers: string[];
  delimiter: string;
  rows_total: number;
  sample_rows: PreviewRow[];
  mapping_confirmed: boolean;
  warnings: string[];
};

type ImportMapping = {
  timestamp_column: string;
  timestamp_timezone: string;
  value_column: string;
  fixed_unit: string | null;
  unit_column: string | null;
  fixed_sensor_id: string | null;
  sensor_column: string | null;
  source_event_id_column: string | null;
};

type ImportRecord = {
  import_id: string;
  status: "uploaded" | "queued" | "processing" | "completed" | "completed_with_errors" | "failed" | "cancelled";
  source_checksum: string;
  created_at: string;
  counts: { total: number; inserted: number; duplicates: number; rejected: number };
  rejected_by_code: Record<string, number>;
  error_summary: string | null;
  identical_source_imports: number;
  worker_attempt_count: number;
  progress_rows: number;
  has_error_file: boolean;
};

type SensorImportsProps = {
  sensorId: string;
  sensorName: string;
  measurementType: string;
  registeredUnit: string;
  canEdit: boolean;
  active: boolean;
};

function message(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "The sensor import service could not be reached.";
}

function initialColumn(headers: string[], pattern: RegExp): string {
  return headers.find((header) => pattern.test(header)) ?? headers[0] ?? "";
}

export function SensorImports({
  sensorId,
  sensorName,
  measurementType,
  registeredUnit,
  canEdit,
  active,
}: SensorImportsProps) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<ImportMapping>({
    timestamp_column: "",
    timestamp_timezone: "value",
    value_column: "",
    fixed_unit: registeredUnit,
    unit_column: null,
    fixed_sensor_id: sensorId,
    sensor_column: null,
    source_event_id_column: null,
  });
  const [imports, setImports] = useState<ImportRecord[]>([]);
  const [loadingImports, setLoadingImports] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const mappingReady = Boolean(mapping.timestamp_column && mapping.value_column
    && (mapping.fixed_unit || mapping.unit_column)
    && (mapping.fixed_sensor_id || mapping.sensor_column));

  const loadImports = useCallback(async () => {
    try {
      const result = await apiRequest<{ imports: ImportRecord[] }>(
        `/sensor-imports?sensor_id=${encodeURIComponent(sensorId)}`,
      );
      setImports(result.imports);
      setError("");
    } catch (reason) {
      setError(message(reason));
    } finally {
      setLoadingImports(false);
    }
  }, [sensorId]);

  useEffect(() => {
    setFile(null);
    setPreview(null);
    setMapping({
      timestamp_column: "",
      timestamp_timezone: "value",
      value_column: "",
      fixed_unit: registeredUnit,
      unit_column: null,
      fixed_sensor_id: sensorId,
      sensor_column: null,
      source_event_id_column: null,
    });
    setImports([]);
    setLoadingImports(true);
    void loadImports();
    const timer = window.setInterval(() => {
      if (active) void loadImports();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [active, loadImports, registeredUnit, sensorId]);

  const updateRequiredMapping = (
    key: "timestamp_column" | "timestamp_timezone" | "value_column",
    value: string,
  ) => {
    setMapping((current) => ({ ...current, [key]: value }));
    setPreview((current) => current ? { ...current, mapping_confirmed: false } : current);
  };
  const updateOptionalMapping = (
    key: "fixed_unit" | "unit_column" | "sensor_column" | "source_event_id_column",
    value: string,
  ) => {
    setMapping((current) => ({ ...current, [key]: value || null }));
    setPreview((current) => current ? { ...current, mapping_confirmed: false } : current);
  };

  async function previewFile(confirmed: boolean) {
    if (!file) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const headers = new Headers({ "Content-Type": "text/csv", "X-File-Name": file.name });
      if (confirmed) headers.set("X-Import-Mapping", JSON.stringify(mapping));
      const result = await apiRequest<Preview>(
        `/sensor-imports/preview?sensor_id=${encodeURIComponent(sensorId)}`,
        { method: "POST", body: file, headers },
      );
      setPreview(result);
      if (!confirmed) {
        setMapping((current) => ({
          ...current,
          timestamp_column: initialColumn(result.headers, /time|date|timestamp/i),
          value_column: initialColumn(result.headers, /value|reading|measurement/i),
          fixed_unit: registeredUnit,
          fixed_sensor_id: sensorId,
        }));
      } else {
        setNotice("Mapping checked against the sample. Confirm to queue the import.");
      }
    } catch (reason) {
      setError(message(reason));
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  async function submitImport() {
    if (!file || !mappingReady || !preview?.mapping_confirmed) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await apiRequest<{ import: ImportRecord }>(
        `/sensor-imports?sensor_id=${encodeURIComponent(sensorId)}`,
        {
          method: "POST",
          body: file,
          headers: {
            "Content-Type": "text/csv",
            "X-File-Name": file.name,
            "X-Import-Mapping": JSON.stringify(mapping),
          },
        },
      );
      setNotice(`Import ${result.import.import_id} was queued.`);
      setFile(null);
      setPreview(null);
      await loadImports();
    } catch (reason) {
      setError(message(reason));
      await loadImports();
    } finally {
      setBusy(false);
    }
  }

  async function changeImport(importId: string, action: "cancel" | "retry") {
    setBusy(true);
    setError("");
    try {
      await apiRequest(`/sensor-imports/${encodeURIComponent(importId)}/${action}`, {
        method: "POST",
      });
      await loadImports();
    } catch (reason) {
      setError(message(reason));
    } finally {
      setBusy(false);
    }
  }

  async function downloadErrors(importId: string) {
    setError("");
    try {
      const result = await apiRequest<{ download_url: string }>(
        `/sensor-imports/${encodeURIComponent(importId)}/errors`,
      );
      window.location.assign(result.download_url);
    } catch (reason) {
      setError(message(reason));
    }
  }

  const columns = useMemo(() => preview?.headers ?? [], [preview]);
  const columnOptions = () => columns.map((column) => (
    <option key={column} value={column}>{column}</option>
  ));

  function chooseFile(selected: File | undefined) {
    setFile(selected ?? null);
    setPreview(null);
    setNotice("");
    setError("");
  }

  return (
    <>
    {active && (
      <DeviceCredentials
        active={active}
        canEdit={canEdit}
        sensorId={sensorId}
        sensorName={sensorName}
      />
    )}
    <section className="mt-6 border border-rule bg-white/35 p-5" aria-label="Historical sensor imports">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-mono text-xs tracking-wider text-ink/55">HISTORICAL IMPORT · SOURCE FILE RETAINED PRIVATELY</p>
          <h3 className="mt-2 text-lg font-semibold">{sensorName}</h3>
          <p className="mt-1 text-sm text-ink/65">
            {measurementType} · registered unit {registeredUnit}. Imported values are measured source data normalized to the registered quantity.
          </p>
        </div>
        {!canEdit && <p className="text-sm text-ink/60">Your workspace role can view import history but cannot upload or manage imports.</p>}
      </div>

      {canEdit && (
        <div className="mt-5 grid gap-4 border-t border-rule pt-5">
          <label className="form-field">
            <span>CSV file (UTF-8; bounded upload)</span>
            <input
              accept=".csv,text/csv"
              onChange={(event) => chooseFile(event.currentTarget.files?.[0])}
              type="file"
            />
          </label>
          <div className="flex flex-wrap gap-3">
            <button className="secondary-button" disabled={!file || busy} onClick={() => void previewFile(false)} type="button">
              {busy ? "CHECKING…" : "READ CSV HEADERS"}
            </button>
            {file && <span className="self-center text-sm text-ink/65">{file.name} · {file.size.toLocaleString()} bytes</span>}
          </div>
          {preview && (
            <div className="grid gap-4 border-t border-rule pt-4">
              <p className="text-sm">
                {preview.rows_total.toLocaleString()} data rows · delimiter {preview.delimiter}
              </p>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                <label className="form-field">
                  <span>Timestamp column</span>
                  <select value={mapping.timestamp_column} onChange={(event) => updateRequiredMapping("timestamp_column", event.target.value)}>
                    {columnOptions()}
                  </select>
                </label>
                <label className="form-field">
                  <span>Timestamp timezone</span>
                  <input
                    maxLength={128}
                    onChange={(event) => updateRequiredMapping("timestamp_timezone", event.target.value)}
                    required
                    value={mapping.timestamp_timezone}
                  />
                  <small>Use “value” only when every timestamp includes UTC or an explicit offset; otherwise enter an IANA zone.</small>
                </label>
                <label className="form-field">
                  <span>Measured value column</span>
                  <select value={mapping.value_column} onChange={(event) => updateRequiredMapping("value_column", event.target.value)}>
                    {columnOptions()}
                  </select>
                </label>
                <label className="form-field">
                  <span>Unit source</span>
                  <select
                    value={mapping.unit_column ? "column" : "fixed"}
                    onChange={(event) => setMapping((current) => ({
                      ...current,
                      fixed_unit: event.target.value === "fixed" ? registeredUnit : null,
                      unit_column: event.target.value === "column" ? columns[0] ?? null : null,
                    }))}
                  >
                    <option value="fixed">Fixed unit</option>
                    <option value="column">CSV column</option>
                  </select>
                </label>
                {mapping.unit_column ? (
                  <label className="form-field">
                    <span>Unit column</span>
                    <select value={mapping.unit_column} onChange={(event) => updateOptionalMapping("unit_column", event.target.value)}>
                      {columnOptions()}
                    </select>
                  </label>
                ) : (
                  <label className="form-field">
                    <span>Fixed unit</span>
                    <input maxLength={32} onChange={(event) => updateOptionalMapping("fixed_unit", event.target.value)} required value={mapping.fixed_unit ?? ""} />
                  </label>
                )}
                <label className="form-field">
                  <span>Sensor source</span>
                  <select
                    value={mapping.sensor_column ? "column" : "fixed"}
                    onChange={(event) => setMapping((current) => ({
                      ...current,
                      fixed_sensor_id: event.target.value === "fixed" ? sensorId : null,
                      sensor_column: event.target.value === "column" ? columns[0] ?? null : null,
                    }))}
                  >
                    <option value="fixed">Selected sensor: {sensorName}</option>
                    <option value="column">CSV column with registered sensor ID/identity</option>
                  </select>
                </label>
                {mapping.sensor_column && (
                  <label className="form-field">
                    <span>Sensor ID column</span>
                    <select value={mapping.sensor_column} onChange={(event) => updateOptionalMapping("sensor_column", event.target.value)}>
                      {columnOptions()}
                    </select>
                  </label>
                )}
                <label className="form-field">
                  <span>Source event ID (optional)</span>
                  <select
                    value={mapping.source_event_id_column ?? ""}
                    onChange={(event) => updateOptionalMapping("source_event_id_column", event.target.value)}
                  >
                    <option value="">Not provided</option>
                    {columnOptions()}
                  </select>
                </label>
              </div>
              <div className="flex flex-wrap gap-3">
                <button className="secondary-button" disabled={!mappingReady || busy} onClick={() => void previewFile(true)} type="button">
                  VALIDATE MAPPING SAMPLE
                </button>
                <button className="action-button" disabled={!mappingReady || !preview.mapping_confirmed || busy} onClick={() => void submitImport()} type="button">
                  {busy ? "SENDING…" : "CONFIRM AND QUEUE IMPORT"}
                </button>
              </div>
              {preview.warnings.map((warning) => <p className="text-sm text-amber-900" key={warning}>{warning}</p>)}
              <div className="overflow-x-auto border border-rule">
                <table className="w-full min-w-[640px] text-left text-xs">
                  <thead><tr className="border-b border-rule bg-paper/60">
                    <th className="p-2">Row</th><th className="p-2">Status</th><th className="p-2">Sample values</th><th className="p-2">Warnings</th>
                  </tr></thead>
                  <tbody>
                    {preview.sample_rows.map((row) => (
                      <tr className="border-b border-rule last:border-0" key={row.row_number}>
                        <td className="p-2 font-mono">{row.row_number}</td>
                        <td className="p-2">{row.parse_status}</td>
                        <td className="p-2 font-mono">{row.values.join(" · ")}</td>
                        <td className="p-2">{row.warnings.join(" ") || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}

      {error && <p className="mt-4 border-l-2 border-red-700 pl-3 text-sm text-red-800" role="alert">{error}</p>}
      {notice && <p className="mt-4 border-l-2 border-accent pl-3 text-sm" role="status">{notice}</p>}

      <div className="mt-6 border-t border-rule pt-4">
        <h4 className="font-mono text-xs tracking-wider">IMPORT HISTORY</h4>
        {loadingImports ? (
          <p aria-live="polite" className="mt-3 text-sm text-ink/65">Loading import status…</p>
        ) : imports.length === 0 ? (
          <p className="mt-3 text-sm text-ink/65">No historical imports for this sensor.</p>
        ) : (
          <ul className="mt-3 divide-y divide-rule">
            {imports.map((item) => (
              <li className="grid gap-3 py-4 lg:grid-cols-[1fr_auto]" key={item.import_id}>
                <div>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <strong className="font-mono text-xs">{item.status.toUpperCase()}</strong>
                    <span className="text-xs text-ink/60">{new Date(item.created_at).toLocaleString()}</span>
                    {item.identical_source_imports > 0 && <span className="text-xs text-amber-900">Identical source already imported {item.identical_source_imports} time(s).</span>}
                  </div>
                  <p className="mt-2 text-sm">
                    {item.counts.total.toLocaleString()} rows · {item.counts.inserted.toLocaleString()} inserted · {item.counts.duplicates.toLocaleString()} duplicates · {item.counts.rejected.toLocaleString()} rejected
                  </p>
                  {item.error_summary && <p className="mt-1 text-sm text-red-800">{item.error_summary}</p>}
                  {Object.keys(item.rejected_by_code).length > 0 && (
                    <p className="mt-1 text-xs text-ink/65">{Object.entries(item.rejected_by_code).map(([code, count]) => `${code}: ${count}`).join(" · ")}</p>
                  )}
                  {item.status === "processing" && (
                    <p className="mt-1 text-xs text-ink/60" aria-live="polite">{item.progress_rows.toLocaleString()} rows committed · attempt {item.worker_attempt_count}</p>
                  )}
                  <p className="mt-1 break-all font-mono text-[0.65rem] text-ink/50">SHA-256 {item.source_checksum}</p>
                </div>
                <div className="flex flex-wrap items-start gap-2">
                  {item.has_error_file && (
                    <button className="secondary-button" onClick={() => void downloadErrors(item.import_id)} type="button">DOWNLOAD REJECTED ROWS</button>
                  )}
                  {canEdit && ["queued", "processing"].includes(item.status) && (
                    <button className="secondary-button" disabled={busy} onClick={() => void changeImport(item.import_id, "cancel")} type="button">CANCEL</button>
                  )}
                  {canEdit && item.status === "failed" && (
                    <button className="secondary-button" disabled={busy} onClick={() => void changeImport(item.import_id, "retry")} type="button">RETRY</button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
    </>
  );
}
