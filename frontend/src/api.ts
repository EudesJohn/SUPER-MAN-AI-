// Typed contract with the FastAPI backend (spec section 30: API CONTRACT).
export interface Requirement {
  id: string;
  description: string;
  quantity: string | null;
  value: number | null;
  raw_value: string | null;
  unit: string | null;
  priority: string;
  confidence: number;
  status: string;
}

export interface TaskView {
  id: string;
  title: string;
  agent: string;
  status: string;
}

export interface VerificationView {
  id: string;
  subject: string;
  outcome: "PASS" | "FAIL" | "WARNING" | "UNKNOWN";
  detail: string;
}

export interface VersionView {
  id: string;
  number: number;
  summary: string;
}

export interface ComponentView {
  id: string;
  type: string;
  requirement: string;
  status: "SOURCED" | "INSUFFICIENT_SOURCES" | "INCONNU";
  confidence: number;
  note: string;
  manufacturer_domains: string[];
  sources: string[];
}

export interface ExecuteResult {
  project_id: string;
  name?: string;
  requirements: Requirement[];
  known_gaps: string[];
  power_w: number | null;
  tasks: TaskView[];
  verifications: VerificationView[];
  component?: ComponentView | null;
  versions?: VersionView[];
  version?: VersionView;
  all_verifications_pass: boolean;
}

export interface Project {
  id: string;
  name: string;
  description: string;
  created_at: string;
}

export interface BusEvent {
  kind: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

export interface ToolInfo {
  name: string;
  risk: string;
  description: string;
}

export interface CadFileInfo {
  path: string;
  triangles: number;
  color: string;
  checksum: string;
}

export interface CadPart {
  name: string;
  group: string;
  triangles: number;
  mass_kg: number;
  center_of_mass_mm: number[];
  note: string;
}

export interface ElecCircuit {
  name: string;
  description: string;
  kind: string;
  load_w: number | null;
  current_a: number;
  length_m: number;
  gauge_mm2: number;
  capacity_a: number;
  drop_v: number;
  drop_pct: number;
  fuse_a: number | null;
  fuse_exception: string | null;
  ground: string;
  color: string;
}

export interface TractorVerification {
  id: string;
  subject: string;
  outcome: string;
  detail: string;
}

export interface DrawingInfo {
  sheet: string;
  title: string;
  dxf: string;
  svg: string;
  edges: number;
  dims: number;
  note: string;
}

export interface WireRow {
  id: string;
  de: string;
  vers: string;
  circuit: string;
  a: string;
  mm2: string;
  couleur: string;
  fusible: string;
  layer: string;
}

export interface DeliverablesInfo {
  folder: string;
  layout: { "3d": string; "2d": string; data: string };
  assembly_3d_dxf: string;
  part_3d_dxf: { part: string; path: string; triangles: number }[];
  parts_count: number;
  combined_2d_dxf: string | null;
  bom_csv: string;
  wiring_csv: string;
  circuits_csv: string | null;
  verifications_csv: string | null;
  index_csv: string;
  readme: string;
  zip: string;
  zip_bytes: number;
  file_count: number;
  note: string;
}

export interface TractorBuildResult {
  project_id: string;
  cad: {
    files: Record<string, CadFileInfo>;
    parts: CadPart[];
    total_mass_kg: number;
    total_triangles: number;
  };
  deliverables?: DeliverablesInfo;
  electrical_design: {
    system_voltage: number;
    battery: { capacity_ah: number };
    alternator: { max_current_a: number };
    circuits: ElecCircuit[];
    notes: string[];
  };
  wire_schedule?: WireRow[];
  drawings?: DrawingInfo[];
  verifications: TractorVerification[];
  cad_notes: string[];
  version: { number: number };
}

export interface CarBuildResult {
  project_id: string;
  kind: "aero_car";
  scenario: {
    scenario: {
      mass_kg: number; cd: number; frontal_area_m2: number;
      vmax_kmh: number; cruise_kmh: number; accel_100_time_s: number;
      motor_kw: number; battery_kwh: number; consumption_wh_per_km: number;
    };
    aero: { drag_vmax_N: number; power_vmax_W: number; drag_cruise_N: number;
            power_cruise_W: number; power_roll_cruise_W: number; total_cruise_W: number };
    acceleration: { mean_wheel_power_W: number };
    consistency: {
      motor_ok: boolean; required_motor_kw: number; motor_margin_kw: number;
      range_km: number; range_target_km: number; range_ok: boolean;
      pack_mass_kg: number; mass_check_kg: number; note: string;
    };
  };
  hv: {
    system_voltage: number; network: string;
    circuits: (ElecCircuit & { parallel_per_pole: number })[];
    max_drop_pct: number; notes: string[];
  };
  lv: {
    system_voltage: number;
    battery: { capacity_ah: number };
    alternator: { max_current_a: number };
    circuits: ElecCircuit[];
    notes: string[];
  };
  cad: {
    files: Record<string, CadFileInfo>;
    parts: CadPart[];
    total_mass_kg: number;
    total_triangles: number;
  };
  drawings?: DrawingInfo[];
  deliverables: DeliverablesInfo;
  verifications: TractorVerification[];
  cad_notes: string[];
  version: { number: number };
}

const base = "/api";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${base}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const Api = {
  health: () => api<{ status: string; mode: string }>("/health"),
  listProjects: () => api<Project[]>("/projects"),
  createProject: (name: string, description: string) =>
    api<Project>("/projects", { method: "POST", body: JSON.stringify({ name, description }) }),
  execute: (pid: string, cahierDesCharges: string) =>
    api<ExecuteResult>(`/projects/${pid}/execute`, {
      method: "POST",
      body: JSON.stringify({ cahier_des_charges: cahierDesCharges }),
    }),
  summary: (pid: string) => api<ExecuteResult>(`/projects/${pid}/summary`),
  report: (pid: string) =>
    api<{ path: string; content: string }>(`/projects/${pid}/report`),
  tools: () => api<ToolInfo[]>("/tools"),
  tractor: (pid: string) =>
    api<TractorBuildResult>(`/projects/${pid}/tractor`, { method: "POST", body: "{}" }),
  getTractor: (pid: string) =>
    fetch(Api.artifactUrl(`${pid}/cad/tractor/tractor_build.json`)).then(
      (x) => (x.ok ? (x.json() as Promise<TractorBuildResult>) : null)
    ),
  car: (pid: string) =>
    api<CarBuildResult>(`/projects/${pid}/car`, { method: "POST", body: "{}" }),
  getCar: (pid: string) =>
    fetch(Api.artifactUrl(`${pid}/cad/car/car_build.json`)).then(
      (x) => (x.ok ? (x.json() as Promise<CarBuildResult>) : null)
    ),
  ask: (pid: string, question: string) =>
    api<
      | {
          project_id: string;
          question: string;
          intent: "question";
          answer: string;
          grounding: string;
        }
      | {
          project_id: string;
          question: string;
          intent: "design";
          answer: string;
          deliverables: DeliverablesInfo;
          parts_count: number;
          version: { number: number };
          grounding: string;
        }
    >(`/projects/${pid}/ask`, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
  artifactUrl: (path: string) => `${base}/artifacts/${path}`,
};
