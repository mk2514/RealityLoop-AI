import { useEffect, useState, type FormEvent } from "react";
import { ApiError, apiRequest } from "./api";

type LineOption = { id: string; name: string };
type PhotoJob = {
  id?: string;
  job_id?: string;
  status: string;
  draft?: { stations?: Array<{ candidate_id: string; label: string; kind: string }> };
  error?: { message?: string } | null;
};

export function PhotoLineStarter() {
  const [files, setFiles] = useState<FileList | null>(null);
  const [consent, setConsent] = useState(false);
  const [lineId, setLineId] = useState("");
  const [lines, setLines] = useState<LineOption[]>([]);
  const [jobId, setJobId] = useState("");
  const [job, setJob] = useState<PhotoJob | null>(null);
  const [draftText, setDraftText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    apiRequest<{ hierarchy: Array<{ lines: Array<{ id: string; name: string }> }> }>("/dashboard/hierarchy")
      .then((result) => setLines(result.hierarchy.flatMap((factory) => factory.lines)))
      .catch((reason) => setError(reason instanceof ApiError ? reason.message : "Lines could not be loaded."));
  }, []);

  async function poll(id: string) {
    for (let attempt = 0; attempt < 12; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      const result = await apiRequest<{ job: PhotoJob }>(`/photo-line-jobs/${encodeURIComponent(id)}`);
      setJob(result.job);
      if (result.job.status !== "queued" && result.job.status !== "processing") {
        if (result.job.draft) setDraftText(JSON.stringify(result.job.draft, null, 2));
        if (["failed", "missing_key", "provider_outage"].includes(result.job.status)) {
          setError(result.job.error?.message ?? "Photo analysis did not complete.");
        }
        return;
      }
    }
    setNotice("Analysis is still pending. Use Refresh status.");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!files?.length || !consent) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const form = new FormData();
      for (let index = 0; index < files.length; index += 1) form.append("files", files[index]);
      form.append("consent_confirmed", "true");
      if (lineId) form.append("line_id", lineId);
      form.append("idempotency_key", `photo-ui:${crypto.randomUUID()}`);
      const result = await apiRequest<{ job: PhotoJob }>("/photo-line-jobs", { method: "POST", body: form });
      const id = result.job.id ?? result.job.job_id ?? "";
      setJobId(id);
      setNotice(id ? `Photo job accepted: ${id}` : "Photo job was accepted.");
      if (id) await poll(id);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "The photo could not be queued.");
    } finally {
      setBusy(false);
    }
  }

  async function refresh() {
    if (!jobId) return;
    try {
      const result = await apiRequest<{ job: PhotoJob }>(`/photo-line-jobs/${encodeURIComponent(jobId)}`);
      setJob(result.job);
      if (result.job.draft) setDraftText(JSON.stringify(result.job.draft, null, 2));
      if (result.job.error?.message) setError(result.job.error.message);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Photo status could not be refreshed.");
    }
  }

  async function confirmSave() {
    if (!lineId || job?.status !== "completed" || !draftText) return;
    setBusy(true);
    setError("");
    try {
      const draft = JSON.parse(draftText) as { stations?: Array<{ candidate_id: string; label: string; kind: string }> };
      const current = await apiRequest<{ revision: number; model: { schema_version: 1; layout: { nodes: unknown[]; edges: unknown[]; transfer_settings: unknown }; products: unknown[]; recipes: unknown[] } }>(
        `/lines/${encodeURIComponent(lineId)}/model`,
      );
      const stations = draft.stations ?? [];
      const existingNodes = current.model.layout.nodes as Array<{ id: string; position?: { x: number; y: number } }>;
      const offsetX = existingNodes.reduce((max, node) => Math.max(max, node.position?.x ?? 0), 0) + (existingNodes.length ? 260 : 0);
      const nodes = stations.map((station, index) => ({
        id: `photo-${jobId.slice(-6)}-${station.candidate_id}`,
        type: station.kind === "buffer" ? "buffer" : station.kind === "machine" ? "machine" : "machine",
        position: { x: 140 + offsetX + index * 220, y: 220 },
        rotation: 0,
        label: station.label,
        machine_id: null,
        required: true,
        buffer_capacity: null,
      }));
      const result = await apiRequest<{ revision: number }>(`/lines/${encodeURIComponent(lineId)}/model`, {
        method: "PUT",
        body: JSON.stringify({
          expected_revision: current.revision,
          model: {
            ...current.model,
            layout: {
              nodes: [...existingNodes, ...nodes],
              edges: current.model.layout.edges,
              transfer_settings: current.model.layout.transfer_settings,
            },
          },
        }),
      });
      setNotice(`Confirmed photo draft appended to the existing layout (nothing removed) and saved as line version ${result.revision}.`);
    } catch (reason) {
      setError(reason instanceof ApiError || reason instanceof SyntaxError
        ? "The draft is invalid or the line could not be saved. No file was silently overwritten."
        : "The photo draft could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-6 border border-rule bg-white/40 p-6" aria-labelledby="photo-twin-title">
      <p className="font-mono text-xs tracking-widest text-ink/60">PHOTO-TO-TWIN · EXTERNAL PROCESSING OPT-IN</p>
      <h2 className="mt-2 text-xl font-semibold" id="photo-twin-title">Start from photos</h2>
      <form className="mt-4 grid gap-4 sm:grid-cols-2" onSubmit={submit}>
        <label className="form-field"><span>Photos</span><input accept="image/jpeg,image/png,image/webp" multiple onChange={(event) => setFiles(event.currentTarget.files)} type="file" /></label>
        <label className="form-field"><span>Existing line to correct (optional)</span>
          <select value={lineId} onChange={(event) => setLineId(event.target.value)}><option value="">Create draft only</option>{lines.map((line) => <option key={line.id} value={line.id}>{line.name}</option>)}</select>
        </label>
        <label className="sm:col-span-2 flex items-center gap-2 text-sm">
          <input checked={consent} onChange={(event) => setConsent(event.target.checked)} type="checkbox" />
          I consent to private, tenant-scoped image processing by the configured Gemini worker.
        </label>
        <button className="action-button sm:col-span-2" disabled={!files?.length || !consent || busy} type="submit">{busy ? "SUBMITTING…" : "SUBMIT PHOTOS"}</button>
      </form>
      {(jobId || job) && (
        <div className="mt-5 border-t border-rule pt-4">
          <p className="text-sm">Job: <code>{jobId || job?.id || job?.job_id}</code> · Status: <strong>{job?.status ?? "accepted"}</strong></p>
          <button className="secondary-button mt-3" disabled={!jobId || busy} onClick={() => void refresh()} type="button">REFRESH STATUS</button>
        </div>
      )}
      {job?.status === "completed" && (
        <div className="mt-4">
          <label className="form-field"><span>Editable correction draft (JSON)</span><textarea rows={10} value={draftText} onChange={(event) => setDraftText(event.target.value)} /></label>
          <button className="action-button mt-3" disabled={!lineId || busy} onClick={() => void confirmSave()} type="button">CONFIRM AND SAVE LINE VERSION</button>
          {!lineId && <p className="mt-2 text-sm text-ink/65">Select an existing line before confirming a normal version.</p>}
        </div>
      )}
      {notice && <p className="mt-4 border-l-2 border-accent pl-4 text-sm" role="status">{notice}</p>}
      {error && <p className="mt-4 border-l-2 border-red-700 pl-4 text-sm text-red-800" role="alert">{error}</p>}
    </section>
  );
}
