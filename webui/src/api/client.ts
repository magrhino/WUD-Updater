export interface PendingItem {
  line_no: number;
  raw: string;
  image: string;
  key: string;
  repo: string;
  has_tag: boolean;
  allow_repo: boolean;
  digest: string;
  desired_tag: string;
}

export interface PendingResponse {
  source_file: string;
  exists: boolean;
  count: number;
  items: PendingItem[];
  warnings: string[];
}

export interface StatusResponse {
  ok: boolean;
  version: string;
  wud_file: string;
  wud_file_exists: boolean;
  pending_count: number;
  db_path: string;
  db_ready: boolean;
  auth_required: boolean;
  dev_auth_bypass: boolean;
  setup_required: boolean;
  mutations_enabled: boolean;
  static_spa_available: boolean;
  warnings: string[];
}

export interface AuthSessionResponse {
  authenticated: boolean;
  setup_required: boolean;
  auth_required: boolean;
  dev_auth_bypass: boolean;
  mutations_enabled: boolean;
  username: string | null;
}

export interface CsrfResponse {
  csrf_token: string;
}

export interface SetupStatusResponse {
  setup_required: boolean;
  claim_required: boolean;
  authenticated: boolean;
  auth_required: boolean;
  dev_auth_bypass: boolean;
  mutations_enabled: boolean;
  password_min_length: number;
}

export interface RunSummary {
  id: number;
  started_at: string;
  finished_at: string | null;
  status: string;
  dry_run: boolean;
  mode: string;
  wud_file: string;
  log_file: string;
  metadata: Record<string, unknown>;
}

export interface PendingUpdateRecord {
  id: number;
  run_id: number;
  line_no: number;
  raw: string;
  image: string;
  target_digest: string;
  desired_tag: string;
  service_key: string;
  stack_name: string;
  service_name: string;
  status: string;
  status_reason: string;
  created_at: string;
  updated_at: string;
  metadata: Record<string, unknown>;
}

export interface RunEventRecord {
  id: number;
  run_id: number;
  created_at: string;
  service_name: string;
  stack_name: string;
  image: string;
  target_image: string;
  old_image_id: string;
  new_image_id: string;
  old_digest: string;
  new_digest: string;
  status: string;
  metadata: Record<string, unknown>;
}

export interface RunDetail extends RunSummary {
  pending_updates: PendingUpdateRecord[];
  events: RunEventRecord[];
}

export interface RunLogResponse {
  run_id: number;
  log_file: string;
  exists: boolean;
  content: string;
  truncated: boolean;
  max_bytes: number;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`/api/v1${path}`, {
    ...options,
    credentials: "include",
    headers,
  });
  const contentType = response.headers.get("content-type") ?? "";
  const body = contentType.includes("application/json")
    ? await response.json()
    : await response.text();

  if (!response.ok) {
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : `Request failed with status ${response.status}`;
    throw new ApiError(response.status, detail);
  }

  return body as T;
}

export const webApi = {
  csrf: () => apiRequest<CsrfResponse>("/auth/csrf"),
  setupStatus: () => apiRequest<SetupStatusResponse>("/setup/status"),
  setupClaim: (
    claim: string,
    username: string,
    password: string,
    csrfToken: string,
  ) =>
    apiRequest<AuthSessionResponse>("/setup/claim", {
      method: "POST",
      headers: { "x-wud-csrf-token": csrfToken },
      body: JSON.stringify({ claim, username, password }),
    }),
  session: () => apiRequest<AuthSessionResponse>("/auth/session"),
  login: (username: string, password: string, csrfToken: string) =>
    apiRequest<AuthSessionResponse>("/auth/login", {
      method: "POST",
      headers: { "x-wud-csrf-token": csrfToken },
      body: JSON.stringify({ username, password }),
    }),
  logout: (csrfToken: string) =>
    apiRequest<AuthSessionResponse>("/auth/logout", {
      method: "POST",
      headers: { "x-wud-csrf-token": csrfToken },
    }),
  status: () => apiRequest<StatusResponse>("/status"),
  pending: () => apiRequest<PendingResponse>("/pending"),
  runs: () => apiRequest<RunSummary[]>("/runs"),
  runDetail: (runId: number) => apiRequest<RunDetail>(`/runs/${runId}`),
  runLog: (runId: number, tailBytes = 262_144) =>
    apiRequest<RunLogResponse>(`/runs/${runId}/log?tail_bytes=${tailBytes}`),
};
