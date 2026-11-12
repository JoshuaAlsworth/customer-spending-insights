import createClient from "openapi-fetch";
import type { components, paths } from "./generated/schema";

export type Session = components["schemas"]["Session"];
export type Account = components["schemas"]["Account"];
export type Dashboard = components["schemas"]["Dashboard"];

export class ApiError extends Error {
  constructor(readonly status: number) {
    super(`Request failed (${status})`);
  }
}

const api = createClient<paths>({
  baseUrl: location.origin,
  credentials: "same-origin",
  fetch: (input: Request) => fetch(input),
});

async function csrf() {
  const result = await api.GET("/api/v1/auth/csrf");
  if (!result.data) throw new ApiError(result.response.status);
  return result.data.token;
}

export async function login(
  loginId: string,
  password: string,
): Promise<Session> {
  const token = await csrf();
  const result = await api.POST("/api/v1/auth/login", {
    params: { header: { "X-XSRF-TOKEN": token } },
    body: { loginId, password },
  });
  if (!result.data) throw new ApiError(result.response.status);
  await csrf();
  return result.data;
}

export async function getSession() {
  const result = await api.GET("/api/v1/auth/session");
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function logout() {
  const token = await csrf();
  const result = await api.POST("/api/v1/auth/logout", {
    params: { header: { "X-XSRF-TOKEN": token } },
  });
  if (!result.response.ok) throw new ApiError(result.response.status);
}

export async function getAccounts(signal?: AbortSignal) {
  const result = await api.GET("/api/v1/accounts", { signal });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function getDashboard(
  accountIds: string[],
  from?: string,
  to?: string,
  signal?: AbortSignal,
) {
  const result = await api.GET("/api/v1/dashboard", {
    params: {
      query: {
        ...(from ? { from } : {}),
        ...(to ? { to } : {}),
        ...(accountIds.length ? { accountIds: accountIds.join(",") } : {}),
      },
    },
    signal,
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}
