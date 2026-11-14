import http from "k6/http";
import { check, fail } from "k6";
import { sleep } from "k6";
import { Counter } from "k6/metrics";

const origin = __ENV.CSI_ORIGIN;
const loginIds = (__ENV.CSI_LOGIN_IDS || "").split(",").filter(Boolean);
const password = __ENV.CSI_CUSTOMER_PASSWORD;
const rate = Number(__ENV.CSI_RATE || 10);
const duration = __ENV.CSI_DURATION || "30s";
const successfulReads = new Counter("financial_reads_successful");
const offeredReads = new Counter("financial_reads_offered");
const scenarioCounts = new Counter("financial_scenario");
const statusTotals = Object.fromEntries(
  [200, 400, 401, 403, 404, 409, 429, 500, 503, "other"].map((status) => [
    String(status),
    new Counter(`financial_status_${status}`),
  ]),
);

function monthStart(reference, offset) {
  const date = new Date(`${reference}T00:00:00Z`);
  date.setUTCDate(1);
  date.setUTCMonth(date.getUTCMonth() + offset);
  return date.toISOString().slice(0, 10);
}

function validDataset(body, expected) {
  return (
    body.dataset?.datasetId === expected.datasetId &&
    body.dataset?.instanceEpoch === expected.instanceEpoch &&
    Number.isSafeInteger(body.dataset?.customerRevision)
  );
}

function amount(value) {
  return typeof value === "string" && /^(0|-?[1-9]\d*)$/.test(value);
}

if (
  !origin ||
  loginIds.length === 0 ||
  !password ||
  !Number.isInteger(rate) ||
  rate < 1 ||
  rate > 300
) {
  throw new Error(
    "CSI_ORIGIN, CSI_LOGIN_IDS, CSI_CUSTOMER_PASSWORD and a rate from 1 to 300 are required",
  );
}

export const options = {
  noCookiesReset: true,
  summaryTrendStats: ["avg", "min", "med", "p(50)", "p(95)", "p(99)", "max"],
  scenarios: {
    financial_reads: {
      executor: "constant-arrival-rate",
      rate,
      timeUnit: "1s",
      duration,
      preAllocatedVUs: Math.max(10, Math.min(50, rate)),
      maxVUs: Math.max(20, Math.min(100, rate * 2)),
    },
  },
  thresholds: {
    "checks{kind:financial}": ["rate>0.99"],
    "financial_reads_successful{cohort:ordinary}": ["count>0"],
    "financial_reads_successful{cohort:high_activity}": ["count>0"],
    "financial_scenario{scope:all}": ["count>0"],
    "financial_scenario{scope:single}": ["count>0"],
    "financial_scenario{period:current}": ["count>0"],
    "financial_scenario{period:previous}": ["count>0"],
    "financial_scenario{period:wide}": ["count>0"],
    "financial_scenario{page:deep}": ["count>0"],
    dropped_iterations: ["count==0"],
    "http_req_duration{name:dashboard}": ["p(95)<300", "p(99)<1000"],
    "http_req_duration{name:transactions}": ["p(95)<300", "p(99)<1000"],
    "http_req_duration{name:detail}": ["p(95)<300", "p(99)<1000"],
  },
};

export function setup() {
  const sessions = [];
  for (const loginId of loginIds) {
    for (let session = 0; session < 4; session += 1) {
      http.cookieJar().clear(origin);
      const csrf = http.get(`${origin}/api/v1/auth/csrf`, {
        tags: { name: "csrf" },
      });
      if (csrf.status !== 200) fail(`CSRF bootstrap failed: ${csrf.status}`);
      const token = csrf.json("token");
      const login = http.post(
        `${origin}/api/v1/auth/login`,
        JSON.stringify({ loginId, password }),
        {
          headers: {
            "Content-Type": "application/json",
            "X-XSRF-TOKEN": token,
          },
          tags: { name: "login" },
        },
      );
      if (login.status !== 200) fail(`Authentication failed: ${login.status}`);
      const sessionCookie = login.cookies.SESSION?.[0]?.value;
      if (!sessionCookie) fail("Authentication returned no session cookie");
      const cookie = `SESSION=${sessionCookie}`;
      const headers = { Cookie: cookie };
      const accountsResponse = http.get(`${origin}/api/v1/accounts`, {
        headers,
        tags: { name: "setup_accounts" },
      });
      if (accountsResponse.status !== 200)
        fail(`Setup accounts failed: ${accountsResponse.status}`);
      const accounts = accountsResponse.json();
      const accountIds = accounts.accounts?.map((account) => account.id);
      if (!accountIds?.length || !validDataset(accounts, accounts.dataset))
        fail("Setup accounts lacked owned IDs or dataset identity");
      const dataset = accounts.dataset;
      const reference = dataset.referenceDate;
      const periods = [
        { label: "current", from: monthStart(reference, 0), to: reference },
        {
          label: "previous",
          from: monthStart(reference, -1),
          to: "",
        },
        { label: "wide", from: monthStart(reference, -11), to: reference },
      ];
      const previousEnd = new Date(`${monthStart(reference, 0)}T00:00:00Z`);
      previousEnd.setUTCDate(0);
      periods[1].to = previousEnd.toISOString().slice(0, 10);
      const cases = [
        { scope: "all", period: periods[0] },
        { scope: "single", period: periods[1] },
        { scope: "all", period: periods[2] },
        { scope: "single", period: periods[2] },
      ].map(({ scope, period }) => ({
        scope,
        period: period.label,
        accountIds: scope === "all" ? accountIds : [accountIds[0]],
        query: `from=${period.from}&to=${period.to}${scope === "single" ? `&accountIds=${encodeURIComponent(accountIds[0])}` : ""}`,
      }));
      const historyCases = [];
      const detailIds = [];
      for (const selected of cases) {
        const base = `status=POSTED&limit=25&${selected.query}`;
        const first = http.get(`${origin}/api/v1/transactions?${base}`, {
          headers,
          tags: { name: "setup_transactions" },
        });
        if (first.status !== 200 || !validDataset(first.json(), dataset))
          fail(`Setup transactions failed: ${first.status}`);
        const page = first.json();
        detailIds.push(...page.items.map((item) => item.id));
        historyCases.push({ ...selected, query: base, page: "first" });
        if (page.nextCursor) {
          historyCases.push({
            ...selected,
            query: `${base}&cursor=${encodeURIComponent(page.nextCursor)}`,
            page: "deep",
          });
        }
      }
      if (detailIds.length === 0)
        fail("Benchmark customer has no posted entries");
      sessions.push({
        cookie,
        detailIds,
        accountIds,
        dataset,
        dashboardCases: cases,
        historyCases,
        cohort: loginId === loginIds[0] ? "ordinary" : "high_activity",
      });
      sleep(1.1);
    }
  }
  for (const session of sessions) {
    http.cookieJar().clear(origin);
    const probe = http.get(`${origin}/api/v1/auth/session`, {
      headers: { Cookie: session.cookie },
      tags: { name: "setup_session" },
    });
    if (probe.status !== 200)
      fail(`Prepared session is not valid: ${probe.status}`);
  }
  return { sessions };
}

