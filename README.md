# Customer Spending Insights

Synthetic ZAR spending dashboard with customer sign-in, exact posted-entry summaries and transaction history.

## Requirements

- Java 25, Node.js 24, pnpm 12.19.0, uv with Python 3.14, and Docker Desktop with Compose.
- Copy `.env.example` to `.env` and set distinct generated `POSTGRES_PASSWORD` and `API_DB_PASSWORD` values. Set `CURSOR_SECRET` to the output of `openssl rand -hex 32`: exactly 64 hexadecimal characters encoding 32 random bytes. Keep `.env` private. Use one shared cursor secret across API replicas serving the same dataset; rotating it invalidates existing pagination cursors.

## Commands

- `./dev check` runs Java formatting and integration tests, OpenAPI generation drift, Vue lint/format/type checks and tests, Python lint/format checks and regressions, and Compose validation.
- `./dev format` applies Spotless to Java, Prettier to web source and Ruff to Python.
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

Live routes: CSRF bootstrap, login, session, logout, owned accounts, dashboard, canonical transaction history and typed transaction detail. The dashboard uses a consistent PostgreSQL snapshot, owned account predicates, exact aggregation and Africa/Johannesburg posting dates. Its default period is the active dataset reference month. The Transactions view combines provisional authorisations and posted entries with status, type, category and search filters; forward cursors bind to customer scope and dataset revision. Overview shows the four latest posted entries from the same endpoint. The API has no public financial write or simulator route. The isolated fixture covers signed spending, transfers, refunds, provisional activity and large integer-cent values. CI also runs a browser check against a disposable Compose fixture.

## Kubernetes API manifest

`infra/k8s/api.yaml` defines two API replicas, resource bounds, probes, a private Service and an `/api/v1` Ingress. It expects the same built Java image imported into k3d as `customer-spending-insights-api:latest`, a namespace Secret `csi-api-db` containing `DATABASE_URL`, `DATABASE_USER`, `DATABASE_PASSWORD` and `COOKIE_SECURE`, and a separate namespace Secret `csi-api-cursor` containing `CURSOR_SECRET`. Generate its value once with `openssl rand -hex 32` and provide the same value to both replicas. The manifest alone does not provide a Kubernetes database, autoscaling policy or performance profile. Do not commit generated Secrets or local database addresses.

## Synthetic datasets

`./dev data:generate demo generated-data/demo` creates the deterministic 20-customer demonstration CSVs and manifest. `./dev data:generate benchmark generated-data/benchmark` creates the separate benchmark profile after a free-disk preflight. Generated files stay under ignored `generated-data/`. `./dev data:validate generated-data/demo` checks hashes, canonical CSV structure, policy rules and relationships before import.

For a deliberate import, first run `./dev provision <project>`, then `./dev data:import generated-data/demo <project> <project>`. The dataset directory may also be an absolute path, including one with spaces. The importer prompts for a synthetic login password (or reads `CSI_CUSTOMER_PASSWORD`) and requires an existing `.env`. It uses the database owner, validates the seed, streams each CSV into PostgreSQL staging while hashing the consumed bytes, and sends `COMMIT` only after every digest matches the manifest. An identical seed is a non-destructive no-op; a different seed is rejected on an occupied database. The operator must use a separately targeted environment; the importer does not reset data or start the normal API. `./dev data:demo <project> <project>` and `./dev data:benchmark <project> <project>` combine generation, validation and this explicit import; the repeated project name confirms the target. Do not use a synthetic password from a shared or exposed environment.

The demo login IDs are `synthetic-00001` through `synthetic-00020`. Customer 1 has no accounts, customer 2 has an empty account, and customer 3 has pending-only activity. The benchmark is a synthetic load dataset, not a measurement of real customer behaviour. Neither profile seeds on `./dev up`.
