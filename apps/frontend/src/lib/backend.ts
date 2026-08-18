import { DEFAULT_API_BASE_URL } from "@rebirth/api-client";

import type { SessionTokens } from "./session";

export type AuthUser = {
  id: number;
  email: string;
  is_active: boolean;
};

export type AuthUserAdmin = {
  id: number;
  email: string;
  is_active: boolean;
  is_admin: boolean;
  failed_login_attempts: number;
  locked_until: string | null;
  created_at: string;
  updated_at: string;
};

export type ResourceNode = {
  id: number;
  parent_id: number | null;
  code: string;
  name: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type ResourceRole = {
  id: number;
  node_id: number;
  cost_category_id: number;
  code: string;
  name: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type CostCategory = {
  id: number;
  code: string;
  name: string;
  calendar_code: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

export type CostRate = {
  id: number;
  cost_category_id: number;
  year: number;
  hourly_rate: string;
  currency_code: string;
  created_at: string;
  updated_at: string;
};

export type InflationRate = {
  id: number;
  year: number;
  coefficient: string;
  created_at: string;
  updated_at: string;
};

export type RoleCapacity = {
  id: number;
  role_id: number;
  period_start: string;
  period_end: string;
  person_count: string;
  available_hours: string;
  created_at: string;
  updated_at: string;
};

export type Project = {
  id: number;
  name: string;
  source_version: number;
  save_version_out: number;
  schedule_from_start: boolean;
  start_date: string | null;
  finish_date: string | null;
  currency_code: string | null;
};

export type Task = {
  id: number;
  project_id: number;
  uid: number;
  id_display: number | null;
  name: string;
  outline_number: string | null;
  outline_level: number | null;
  start_at: string | null;
  finish_at: string | null;
  percent_complete: number | null;
  is_summary: boolean;
  is_milestone: boolean;
  description: string | null;
};

export type ImportBatch = {
  id: number;
  status: "pending" | "running" | "success" | "failed";
  sourceName: string | null;
};

export type ImportBatchStatus = {
  id: number;
  status: "pending" | "running" | "success" | "failed";
  projectId: number | null;
  errorMessage: string | null;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
  expiresIn: number;
};

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function parseError(response: Response): Promise<string> {
  const text = await response.text();
  if (!text) {
    return `HTTP ${response.status}`;
  }

  try {
    const payload = JSON.parse(text) as { detail?: string; message?: string };
    return payload.detail ?? payload.message ?? text;
  } catch {
    return text;
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${DEFAULT_API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
  });
  if (!response.ok) {
    throw new ApiError(response.status, await parseError(response));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

async function authFetch(
  path: string,
  tokens: SessionTokens,
  init: RequestInit,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<Response> {
  const headers = new Headers(init.headers ?? {});
  headers.set("Authorization", `Bearer ${tokens.accessToken}`);

  const firstResponse = await fetch(`${DEFAULT_API_BASE_URL}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

  if (firstResponse.status !== 401) {
    if (!firstResponse.ok) {
      throw new ApiError(firstResponse.status, await parseError(firstResponse));
    }
    return firstResponse;
  }

  const refreshed = await refresh();
  const nextSession: SessionTokens = {
    accessToken: refreshed.access_token,
  };
  onSessionRefresh(nextSession);

  const retryHeaders = new Headers(init.headers ?? {});
  retryHeaders.set("Authorization", `Bearer ${nextSession.accessToken}`);

  const secondResponse = await fetch(`${DEFAULT_API_BASE_URL}${path}`, {
    ...init,
    headers: retryHeaders,
    credentials: "include",
  });

  if (!secondResponse.ok) {
    throw new ApiError(secondResponse.status, await parseError(secondResponse));
  }
  return secondResponse;
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const body = new URLSearchParams();
  body.set("username", email);
  body.set("password", password);

  return requestJson<TokenResponse>("/auth/token", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: body.toString(),
  });
}

export async function refresh(): Promise<TokenResponse> {
  return requestJson<TokenResponse>("/auth/refresh", {
    method: "POST",
  });
}

export async function authRequest<T>(
  path: string,
  tokens: SessionTokens,
  init: RequestInit,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<T> {
  const response = await authFetch(path, tokens, init, onSessionRefresh);
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function authDownload(
  path: string,
  tokens: SessionTokens,
  init: RequestInit,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<Blob> {
  const response = await authFetch(path, tokens, init, onSessionRefresh);
  return await response.blob();
}

export function getMe(tokens: SessionTokens, onSessionRefresh: (next: SessionTokens) => void) {
  return authRequest<AuthUser>("/auth/me", tokens, { method: "GET" }, onSessionRefresh);
}

export function getUsers(
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<AuthUserAdmin[]>("/auth/users", tokens, { method: "GET" }, onSessionRefresh);
}

export function createUser(
  email: string,
  password: string,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<AuthUserAdmin>(
    "/auth/users",
    tokens,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email, password }),
    },
    onSessionRefresh,
  );
}

export function deleteUser(
  userId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<void>(
    `/auth/users/${userId}`,
    tokens,
    { method: "DELETE" },
    onSessionRefresh,
  );
}

export function getResourceNodes(tokens: SessionTokens, onSessionRefresh: (next: SessionTokens) => void) {
  return authRequest<ResourceNode[]>("/resources/nodes", tokens, { method: "GET" }, onSessionRefresh);
}

export function createResourceNode(
  payload: { code: string; name: string; parent_id?: number | null },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<ResourceNode>(
    "/resources/nodes",
    tokens,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    onSessionRefresh,
  );
}

export function getResourceRoles(tokens: SessionTokens, onSessionRefresh: (next: SessionTokens) => void) {
  return authRequest<ResourceRole[]>("/resources/roles", tokens, { method: "GET" }, onSessionRefresh);
}

export function createResourceRole(
  payload: { code: string; name: string; node_id: number; cost_category_id: number },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<ResourceRole>(
    "/resources/roles",
    tokens,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    onSessionRefresh,
  );
}

export function getCostCategories(tokens: SessionTokens, onSessionRefresh: (next: SessionTokens) => void) {
  return authRequest<CostCategory[]>("/resources/categories", tokens, { method: "GET" }, onSessionRefresh);
}

export function createCostCategory(
  payload: { code: string; name: string; calendar_code?: string | null },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<CostCategory>(
    "/resources/categories",
    tokens,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    onSessionRefresh,
  );
}

export function getCostRates(tokens: SessionTokens, onSessionRefresh: (next: SessionTokens) => void) {
  return authRequest<CostRate[]>("/resources/rates", tokens, { method: "GET" }, onSessionRefresh);
}

export function createCostRate(
  payload: { cost_category_id: number; year: number; hourly_rate: string; currency_code: string },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<CostRate>(
    "/resources/rates",
    tokens,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    onSessionRefresh,
  );
}

export function getInflationRates(tokens: SessionTokens, onSessionRefresh: (next: SessionTokens) => void) {
  return authRequest<InflationRate[]>("/resources/inflation", tokens, { method: "GET" }, onSessionRefresh);
}

export function setInflationRate(
  year: number,
  coefficient: string,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<InflationRate>(
    `/resources/inflation/${year}`,
    tokens,
    { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ coefficient }) },
    onSessionRefresh,
  );
}

export function getRoleCapacities(tokens: SessionTokens, onSessionRefresh: (next: SessionTokens) => void) {
  return authRequest<RoleCapacity[]>("/resources/capacities", tokens, { method: "GET" }, onSessionRefresh);
}

export function createRoleCapacity(
  payload: {
    role_id: number;
    period_start: string;
    period_end: string;
    person_count: string;
    available_hours: string;
  },
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<RoleCapacity>(
    "/resources/capacities",
    tokens,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) },
    onSessionRefresh,
  );
}

export function setUserStatus(
  userId: number,
  isActive: boolean,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<AuthUserAdmin>(
    `/auth/users/${userId}/status`,
    tokens,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ is_active: isActive }),
    },
    onSessionRefresh,
  );
}

export function setUserRole(
  userId: number,
  isAdmin: boolean,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<AuthUserAdmin>(
    `/auth/users/${userId}/role`,
    tokens,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ is_admin: isAdmin }),
    },
    onSessionRefresh,
  );
}

export function getProjects(
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<Project[]>("/projects", tokens, { method: "GET" }, onSessionRefresh);
}

export function createProject(
  name: string,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<Project>(
    "/projects",
    tokens,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ name }),
    },
    onSessionRefresh,
  );
}

export function updateProjectName(
  projectId: number,
  name: string,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<Project>(
    `/projects/${projectId}`,
    tokens,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ name }),
    },
    onSessionRefresh,
  );
}

export function deleteProject(
  projectId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<void>(
    `/projects/${projectId}`,
    tokens,
    {
      method: "DELETE",
    },
    onSessionRefresh,
  );
}

export function createImportBatch(
  projectId: number,
  sourceName: string,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<ImportBatch>(
    "/imports/v1/batches",
    tokens,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ projectId, importMode: "standard", sourceName }),
    },
    onSessionRefresh,
  );
}

export function uploadImportSourceXml(
  batchId: number,
  file: File,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  const form = new FormData();
  form.append("file", file, file.name);
  return authRequest<ImportBatch>(
    `/imports/v1/batches/${batchId}/xml`,
    tokens,
    {
      method: "POST",
      body: form,
    },
    onSessionRefresh,
  );
}

export function runImportBatch(
  batchId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<{ batchId: number }>(
    `/imports/v1/batches/${batchId}/run`,
    tokens,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ dryRun: false, failFast: true }),
    },
    onSessionRefresh,
  );
}

export function getImportBatchStatus(
  batchId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<ImportBatchStatus>(
    `/imports/v1/batches/${batchId}`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
}

export function getProjectTasks(
  projectId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<Task[]>(
    `/projects/${projectId}/tasks`,
    tokens,
    { method: "GET" },
    onSessionRefresh,
  );
}

export function updateTaskDescription(
  projectId: number,
  taskUid: number,
  description: string | null,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authRequest<Task>(
    `/projects/${projectId}/tasks/${taskUid}`,
    tokens,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ description }),
    },
    onSessionRefresh,
  );
}

export function exportProjectXml(
  projectId: number,
  tokens: SessionTokens,
  onSessionRefresh: (next: SessionTokens) => void,
) {
  return authDownload(`/projects/${projectId}/export.xml`, tokens, { method: "GET" }, onSessionRefresh);
}
