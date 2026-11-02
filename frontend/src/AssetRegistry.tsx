import { useEffect, useState, type FormEvent } from "react";
import { ApiError, apiRequest } from "./api";

type RegistryAsset = {
  id: string;
  name: string;
  archived_at: string | null;
  [key: string]: unknown;
};

type Factory = RegistryAsset & {
  timezone: string;
  description: string;
  unit_preferences: { system: "metric" | "imperial"; temperature: "C" | "F" };
  operating_calendar: { shifts: { day: number; name: string; start: string; end: string }[] };
};

type MachineTemplate = {
  key: string;
  label: string;
  suggested_capabilities: string[];
  physics_model: null;
  model_validation_status: "not_validated";
};

type MachineStates = Record<string, string>;
type SensorUnits = Record<string, string[]>;
type EditorKind = "factory" | "line" | "machine" | "component" | "sensor";
type EditorState = {
  kind: EditorKind;
  record: RegistryAsset | null;
  parentId?: string;
};

const COMPONENT_TYPES = ["motor", "bearing", "gearbox", "belt", "controller", "custom"];
const MEASUREMENT_TYPES = [
  "temperature",
  "pressure",
  "vibration",
  "speed",
  "current",
  "voltage",
  "power",
  "flow",
  "level",
  "proximity",
  "position",
  "force",
  "humidity",
  "count",
  "custom",
];
const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "The factory registry could not be reached.";
}

function value(record: RegistryAsset | null, key: string, fallback = ""): string {
  const result = record?.[key];
  return typeof result === "string" || typeof result === "number" ? String(result) : fallback;
}

function FormField({
  label,
  name,
  defaultValue,
  required = false,
  type = "text",
  min,
  step,
  maxLength,
  hint,
  list,
}: {
  label: string;
  name: string;
  defaultValue?: string | number;
  required?: boolean;
  type?: string;
  min?: number;
  step?: number;
  maxLength?: number;
  hint?: string;
  list?: string;
}) {
  return (
    <label className="form-field">
      <span>{label}{hint && <small> ({hint})</small>}</span>
      <input
        defaultValue={defaultValue}
        maxLength={maxLength}
        list={list}
        min={min}
        name={name}
        required={required}
        step={step}
        type={type}
      />
    </label>
  );
}

function SelectField({
  label,
  name,
  options,
  defaultValue,
  required = true,
}: {
  label: string;
  name: string;
  options: { value: string; label: string }[];
  defaultValue?: string;
  required?: boolean;
}) {
  return (
    <label className="form-field">
      <span>{label}</span>
      <select className="registry-select" defaultValue={defaultValue} name={name} required={required}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    </label>
  );
}

function scheduleText(factory: Factory | null): string {
  return (factory?.operating_calendar.shifts ?? [])
    .map((shift) => `${shift.day},${shift.name},${shift.start},${shift.end}`)
    .join("\n");
}

