import createClient from "openapi-fetch";
import type { components, paths } from "./generated/schema";

export type Session = components["schemas"]["Session"];
export type Account = components["schemas"]["Account"];
export type AccountsResponse = components["schemas"]["AccountsResponse"];
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
  const data = result.data;
  const amount = (value: unknown) =>
    typeof value === "string" && /^(0|-?[1-9]\d*)$/.test(value);
  if (
    !Array.isArray(data.accounts) ||
    !/^\d{4}-\d{2}-\d{2}$/.test(data.balanceAsOfDate) ||
    data.currency !== "ZAR" ||
    !data.dataset ||
    typeof data.dataset.datasetId !== "string" ||
    typeof data.dataset.instanceEpoch !== "string" ||
    !Number.isSafeInteger(data.dataset.customerRevision) ||
    data.dataset.referenceDate !== data.balanceAsOfDate ||
    (data.accounts.length === 0
      ? data.combinedPostedBalanceMinor !== null
      : !amount(data.combinedPostedBalanceMinor)) ||
    data.accounts.some((account) => !amount(account.postedBalanceMinor))
  )
    throw new ApiError(502);
  return data;
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

type Authorization = Extract<Activity, { recordKind: "AUTHORIZATION" }>;
type PostedEntry = Extract<Activity, { recordKind: "POSTED_ENTRY" }>;
type AuthorizationResponse = Omit<
  Authorization,
  "postedAt" | "amountMinor" | "effectGroup" | "categoryCode"
> &
  Partial<
    Pick<
      Authorization,
      "postedAt" | "amountMinor" | "effectGroup" | "categoryCode"
    >
  >;

function activity(response: AuthorizationResponse | PostedEntry): Activity {
  if (response.recordKind === "POSTED_ENTRY") return response;
  if (response.recordKind !== "AUTHORIZATION")
    throw new Error("Invalid activity response");
  for (const field of [
    "postedAt",
    "amountMinor",
    "effectGroup",
    "categoryCode",
  ] as const) {
    if (!Object.hasOwn(response, field) || response[field] !== null) {
      throw new Error(`Invalid authorization response: ${field}`);
    }
  }
  return {
    ...response,
    postedAt: null,
    amountMinor: null,
    effectGroup: null,
    categoryCode: null,
  };
}

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
  return { ...result.data, items: result.data.items.map(activity) };
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
  return activity(result.data);
}
