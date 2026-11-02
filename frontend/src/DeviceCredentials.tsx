import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, apiRequest } from "./api";

type Credential = {
  credential_id: string;
  key_id: string;
  name: string;
  expires_at: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};

type SensorState = {
  connection_state: "never_seen" | "fresh" | "stale";
  stale: boolean | null;
  last_seen_at: string | null;
  last_event_time: string | null;
  stale_after_seconds: number;
  source: "measured";
};

function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "The device service could not be reached.";
}

function localTime(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "No reading received";
}

export function DeviceCredentials({
  sensorId,
  sensorName,
  canEdit,
  active,
}: {
  sensorId: string;
  sensorName: string;
  canEdit: boolean;
  active: boolean;
}) {
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [sensorState, setSensorState] = useState<SensorState | null>(null);
  const [threshold, setThreshold] = useState("30");
  const [name, setName] = useState(`${sensorName} gateway`);
  const [oneTimeCredential, setOneTimeCredential] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const thresholdSensorId = useRef<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [credentialResult, stateResult] = await Promise.all([
        apiRequest<{ credentials: Credential[] }>(
          `/device-credentials?sensor_id=${encodeURIComponent(sensorId)}`,
        ),
        apiRequest<{ state: SensorState }>(
          `/sensors/${encodeURIComponent(sensorId)}/telemetry-state`,
        ),
      ]);
      setCredentials(credentialResult.credentials);
      setSensorState(stateResult.state);
      if (thresholdSensorId.current !== sensorId) {
        setThreshold(String(stateResult.state.stale_after_seconds));
        thresholdSensorId.current = sensorId;
      }
      setError("");
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setLoading(false);
    }
  }, [sensorId]);

  useEffect(() => {
    setCredentials([]);
    setSensorState(null);
    thresholdSensorId.current = null;
    setName(`${sensorName} gateway`);
    setOneTimeCredential("");
    setLoading(true);
    void refresh();
    const timer = window.setInterval(() => {
      if (active) void refresh();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [active, refresh, sensorName]);

  async function createCredential() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await apiRequest<{ credential: Credential; secret: string }>(
        "/device-credentials",
        {
          method: "POST",
          body: JSON.stringify({
            name,
            sensor_permissions: [{ sensor_id: sensorId, quantities: null }],
          }),
        },
      );
      setOneTimeCredential(`${result.credential.key_id}.${result.secret}`);
      setNotice("Credential created. Copy the secret now; it cannot be viewed again.");
      await refresh();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function rotateCredential(credentialId: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await apiRequest<{ credential: Credential; secret: string }>(
        `/device-credentials/${encodeURIComponent(credentialId)}/rotate`,
        { method: "POST" },
      );
      setOneTimeCredential(`${result.credential.key_id}.${result.secret}`);
      setNotice("Credential rotated. The previous key is revoked; copy this new secret now.");
      await refresh();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function revokeCredential(credentialId: string) {
    if (!window.confirm("Revoke this device credential? Future uploads using it will be rejected.")) return;
    setBusy(true);
    setError("");
    try {
      await apiRequest(`/device-credentials/${encodeURIComponent(credentialId)}/revoke`, {
        method: "POST",
      });
      setNotice("Device credential revoked.");
      await refresh();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function saveThreshold(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await apiRequest<{ state: SensorState }>(
        `/sensors/${encodeURIComponent(sensorId)}/telemetry-state`,
        {
          method: "PUT",
          body: JSON.stringify({ stale_after_seconds: Number(threshold) }),
        },
      );
      setSensorState(result.state);
      setNotice("Per-sensor stale threshold saved.");
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      setBusy(false);
    }
  }

  async function copyCredential() {
    try {
      await navigator.clipboard.writeText(oneTimeCredential);
      setNotice("Credential copied to clipboard.");
    } catch {
      setError("Clipboard access was denied. Select and copy the displayed credential manually.");
    }
  }

  return (
    <section className="mt-6 border border-rule bg-white/35 p-5" aria-label="Device credentials and sensor state">
      <div>
        <p className="font-mono text-xs tracking-wider text-ink/55">LIVE SENSOR CONNECTION</p>
        <h3 className="mt-2 text-lg font-semibold">Read-only device ingestion</h3>
      </div>
      {loading ? (
        <p className="mt-4 text-sm text-ink/65" aria-live="polite">Loading device status…</p>
      ) : sensorState && (
        <div className="mt-4 grid gap-4 border-t border-rule pt-4 sm:grid-cols-3">
          <div>
            <p className="font-mono text-xs text-ink/55">CONNECTION</p>
            <p className="mt-1 font-semibold">{sensorState.connection_state.replace("_", " ").toUpperCase()}</p>
          </div>
          <div>
            <p className="font-mono text-xs text-ink/55">LAST RECEIVED · SERVER TIME</p>
            <p className="mt-1 text-sm">{localTime(sensorState.last_seen_at)}</p>
          </div>
          <div>
            <p className="font-mono text-xs text-ink/55">LATEST EVENT · DEVICE TIME</p>
            <p className="mt-1 text-sm">{localTime(sensorState.last_event_time)}</p>
          </div>
          <p className="text-xs text-ink/60 sm:col-span-3">
            State reflects measured message receipt only. No live value is shown until a device sends one.
          </p>
        </div>
      )}

      {canEdit && (
        <form className="mt-5 grid gap-3 border-t border-rule pt-4 sm:grid-cols-[1fr_auto]" onSubmit={(event) => void saveThreshold(event)}>
          <label className="form-field">
            <span>Stale threshold for this sensor (seconds)</span>
            <input
              min={1}
              max={31536000}
              onChange={(event) => setThreshold(event.target.value)}
              required
              type="number"
              value={threshold}
            />
          </label>
          <button className="secondary-button self-end" disabled={busy || !/^\d+$/.test(threshold) || Number(threshold) < 1} type="submit">
            SAVE THRESHOLD
          </button>
        </form>
      )}

      {canEdit && (
        <div className="mt-5 grid gap-3 border-t border-rule pt-4 sm:grid-cols-[1fr_auto]">
          <label className="form-field">
            <span>Device credential name</span>
            <input maxLength={120} onChange={(event) => setName(event.target.value)} required value={name} />
          </label>
          <button className="action-button self-end" disabled={busy || !name.trim()} onClick={() => void createCredential()} type="button">
            CREATE SENSOR CREDENTIAL
          </button>
        </div>
      )}

      {oneTimeCredential && (
        <div className="mt-4 border border-rule bg-paper p-4">
          <p className="text-sm font-semibold">One-time credential secret</p>
          <p className="mt-1 text-xs text-ink/65">Store it in the device's secret manager. This screen will not show it again after navigation or refresh.</p>
          <code className="mt-3 block break-all font-mono text-xs">{oneTimeCredential}</code>
          <button className="secondary-button mt-3" onClick={() => void copyCredential()} type="button">COPY CREDENTIAL</button>
        </div>
      )}

      <div className="mt-5 border-t border-rule pt-4">
        <h4 className="font-mono text-xs tracking-wider">SCOPED DEVICE KEYS</h4>
        {loading ? null : credentials.length === 0 ? (
          <p className="mt-3 text-sm text-ink/65">No device credentials are registered for this sensor.</p>
        ) : (
          <ul className="mt-2 divide-y divide-rule">
            {credentials.map((credential) => {
              const expired = Date.parse(credential.expires_at) <= Date.now();
              const activeCredential = !credential.revoked_at && !expired;
              return (
                <li className="flex flex-wrap items-start justify-between gap-3 py-3" key={credential.credential_id}>
                  <div>
                    <p className="font-semibold">{credential.name}</p>
                    <p className="mt-1 font-mono text-xs">{credential.key_id} · {credential.revoked_at ? "REVOKED" : expired ? "EXPIRED" : "ACTIVE"}</p>
                    <p className="mt-1 text-xs text-ink/60">
                      Expires {localTime(credential.expires_at)} · last used {localTime(credential.last_used_at)}
                    </p>
                  </div>
                  {canEdit && activeCredential && (
                    <div className="flex gap-2">
                      <button className="secondary-button" disabled={busy} onClick={() => void rotateCredential(credential.credential_id)} type="button">ROTATE</button>
                      <button className="secondary-button" disabled={busy} onClick={() => void revokeCredential(credential.credential_id)} type="button">REVOKE</button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
      {error && <p className="mt-4 text-sm text-red-800" role="alert">{error}</p>}
      {notice && <p className="mt-4 text-sm text-ink/75" role="status">{notice}</p>}
      {!active && <p className="mt-4 text-sm text-amber-900">This sensor is archived; new device writes are disabled.</p>}
    </section>
  );
}
