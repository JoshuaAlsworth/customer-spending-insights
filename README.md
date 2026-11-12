# Customer Spending Insights

Synthetic ZAR spending dashboard with customer sign-in, account selection and exact posted-entry summaries.

## Requirements

- Java 25, Node.js 24, pnpm 12.19.0, uv with Python 3.14, and Docker Desktop with Compose.
- Copy `.env.example` to `.env` and set distinct generated `POSTGRES_PASSWORD` and `API_DB_PASSWORD` values. Keep `.env` private.

## Commands

- `./dev check` runs Java integration tests, OpenAPI generation drift, Vue/Python checks and Compose validation.
- `./dev test` reruns all Java, Vue and Python tests.
- `./dev build` builds the Java and Vue applications.
- `./dev up` runs the controlled Flyway migration and role provisioner before starting the API and web containers. Open <http://127.0.0.1:8088>.
- `./dev down` stops containers and preserves the PostgreSQL volume.
- `./dev provision <project>` re-applies the API grants after migration or password changes without resetting data.

The API never migrates or imports data on startup. The migration job runs under the separate local database administrator identity; the API identity can read customer/financial rows and maintain sessions and login-attempt state, but cannot write financial tables or perform DDL. Only the web origin publishes a loopback port. Nginx exposes `/api/v1/` and denies other `/api` and `/actuator` paths. The loopback HTTP profile sets `COOKIE_SECURE=false`; it is not the final HTTPS acceptance profile.

### Isolated test fixture

For an **isolated named Compose project only**, run `CSI_ISOLATED_TEST_DB=1 ./dev fixture <project>`. This imports a small test dataset once and rejects a different existing dataset. Repeating the same import is a no-op. Test login IDs include `fixture-f01`, `fixture-f03`, `fixture-f04`, `fixture-f09`, `fixture-empty` and `fixture-large`; their isolated-test password is `fixture-only-password`. Never use this fixture or password in an exposed environment.

## Contracts and implemented routes

`contracts/openapi.yaml` is canonical. `pnpm --filter web api:generate` creates the committed TypeScript types, and `pnpm --filter web api:check` checks drift. The browser client uses `openapi-fetch`, same-origin cookies and the `X-XSRF-TOKEN` header. Exact money values are signed decimal strings of cents.

Live routes: CSRF bootstrap, login, session, logout, owned accounts and dashboard. The dashboard uses a consistent PostgreSQL snapshot, owned account predicates, exact aggregation and Africa/Johannesburg posting dates. Its default period is the active dataset reference month. `GET /api/v1/transactions` and typed detail are reserved in the OpenAPI contract and not implemented yet; the Vue Transactions view says so explicitly. The isolated fixture checks signed spending, transfers, refund-only periods, category totals and large integer-cent values. The remaining fixture scenarios are not complete live acceptance tests.

## Kubernetes API manifest

`infra/k8s/api.yaml` defines two API replicas, resource bounds, probes, a private Service and an `/api/v1` Ingress. It expects the same built Java image imported into k3d as `customer-spending-insights-api:latest` and a namespace Secret `csi-api-db` containing `DATABASE_URL`, `DATABASE_USER`, `DATABASE_PASSWORD` and `COOKIE_SECURE`. The manifest alone does not provide a Kubernetes database, autoscaling policy or performance profile. Do not commit a generated Secret or local database address.
