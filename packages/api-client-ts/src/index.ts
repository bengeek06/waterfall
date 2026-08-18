import createClient from "openapi-fetch";

import type { components, paths } from "./generated/api-types.js";

export type { components, paths };

export const DEFAULT_API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export function createWaterfallClient(baseUrl: string = DEFAULT_API_BASE_URL) {
  return createClient<paths>({ baseUrl });
}