export default function (data) {
  http.cookieJar().clear(origin);
  const session = data.sessions[(__ITER + __VU) % data.sessions.length];
  const headers = { Cookie: session.cookie };
  const choice = Math.random();
  offeredReads.add(1);
  let response;
  let endpoint;
  let requestedId;
  let selected;
  if (choice < 0.45) {
    endpoint = "dashboard";
    selected =
      session.dashboardCases[
        Math.floor(Math.random() * session.dashboardCases.length)
      ];
    response = http.get(`${origin}/api/v1/dashboard?${selected.query}`, {
      headers,
      tags: { name: endpoint, cohort: session.cohort },
    });
  } else if (choice < 0.9) {
    endpoint = "transactions";
    selected =
      session.historyCases[
        Math.floor(Math.random() * session.historyCases.length)
      ];
    response = http.get(`${origin}/api/v1/transactions?${selected.query}`, {
      headers,
      tags: { name: endpoint, cohort: session.cohort },
    });
  } else {
    endpoint = "detail";
    requestedId =
      session.detailIds[Math.floor(Math.random() * session.detailIds.length)];
    response = http.get(`${origin}/api/v1/transactions/${requestedId}`, {
      headers,
      tags: { name: endpoint, cohort: session.cohort },
    });
  }
  const status = [200, 400, 401, 403, 404, 409, 429, 500, 503].includes(
    response.status,
  )
    ? String(response.status)
    : "other";
  statusTotals[status].add(1);
  scenarioCounts.add(1, {
    endpoint,
    scope: selected?.scope || "owned_detail",
    period: selected?.period || "selected",
    page: selected?.page || "none",
    cohort: session.cohort,
  });
  let valid = false;
  if (response.status === 200) {
    try {
      const body = response.json();
      valid =
        (endpoint === "dashboard" &&
          validDataset(body, session.dataset) &&
          Array.isArray(body.scope?.accountIds) &&
          body.scope.accountIds.length === selected.accountIds.length &&
          body.scope.accountIds.every((id) =>
            selected.accountIds.includes(id),
          ) &&
          [
            "incomeMinor",
            "grossSpendingMinor",
            "spendingCreditsMinor",
            "netSpendingMinor",
            "ownAccountFlowMinor",
            "netMovementMinor",
          ].every((key) => amount(body.summary?.[key])) &&
          Array.isArray(body.categories) &&
          Array.isArray(body.trend)) ||
        (endpoint === "transactions" &&
          validDataset(body, session.dataset) &&
          Array.isArray(body.items) &&
          body.items.every(
            (item) =>
              selected.accountIds.includes(item.accountId) &&
              item.recordKind === "POSTED_ENTRY" &&
              item.status === "POSTED" &&
              amount(item.amountMinor) &&
              typeof item.id === "string" &&
              typeof item.postedAt === "string",
          )) ||
        (endpoint === "detail" &&
          body.id === requestedId &&
          session.accountIds.includes(body.accountId) &&
          body.recordKind === "POSTED_ENTRY" &&
          amount(body.amountMinor));
    } catch (_) {
      valid = false;
    }
  }
  check(
    response,
    { "successful authenticated financial read": () => valid },
    { kind: "financial", endpoint, cohort: session.cohort },
  );
  if (valid) {
    successfulReads.add(1, { cohort: session.cohort, endpoint });
  }
  if (!valid && __ITER < 3) {
    console.error(
      `Financial ${endpoint} failed with HTTP ${response.status} or invalid response`,
    );
  }
}