function AssetEditor({
  editor,
  templates,
  machineStates,
  sensorUnits,
  busy,
  error,
  onCancel,
  onSave,
}: {
  editor: EditorState;
  templates: MachineTemplate[];
  machineStates: MachineStates;
  sensorUnits: SensorUnits;
  busy: boolean;
  error: string;
  onCancel: () => void;
  onSave: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const { kind, record } = editor;
  const title = `${record ? "Edit" : "Create"} ${
    kind === "factory" ? "factory" : kind === "line" ? "production line" : kind
  }`;
  const [selectedMachineType, setSelectedMachineType] = useState(
    value(record, "machine_type", "processing_station"),
  );

  return (
    <section className="mt-5 border border-rule bg-white/70 p-5 sm:p-7" aria-labelledby="asset-editor-title">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="font-mono text-xs tracking-widest text-accent">ASSET CONFIGURATION</p>
          <h3 className="mt-2 text-xl font-semibold" id="asset-editor-title">{title}</h3>
        </div>
        <button className="text-link text-sm" onClick={onCancel} type="button">Cancel</button>
      </div>
      <form className="mt-6 grid gap-5 md:grid-cols-2" onSubmit={onSave}>
        {kind === "factory" && (
          <>
            <FormField label="Factory name" name="name" defaultValue={value(record, "name")} required maxLength={160} />
            <FormField label="IANA timezone" name="timezone" defaultValue={value(record, "timezone", "UTC")} required maxLength={80} hint="for example America/Chicago" />
            <label className="form-field md:col-span-2">
              <span>Description</span>
              <textarea className="registry-textarea" defaultValue={value(record, "description")} maxLength={4000} name="description" rows={3} />
            </label>
            <SelectField
              label="Unit system"
              name="unit_system"
              defaultValue={String((record?.unit_preferences as Factory["unit_preferences"] | undefined)?.system ?? "metric")}
              options={[{ value: "metric", label: "Metric" }, { value: "imperial", label: "Imperial" }]}
            />
            <SelectField
              label="Preferred temperature"
              name="temperature"
              defaultValue={String((record?.unit_preferences as Factory["unit_preferences"] | undefined)?.temperature ?? "C")}
              options={[{ value: "C", label: "Celsius (C)" }, { value: "F", label: "Fahrenheit (F)" }]}
            />
            <label className="form-field md:col-span-2">
              <span>Operating shifts</span>
              <textarea
                className="registry-textarea font-mono"
                defaultValue={scheduleText(record as Factory | null)}
                name="shifts"
                placeholder={"0,Day shift,06:00,14:00\n0,Night shift,22:00,06:00"}
                rows={4}
              />
              <small>One per line: weekday number (0 {WEEKDAYS[0]}–6 {WEEKDAYS[6]}), name, start, end. Overnight shifts are supported.</small>
            </label>
          </>
        )}

        {kind === "line" && (
          <>
            <FormField label="Production line name" name="name" defaultValue={value(record, "name")} required maxLength={160} />
            <label className="form-field md:col-span-2">
              <span>Description</span>
              <textarea className="registry-textarea" defaultValue={value(record, "description")} maxLength={4000} name="description" rows={3} />
            </label>
          </>
        )}

        {kind === "machine" && (
          <>
            <FormField label="Machine identity" name="identity" defaultValue={value(record, "identity")} required maxLength={120} />
            <FormField label="Machine name" name="name" defaultValue={value(record, "name")} required maxLength={160} />
            <label className="form-field">
              <span>Equipment template</span>
              <select
                className="registry-select"
                name="machine_type"
                onChange={(event) => setSelectedMachineType(event.target.value)}
                value={selectedMachineType}
              >
                {[
                ...templates.map((template) => ({ value: template.key, label: template.label })),
                { value: "custom", label: "Custom station type" },
                ].map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <FormField label="Custom station type name" name="custom_type_name" defaultValue={value(record, "custom_type_name")} maxLength={120} hint="required for a custom type" />
            <FormField
              key={`${selectedMachineType}-${record?.id ?? "new"}`}
              label="Capabilities"
              name="capabilities"
              defaultValue={Array.isArray(record?.capabilities)
                ? record.capabilities.join(", ")
                : templates.find((template) => template.key === selectedMachineType)?.suggested_capabilities.join(", ") ?? ""}
              maxLength={1000}
              hint="comma-separated, descriptive only"
            />
            <SelectField
              label="Recorded operating state"
              name="operating_state"
              defaultValue={value(record, "operating_state", "offline")}
              options={Object.keys(machineStates).map((state) => ({ value: state, label: state }))}
            />
            <details className="md:col-span-2">
              <summary className="cursor-pointer font-mono text-xs tracking-wider">MACHINE STATE DEFINITIONS</summary>
              <dl className="mt-3 grid gap-2 sm:grid-cols-2">
                {Object.entries(machineStates).map(([state, description]) => (
                  <div className="border-t border-rule pt-2" key={state}>
                    <dt className="font-mono text-xs uppercase">{state}</dt>
                    <dd className="mt-1 text-sm text-ink/70">{description}</dd>
                  </div>
                ))}
              </dl>
            </details>
            <FormField label="Nominal cycle time (seconds)" name="nominal_cycle_time_seconds" defaultValue={value(record, "nominal_cycle_time_seconds")} required type="number" min={0.001} step={0.001} />
            <FormField label="Nominal capacity (units/hour)" name="capacity_per_hour" defaultValue={value(record, "capacity_per_hour")} required type="number" min={0.001} step={0.001} />
            <FormField label="Manufacturer (optional)" name="manufacturer" defaultValue={value(record, "manufacturer")} maxLength={160} />
            <FormField label="Model (optional)" name="model" defaultValue={value(record, "model")} maxLength={160} />
            <p className="md:col-span-2 border-l-2 border-accent pl-4 text-sm leading-relaxed text-ink/70">
              Templates suggest editable metadata only. Selecting equipment does not create or validate a physics model; this asset will be marked NOT VALIDATED.
            </p>
          </>
        )}

        {kind === "component" && (
          <>
            <FormField label="Component identity" name="identity" defaultValue={value(record, "identity")} required maxLength={120} />
            <FormField label="Component name" name="name" defaultValue={value(record, "name")} required maxLength={160} />
            <SelectField label="Component type" name="component_type" defaultValue={value(record, "component_type", "motor")} options={COMPONENT_TYPES.map((type) => ({ value: type, label: type }))} />
            <FormField label="Manufacturer (optional)" name="manufacturer" defaultValue={value(record, "manufacturer")} maxLength={160} />
            <FormField label="Model (optional)" name="model" defaultValue={value(record, "model")} maxLength={160} />
          </>
        )}

        {kind === "sensor" && (
          <>
            <FormField label="Sensor identity" name="identity" defaultValue={value(record, "identity")} required maxLength={120} />
            <FormField label="Sensor name" name="name" defaultValue={value(record, "name")} required maxLength={160} />
            <SelectField label="Measurement type" name="measurement_type" defaultValue={value(record, "measurement_type", "temperature")} options={MEASUREMENT_TYPES.map((type) => ({ value: type, label: type }))} />
            <FormField label="Unit" name="unit" defaultValue={value(record, "unit", "C")} required maxLength={32} hint="must match the measurement type" list="sensor-unit-options" />
            <datalist id="sensor-unit-options">
              {[...new Set(Object.values(sensorUnits).flat())].map((unit) => <option key={unit} value={unit} />)}
            </datalist>
            <FormField label="Expected reporting interval (seconds)" name="expected_reporting_interval_seconds" defaultValue={value(record, "expected_reporting_interval_seconds", "5")} required type="number" min={0.001} step={0.001} />
            <FormField label="Minimum threshold (optional)" name="threshold_minimum" defaultValue={value(record?.thresholds as RegistryAsset | null, "minimum")} type="number" step={0.001} />
            <FormField label="Maximum threshold (optional)" name="threshold_maximum" defaultValue={value(record?.thresholds as RegistryAsset | null, "maximum")} type="number" step={0.001} />
            <FormField label="Last calibrated at (ISO 8601, optional)" name="last_calibrated_at" defaultValue={value(record?.calibration as RegistryAsset | null, "last_calibrated_at")} />
            <FormField label="Calibration due at (ISO 8601, optional)" name="calibration_due_at" defaultValue={value(record?.calibration as RegistryAsset | null, "calibration_due_at")} />
            <FormField label="Calibration offset (optional)" name="calibration_offset" defaultValue={value(record?.calibration as RegistryAsset | null, "offset")} type="number" step={0.0001} />
            <FormField label="Calibration scale (optional)" name="calibration_scale" defaultValue={value(record?.calibration as RegistryAsset | null, "scale")} type="number" min={0.0001} step={0.0001} />
            <label className="form-field md:col-span-2">
              <span>Calibration notes</span>
              <textarea className="registry-textarea" defaultValue={value(record?.calibration as RegistryAsset | null, "notes")} maxLength={1000} name="calibration_notes" rows={2} />
            </label>
            <p className="md:col-span-2 text-sm text-ink/65">
              Accepted unit labels are validated by measurement type. Custom measurements require an explicit unit label.
            </p>
          </>
        )}

        <div className="flex flex-wrap items-center gap-4 md:col-span-2">
          <button className="action-button" disabled={busy} type="submit">
            {busy ? "SAVING…" : record ? "SAVE CHANGES" : `CREATE ${kind.toUpperCase()}`}
          </button>
          {error && <p className="text-sm text-red-800" role="alert">{error}</p>}
        </div>
      </form>
    </section>
  );
}

function assetPath(kind: EditorKind, id: string): string {
  const collection = {
    factory: "factories",
    line: "lines",
    machine: "machines",
    component: "components",
    sensor: "sensors",
  }[kind];
  return `/${collection}/${encodeURIComponent(id)}`;
}

function formPayload(kind: EditorKind, form: FormData): Record<string, unknown> {
  const text = (name: string) => String(form.get(name) ?? "").trim();
  const numberOrNull = (name: string) => {
    const raw = text(name);
    return raw === "" ? null : Number(raw);
  };

  if (kind === "factory") {
    const shifts = text("shifts").split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((line) => {
      const [day, name, start, end, extra] = line.split(",").map((part) => part.trim());
      if (extra !== undefined || !day || !name || !start || !end) {
        throw new Error("Each shift must be weekday number, name, start and end separated by commas.");
      }
      return { day: Number(day), name, start, end };
    });
    return {
      name: text("name"),
      timezone: text("timezone"),
      description: text("description"),
      unit_preferences: {
        system: text("unit_system"),
        temperature: text("temperature"),
      },
      operating_calendar: { shifts },
    };
  }
  if (kind === "line") {
    return { name: text("name"), description: text("description") };
  }
  if (kind === "machine") {
    return {
      identity: text("identity"),
      name: text("name"),
      machine_type: text("machine_type"),
      custom_type_name: text("custom_type_name"),
      capabilities: text("capabilities").split(",").map((part) => part.trim()).filter(Boolean),
      manufacturer: text("manufacturer"),
      model: text("model"),
      nominal_cycle_time_seconds: numberOrNull("nominal_cycle_time_seconds"),
      capacity_per_hour: numberOrNull("capacity_per_hour"),
      operating_state: text("operating_state"),
    };
  }
  if (kind === "component") {
    return {
      identity: text("identity"),
      name: text("name"),
      component_type: text("component_type"),
      manufacturer: text("manufacturer"),
      model: text("model"),
    };
  }
  return {
    identity: text("identity"),
    name: text("name"),
    measurement_type: text("measurement_type"),
    unit: text("unit"),
    expected_reporting_interval_seconds: numberOrNull("expected_reporting_interval_seconds"),
    thresholds: {
      minimum: numberOrNull("threshold_minimum"),
      maximum: numberOrNull("threshold_maximum"),
    },
    calibration: {
      last_calibrated_at: text("last_calibrated_at") || null,
      calibration_due_at: text("calibration_due_at") || null,
      offset: numberOrNull("calibration_offset"),
      scale: numberOrNull("calibration_scale"),
      notes: text("calibration_notes"),
    },
  };
}

function AssetList({
  title,
  records,
  selectedId,
  canCreate,
  canReopen,
  busy,
  onSelect,
  onCreate,
  onEdit,
  onArchive,
  onReopen,
}: {
  title: string;
  records: RegistryAsset[];
  selectedId: string | null;
  canCreate: boolean;
  canReopen: boolean;
  busy: boolean;
  onSelect: (record: RegistryAsset) => void;
  onCreate: () => void;
  onEdit: (record: RegistryAsset) => void;
  onArchive: (record: RegistryAsset) => void;
  onReopen: (record: RegistryAsset) => void;
}) {
  return (
    <section className="min-w-0 border border-rule bg-white/35" aria-label={title}>
      <div className="flex items-center justify-between gap-2 border-b border-rule px-3 py-3">
        <h3 className="font-mono text-xs tracking-wider">{title}</h3>
        {canCreate && (
          <button className="text-link font-mono text-xs" disabled={busy} onClick={onCreate} type="button">
            + ADD
          </button>
        )}
      </div>
      {records.length === 0 ? (
        <p className="px-3 py-4 text-sm text-ink/60">No records.</p>
      ) : (
        <ul className="divide-y divide-rule">
          {records.map((record) => {
            const archived = record.archived_at !== null;
            return (
              <li className="px-3 py-3" key={record.id}>
                <div className="flex items-start justify-between gap-2">
                  <button
                    className={`min-w-0 text-left text-sm ${selectedId === record.id ? "font-semibold text-accent" : "hover:text-accent"} ${archived ? "text-ink/55" : ""}`}
                    onClick={() => onSelect(record)}
                    type="button"
                  >
                    <span className="block truncate">{record.name}</span>
                    <span className="mt-1 block font-mono text-[0.65rem] uppercase tracking-wider">
                      {archived ? "ARCHIVED" : "ACTIVE"}
                    </span>
                  </button>
                  {archived ? (
                    canReopen ? (
                      <button className="text-link font-mono text-[0.65rem]" disabled={busy} onClick={() => onReopen(record)} type="button">
                        REOPEN
                      </button>
                    ) : (
                      <span className="max-w-20 text-right font-mono text-[0.6rem] text-ink/50">REOPEN PARENT FIRST</span>
                    )
                  ) : (
                    <details className="relative shrink-0">
                      <summary className="cursor-pointer font-mono text-xs" aria-label={`Actions for ${record.name}`}>···</summary>
                      <div className="absolute right-0 z-10 mt-2 grid min-w-32 gap-2 border border-rule bg-paper p-3 text-left shadow-sm">
                        <button className="text-left text-sm text-link" onClick={() => onEdit(record)} type="button">Edit</button>
                        <button className="text-left text-sm text-red-800" disabled={busy} onClick={() => onArchive(record)} type="button">Archive</button>
                      </div>
                    </details>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

export function AssetRegistry({
  role,
  onSignOut,
  onChanged,
}: {
  role: string;
  onSignOut: () => void;
  onChanged: () => void;
}) {
  const [factories, setFactories] = useState<Factory[]>([]);
  const [lines, setLines] = useState<RegistryAsset[]>([]);
  const [machines, setMachines] = useState<RegistryAsset[]>([]);
  const [components, setComponents] = useState<RegistryAsset[]>([]);
  const [sensors, setSensors] = useState<RegistryAsset[]>([]);
  const [templates, setTemplates] = useState<MachineTemplate[]>([]);
  const [machineStates, setMachineStates] = useState<MachineStates>({});
  const [sensorUnits, setSensorUnits] = useState<SensorUnits>({});
  const [factoryId, setFactoryId] = useState<string | null>(null);
  const [lineId, setLineId] = useState<string | null>(null);
  const [machineId, setMachineId] = useState<string | null>(null);
  const [componentId, setComponentId] = useState<string | null>(null);
  const [editor, setEditor] = useState<EditorState | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const canEdit = ["owner", "administrator", "engineer"].includes(role);
  const activeFactory = factories.find((item) => item.id === factoryId);
  const activeLine = lines.find((item) => item.id === lineId);
  const activeMachine = machines.find((item) => item.id === machineId);
  const activeComponent = components.find((item) => item.id === componentId);

  async function loadFactories() {
    const result = await apiRequest<{ factories: Factory[] }>("/factories?include_archived=true");
    setFactories(result.factories);
    setFactoryId((current) => current && result.factories.some((factory) => factory.id === current)
      ? current
      : result.factories.find((factory) => !factory.archived_at)?.id ?? result.factories[0]?.id ?? null);
  }

  async function loadChildren(path: string, key: string): Promise<RegistryAsset[]> {
    const result = await apiRequest<Record<string, RegistryAsset[]>>(`${path}?include_archived=true`);
    return result[key] ?? [];
  }

  useEffect(() => {
    let active = true;
    setLoading(true);
    Promise.all([
      apiRequest<{ factories: Factory[] }>("/factories?include_archived=true"),
      apiRequest<{ templates: MachineTemplate[] }>("/asset-templates"),
      apiRequest<MachineStates>("/machine-states"),
      apiRequest<SensorUnits>("/sensor-units"),
    ]).then(([factoryData, templateData, states, units]) => {
      if (!active) return;
      setFactories(factoryData.factories);
      setFactoryId(
        factoryData.factories.find((factory) => !factory.archived_at)?.id
          ?? factoryData.factories[0]?.id
          ?? null,
      );
      setTemplates(templateData.templates);
      setMachineStates(states);
      setSensorUnits(units);
      setError("");
    }).catch((reason: unknown) => {
      if (active) setError(getErrorMessage(reason));
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLines([]);
    setLineId(null);
    setMachines([]);
    setMachineId(null);
    setComponents([]);
    setComponentId(null);
    setSensors([]);
    if (!factoryId) return () => { active = false; };
    loadChildren(`/factories/${encodeURIComponent(factoryId)}/lines`, "lines")
      .then((records) => {
        if (!active) return;
        setLines(records);
        setLineId(records.find((record) => !record.archived_at)?.id ?? records[0]?.id ?? null);
      })
      .catch((reason: unknown) => {
        if (active) setError(getErrorMessage(reason));
      });
    return () => {
      active = false;
    };
  }, [factoryId]);

  useEffect(() => {
    let active = true;
    setMachines([]);
    setMachineId(null);
    setComponents([]);
    setComponentId(null);
    setSensors([]);
    if (!lineId) return () => { active = false; };
    loadChildren(`/lines/${encodeURIComponent(lineId)}/machines`, "machines")
      .then((records) => {
        if (!active) return;
        setMachines(records);
        setMachineId(records.find((record) => !record.archived_at)?.id ?? records[0]?.id ?? null);
      })
      .catch((reason: unknown) => {
        if (active) setError(getErrorMessage(reason));
      });
    return () => {
      active = false;
    };
  }, [lineId]);

  useEffect(() => {
    let active = true;
    setComponents([]);
    setComponentId(null);
    setSensors([]);
    if (!machineId) return () => { active = false; };
    loadChildren(`/machines/${encodeURIComponent(machineId)}/components`, "components")
      .then((records) => {
        if (!active) return;
        setComponents(records);
        setComponentId(records.find((record) => !record.archived_at)?.id ?? records[0]?.id ?? null);
      })
      .catch((reason: unknown) => {
        if (active) setError(getErrorMessage(reason));
      });
    return () => {
      active = false;
    };
  }, [machineId]);

  useEffect(() => {
    let active = true;
    setSensors([]);
    if (!componentId) return () => { active = false; };
    loadChildren(`/components/${encodeURIComponent(componentId)}/sensors`, "sensors")
      .then((records) => {
        if (active) setSensors(records);
      })
      .catch((reason: unknown) => {
        if (active) setError(getErrorMessage(reason));
      });
    return () => {
      active = false;
    };
  }, [componentId]);

  async function refresh(kind: EditorKind, parentId?: string) {
    if (kind === "factory") {
      await loadFactories();
      return;
    }
    if (kind === "line" && factoryId) {
      const records = await loadChildren(`/factories/${factoryId}/lines`, "lines");
      setLines(records);
      if (parentId) setLineId(parentId);
      return;
    }
    if (kind === "machine" && lineId) {
      const records = await loadChildren(`/lines/${lineId}/machines`, "machines");
      setMachines(records);
      if (parentId) setMachineId(parentId);
      return;
    }
    if (kind === "component" && machineId) {
      const records = await loadChildren(`/machines/${machineId}/components`, "components");
      setComponents(records);
      if (parentId) setComponentId(parentId);
      return;
    }
    if (kind === "sensor" && componentId) {
      setSensors(await loadChildren(`/components/${componentId}/sensors`, "sensors"));
    }
  }

  async function saveEditor(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editor) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const data = formPayload(editor.kind, new FormData(event.currentTarget));
      const collectionBase = {
        factory: "/factories",
        line: `/factories/${encodeURIComponent(editor.parentId ?? "")}/lines`,
        machine: `/lines/${encodeURIComponent(editor.parentId ?? "")}/machines`,
        component: `/machines/${encodeURIComponent(editor.parentId ?? "")}/components`,
        sensor: `/components/${encodeURIComponent(editor.parentId ?? "")}/sensors`,
      }[editor.kind];
      const path = editor.record ? assetPath(editor.kind, editor.record.id) : collectionBase;
      const saved = await apiRequest<RegistryAsset>(path, {
        method: editor.record ? "PATCH" : "POST",
        body: JSON.stringify(data),
      });
      await refresh(editor.kind, editor.record?.id ?? saved.id);
      if (editor.kind === "factory" && !editor.record) setFactoryId(saved.id);
      if (editor.kind === "line" && !editor.record) setLineId(saved.id);
      if (editor.kind === "machine" && !editor.record) setMachineId(saved.id);
      if (editor.kind === "component" && !editor.record) setComponentId(saved.id);
      setEditor(null);
      setNotice("Configuration saved.");
      onChanged();
    } catch (reason) {
      setError(getErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  async function changeLifecycle(kind: EditorKind, record: RegistryAsset, reopen: boolean) {
    if (!reopen && !window.confirm(`Archive "${record.name}"? All active assets below it will also be archived and can be reopened later.`)) {
      return;
    }
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await apiRequest(`${assetPath(kind, record.id)}${reopen ? "/reopen" : ""}`, {
        method: reopen ? "POST" : "DELETE",
      });
      await refresh(kind);
      if (kind === "factory" && !reopen && factoryId === record.id) setFactoryId(null);
      if (kind === "line" && !reopen && lineId === record.id) setLineId(null);
      if (kind === "machine" && !reopen && machineId === record.id) setMachineId(null);
      if (kind === "component" && !reopen && componentId === record.id) setComponentId(null);
      setNotice(reopen ? "Asset reopened." : "Asset archived.");
      onChanged();
    } catch (reason) {
      setError(getErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  if (loading) {
    return <p aria-live="polite" className="font-mono text-sm">LOADING FACTORY REGISTRY…</p>;
  }

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-mono text-xs tracking-widest text-ink/60">ORGANIZATION ASSET REGISTRY</p>
          <h2 className="mt-2 text-2xl font-semibold">Factories and equipment</h2>
        </div>
        <div className="flex flex-wrap gap-3">
          <button className="secondary-button" onClick={onSignOut} type="button">SIGN OUT</button>
          {canEdit && (
            <button className="action-button" onClick={() => setEditor({ kind: "factory", record: null })} type="button">
              CREATE FACTORY
            </button>
          )}
        </div>
      </div>
      {error && !editor && <p className="mt-5 border-l-2 border-red-700 pl-4 text-sm text-red-800" role="alert">{error}</p>}
      {notice && <p className="mt-5 border-l-2 border-accent pl-4 text-sm" role="status">{notice}</p>}

      {editor && (
        <AssetEditor
          busy={busy}
          editor={editor}
          error={error}
          key={`${editor.kind}-${editor.record?.id ?? "new"}`}
          machineStates={machineStates}
          onCancel={() => { setEditor(null); setError(""); }}
          onSave={(event) => void saveEditor(event)}
          sensorUnits={sensorUnits}
          templates={templates}
        />
      )}

      {factories.length === 0 ? (
        <div className="mt-6 border border-dashed border-rule p-7">
          <p className="font-semibold">No factories have been added.</p>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink/70">
            Create a factory to configure its timezone, units and operating shifts. No production data is assumed.
          </p>
        </div>
      ) : (
        <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <AssetList
            busy={busy}
            canCreate={canEdit}
            canReopen
            onArchive={(record) => void changeLifecycle("factory", record, false)}
            onCreate={() => setEditor({ kind: "factory", record: null })}
            onEdit={(record) => setEditor({ kind: "factory", record })}
            onReopen={(record) => void changeLifecycle("factory", record, true)}
            onSelect={(record) => setFactoryId(record.id)}
            records={factories}
            selectedId={factoryId}
            title="FACTORIES"
          />
          <AssetList
            busy={busy}
            canCreate={canEdit && Boolean(factoryId && !activeFactory?.archived_at)}
            canReopen={Boolean(activeFactory && !activeFactory.archived_at)}
            onArchive={(record) => void changeLifecycle("line", record, false)}
            onCreate={() => factoryId && setEditor({ kind: "line", record: null, parentId: factoryId })}
            onEdit={(record) => setEditor({ kind: "line", record })}
            onReopen={(record) => void changeLifecycle("line", record, true)}
            onSelect={(record) => setLineId(record.id)}
            records={lines}
            selectedId={lineId}
            title="PRODUCTION LINES"
          />
          <AssetList
            busy={busy}
            canCreate={canEdit && Boolean(lineId && !activeLine?.archived_at && !activeFactory?.archived_at)}
            canReopen={Boolean(activeLine && !activeLine.archived_at && activeFactory && !activeFactory.archived_at)}
            onArchive={(record) => void changeLifecycle("machine", record, false)}
            onCreate={() => lineId && setEditor({ kind: "machine", record: null, parentId: lineId })}
            onEdit={(record) => setEditor({ kind: "machine", record })}
            onReopen={(record) => void changeLifecycle("machine", record, true)}
            onSelect={(record) => setMachineId(record.id)}
            records={machines}
            selectedId={machineId}
            title="MACHINES"
          />
          <AssetList
            busy={busy}
            canCreate={canEdit && Boolean(machineId && !activeMachine?.archived_at && !activeLine?.archived_at && !activeFactory?.archived_at)}
            canReopen={Boolean(activeMachine && !activeMachine.archived_at && activeLine && !activeLine.archived_at && activeFactory && !activeFactory.archived_at)}
            onArchive={(record) => void changeLifecycle("component", record, false)}
            onCreate={() => machineId && setEditor({ kind: "component", record: null, parentId: machineId })}
            onEdit={(record) => setEditor({ kind: "component", record })}
            onReopen={(record) => void changeLifecycle("component", record, true)}
            onSelect={(record) => setComponentId(record.id)}
            records={components}
            selectedId={componentId}
            title="COMPONENTS"
          />
          <AssetList
            busy={busy}
            canCreate={canEdit && Boolean(componentId && !activeComponent?.archived_at && !activeMachine?.archived_at && !activeLine?.archived_at && !activeFactory?.archived_at)}
            canReopen={Boolean(activeComponent && !activeComponent.archived_at && activeMachine && !activeMachine.archived_at && activeLine && !activeLine.archived_at && activeFactory && !activeFactory.archived_at)}
            onArchive={(record) => void changeLifecycle("sensor", record, false)}
            onCreate={() => componentId && setEditor({ kind: "sensor", record: null, parentId: componentId })}
            onEdit={(record) => setEditor({ kind: "sensor", record })}
            onReopen={(record) => void changeLifecycle("sensor", record, true)}
            onSelect={(record) => setNotice(`${record.name}: ${String(record.measurement_type ?? "sensor")} / ${String(record.unit ?? "")}; expected every ${String(record.expected_reporting_interval_seconds ?? "")}s.`)}
            records={sensors}
            selectedId={null}
            title="SENSORS"
          />
        </div>
      )}

      {factoryId && (
        <section className="mt-6 border border-rule bg-white/35 p-5" aria-label="Selected factory details">
          {(() => {
            const factory = factories.find((item) => item.id === factoryId);
            if (!factory) return null;
            const activeCount = (factory.operating_calendar?.shifts ?? []).length;
            return (
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="font-mono text-xs tracking-wider text-ink/55">FACTORY CONFIGURATION</p>
                  <p className="mt-2 font-semibold">{factory.name}</p>
                  <p className="mt-1 text-sm text-ink/65">
                    {factory.timezone} · {factory.unit_preferences?.system} · {activeCount} configured shift{activeCount === 1 ? "" : "s"}
                  </p>
                  {factory.description && <p className="mt-2 max-w-3xl text-sm text-ink/70">{factory.description}</p>}
                </div>
                <a className="text-link text-sm" href="/api/v1/asset-audit" target="_blank" rel="noreferrer">View configuration audit</a>
              </div>
            );
          })()}
        </section>
      )}
      <p className="mt-5 text-xs leading-relaxed text-ink/60">
        Archiving preserves records and audit history. Equipment templates are metadata suggestions, not validated physics or production models.
      </p>
    </div>
  );
}
