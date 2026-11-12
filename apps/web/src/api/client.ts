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

export type Activity = components["schemas"]["Activity"];
export type ActivityPage = components["schemas"]["ActivityPage"];
export type TransactionType = components["schemas"]["TransactionType"];
export type CategoryCode = components["schemas"]["CategoryCode"];

export async function getTransactions(
  filters: {
    accountIds?: string[];
    from?: string;
    to?: string;
    status?: "ALL" | "PENDING" | "POSTED" | "CANCELLED";
    type?: TransactionType;
    category?: CategoryCode;
    search?: string;
    limit?: number;
    cursor?: string;
  },
  signal?: AbortSignal,
): Promise<ActivityPage> {
  const result = await api.GET("/api/v1/transactions", {
    params: {
      query: {
        ...(filters.accountIds?.length
          ? { accountIds: filters.accountIds.join(",") }
          : {}),
        ...(filters.from ? { from: filters.from } : {}),
        ...(filters.to ? { to: filters.to } : {}),
        ...(filters.status ? { status: filters.status } : {}),
        ...(filters.type ? { type: filters.type } : {}),
        ...(filters.category ? { category: filters.category } : {}),
        ...(filters.search ? { search: filters.search } : {}),
        ...(filters.limit ? { limit: filters.limit } : {}),
        ...(filters.cursor ? { cursor: filters.cursor } : {}),
      },
    },
    signal,
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data as unknown as ActivityPage;
}

export async function getTransaction(
  id: string,
  signal?: AbortSignal,
): Promise<Activity> {
  const result = await api.GET("/api/v1/transactions/{id}", {
    params: { path: { id } },
    signal,
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data as unknown as Activity;
}
