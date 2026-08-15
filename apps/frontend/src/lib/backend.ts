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
  refreshToken: string;
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
  const response = await fetch(`${DEFAULT_API_BASE_URL}${path}`, init);
  if (!response.ok) {
    throw new ApiError(response.status, await parseError(response));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
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

export async function refresh(refreshToken: string): Promise<TokenResponse> {
  return requestJson<TokenResponse>("/auth/refresh", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ refreshToken }),
  });
}

export async function authRequest<T>(
  path: string,
  tokens: SessionTokens,
  init: RequestInit,
  onSessionRefresh: (next: SessionTokens) => void,
): Promise<T> {
  const headers = new Headers(init.headers ?? {});
  headers.set("Authorization", `Bearer ${tokens.accessToken}`);

  const firstResponse = await fetch(`${DEFAULT_API_BASE_URL}${path}`, {
    ...init,
    headers,
  });

  if (firstResponse.status !== 401) {
    if (!firstResponse.ok) {
      throw new ApiError(firstResponse.status, await parseError(firstResponse));
    }
    if (firstResponse.status === 204) {
      return undefined as T;
    }
    return (await firstResponse.json()) as T;
  }

  const refreshed = await refresh(tokens.refreshToken);
  const nextSession: SessionTokens = {
    accessToken: refreshed.access_token,
    refreshToken: refreshed.refreshToken,
  };
  onSessionRefresh(nextSession);

  const retryHeaders = new Headers(init.headers ?? {});
  retryHeaders.set("Authorization", `Bearer ${nextSession.accessToken}`);

  const secondResponse = await fetch(`${DEFAULT_API_BASE_URL}${path}`, {
    ...init,
    headers: retryHeaders,
  });

  if (!secondResponse.ok) {
    throw new ApiError(secondResponse.status, await parseError(secondResponse));
  }
  if (secondResponse.status === 204) {
    return undefined as T;
  }
  return (await secondResponse.json()) as T;
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
      body: JSON.stringify({ importMode: "standard", sourceName }),
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
