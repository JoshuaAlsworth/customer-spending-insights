# Customer Spending Insights

A synthetic ZAR dashboard for customer sign-in, exact posted balances, spending summaries and transaction history. Overview shows current-period totals and recent posted entries. Transactions adds account, status, type, category and search filters, transaction detail, and pending authorisations. All money is stored and returned in integer cents.

## Quick start

Start Docker Desktop, then run from the repository root:

```sh
./dev up
```

The first run creates private local secrets, starts PostgreSQL, applies seven Flyway migrations, provisions the restricted API role, generates and validates the deterministic 20-customer demo dataset, imports it once, builds the application images and waits for healthy services. Open <http://127.0.0.1:8088>. No host Java, Node, pnpm, Python or uv installation is needed for startup. The only host requirements are a POSIX shell and Docker with Compose.

For a busy port, choose one explicitly: `CSI_WEB_PORT=8089 ./dev up`. The web port binds to loopback only. Use the same `CSI_WEB_PORT` value for later `up` calls. To isolate an experiment, set `CSI_COMPOSE_PROJECT` consistently on each command; it gets its own database volume, generated data and local demo login file. Port conflicts fail before starting that project's database. `./dev down` stops the selected project without removing its volume. `./dev status` shows container health; `./dev logs` shows the latest 80 lines from the database, API and web services. `./dev help` lists the command surface.

For a separate local HTTPS security check, run `./dev secure:up csi-secure-check` and open <https://localhost:8443>. Use `CSI_HTTPS_PORT` to select a different loopback port. The command creates a project-local self-signed certificate under ignored `.local-certs/<project>/`; trust that certificate explicitly in the test browser or pass it with `curl --cacert`. The secure profile enables Secure cookies and serves only the TLS port. Keep the private key local and use a trusted certificate for any deployment beyond this local test. Ordinary `./dev up` remains the HTTP developer profile.

An existing dataset and its instance epoch, seed hash, customer revisions, simulator events and credentials are retained on restart. An interrupted temporary generation can be retried; an invalid canonical dataset directory fails validation instead of being silently replaced. An occupied database without a dataset identity also fails closed. Neither `up` nor `down` deletes a volume. For a disposable experiment, stop the explicitly named project first; remove its named volume, ignored generated-data directory and `.env.demo.<project>` only after confirming that project's data is no longer needed.

## Sign in and use the dashboard

Run `./dev credentials` to display the project-local synthetic password. Sign in as `synthetic-00004`. The generated password is separate from the database and simulator passwords and is stored in an ignored, mode-600 `.env.demo.<project>` file. Existing databases without that file retain their original synthetic login; startup does not reset it. The first-run `.env` contains independently generated infrastructure secrets and is also ignored and mode 600. Startup rejects an API password that no longer matches an existing database role instead of rotating it. Keep both files private.

On Overview, inspect posted spending, movement, account balances and the latest entries. Use the account control to change scope. Open Transactions to inspect posted and pending items, filter and search, and open a detail view. Refresh data after an operator simulation. Customer 1 has no accounts, customer 2 has an empty account and customer 3 has pending-only activity.

## Demonstrate pending, posting and cancellation

This intentionally mutates the selected synthetic demo database. Choose a unique lowercase run ID and explicitly approve the operation:

```sh
./dev demo review1 --approve
```

The command validates the project-scoped demo manifest, resolves `synthetic-00004` to its eligible everyday account, checks that ownership, dataset identity and merchants match the database, then binds the restricted simulator identity to the current dataset instance epoch. It uses logical date 2026-10-30 in Africa/Johannesburg. It creates a R100.00 pending Cedar Market purchase, posts it for R85.00, creates a separate R40.00 pending Harbor Café purchase and cancels that one. It reports account posted totals before and after each operation, then retries the posting event and verifies `replayed: true`. Pending and cancellation do not change posted totals. Refresh the dashboard after the command to see the posted change. Repeating a corrected run ID replays its events; a run ID previously used against a different customer is rejected, so choose a new run ID.

The simulator runs through one-off local containers with its own restricted PostgreSQL role. It is not a customer API action. For individual operator actions, `./dev simulate:provision <project> <project> --dataset <directory>` and `./dev simulate <project> <project> pending|post|cancel ...` remain available; run `./dev help` and see the CLI's `--help`. The duplicate project name is explicit target approval. The simulator password is an independent secret in `.env`. Direct API and simulator provisioning reject a configured password that differs from an existing role; neither command rotates that role's password.

## Verify the project

`./dev test:docker all` runs Java formatting and Testcontainers integration tests, Vue type/lint/format/OpenAPI drift checks and tests, Python Ruff and pytest checks, Compose validation, and both application image builds with Docker-only host prerequisites. The same command accepts `api`, `web` or `python` to run one portion. `CSI_WEB_PORT=8101 ./dev test:docker browser` runs six real Chromium journeys against an automatically removed isolated fixture; choose an available loopback port. `./dev check`, `./dev test`, `./dev build` and `./dev format` retain the faster host-toolchain workflow used by CI.

The isolated fixture is available only for a named test project: `CSI_ISOLATED_TEST_DB=1 ./dev fixture <project>`. Its test password is `fixture-only-password`; never use it for the normal demo. Tests that remove an isolated fixture volume must use the exact fixture project name.

## Architecture and controls

Vue is built into unprivileged Nginx; Spring Boot runs on a JRE as UID 10001; PostgreSQL holds exact financial entries and sessions. Only Nginx publishes a host port. It proxies `/api/v1/` and denies other `/api` and `/actuator` paths. Flyway migration, API role provisioning, dataset import and simulator approval are separate one-off operations. The API role can read financial tables and maintain sessions and login-attempt state; it cannot write financial tables or perform DDL. The importer verifies canonical CSVs and the manifest, hashes bytes consumed by PostgreSQL COPY, reconciles financial totals, and commits only on matching identity. Replaying the same seed is a no-op; a different seed is rejected on an occupied database. The local HTTP profile disables the secure-cookie flag; it is not an HTTPS deployment profile.

Normal API-role SQL statements have an eight-second PostgreSQL deadline and Spring JDBC queries request the same deadline. Hikari waits at most three seconds for a connection; Tomcat accepts connections with a five-second timeout; the web proxy's upstream read deadline is 15 seconds. Migration and import roles do not inherit the API-role statement deadline. The API emits bounded JSON security events for login, logout, denial, validation and throttling with a normalized route and request ID. They contain no credentials, session IDs, or financial response bodies. Container logs rotate locally. Actuator metrics are available only inside the API container on loopback and are blocked by the web proxy.

## Advanced data and deployment work

The host-toolchain commands `./dev data:generate demo generated-data/demo`, `./dev data:validate generated-data/demo` and `./dev data:import generated-data/demo <project> <project>` are for explicit operator imports. A separate `benchmark` generator profile targets roughly one million posted entries and requires disk and Docker memory preflights. Generated datasets stay ignored. The old `./dev data:demo` and `data:benchmark` shortcuts still require target approval. The Kubernetes API manifest at `infra/k8s/api.yaml` declares two initial private API replicas and CPU HPA bounds of two to five. Kubernetes experiments remain separate from normal startup.

For an isolated benchmark, install host `uv` and `k6`, then run `./dev benchmark:prepare csi-benchmark-review csi-benchmark-review` with at least 4 GiB host disk free and 4 GiB Docker memory. This generates a current-policy dataset under ignored `generated-data/csi-benchmark-review/benchmark`, imports it once into a new named volume, and starts the Docker production build on loopback port 18090. Run `./dev benchmark:run csi-benchmark-review smoke synthetic-00004,synthetic-00014` for a 30-second authenticated 10 rps check, or replace `smoke` with `reference` for five minutes at 50 offered rps. The authenticated mix is 45% dashboards, 45% posted history and 10% entry details, sampling owned-account scopes, current and previous months, a wider range, and first and deeper cursor pages. Choose actual ordinary and high-activity login IDs from that dataset's `customers.csv`. Results are written outside Git to the private Capitec workspace by default. Run `./dev benchmark:metrics csi-benchmark-review load 330` concurrently with the five-minute reference run to retain private JVM, Hikari, database and container samples. `warm`, `overload` and `recovery` are also valid named phases; duration is in seconds, up to 360. Set `CSI_WEB_PORT=...` consistently if 18090 is occupied. `./dev benchmark:down csi-benchmark-review csi-benchmark-review` stops containers but retains its dataset, volume and login file.

For the local Kubernetes experiment, install `k3d` and `kubectl` and first prepare the isolated benchmark project. `./dev k8s:up csi-benchmark-review csi-hardening-review` creates one server and two labelled workers, imports that project's API image, and waits for two ready API replicas, Metrics Server and the network policy check. The application namespace enforces Kubernetes Restricted Pod Security at v1.35. The local HTTP ingress binds only to `127.0.0.1:18091`; it shares the benchmark database and login file. `./dev k8s:demo csi-benchmark-review csi-hardening-review hpa synthetic-00004,synthetic-00014` offers 50 authenticated reads per second for two minutes; `smoke` and `reference` profiles are also available. Observe `kubectl --context k3d-csi-hardening-review -n customer-spending-insights get hpa,pods` during load and after the 300-second downscale window. The PodDisruptionBudget requires one available API replica during voluntary eviction. A compatible image rollback still requires an operator to verify schema compatibility and select the prior image. `./dev k8s:down csi-benchmark-review csi-hardening-review csi-hardening-review` deletes only that named cluster; the benchmark database remains intact. This Kubernetes ingress is an explicitly local HTTP scaling environment, separate from the HTTPS security profile.

For a private recovery exercise, run `./dev recovery:backup csi-benchmark-review '/absolute/private/path/review.dump'`, then `./dev recovery:restore '/absolute/private/path/review.dump' csi-recovery-review csi-recovery-review`. Restore refuses an existing target volume or containers, removes restored sessions, changes the dataset instance epoch, provisions the restricted API role and leaves the restored API stopped for inspection. The dump remains outside Git with restricted file permissions. This is data recovery; application image rollback is a separate operation.

## Current limits

The benchmark command reports laboratory throughput and endpoint latency on the measured host; it is not a production capacity guarantee. The Kubernetes manifest is a local experiment, not a production cluster deployment or automatic rollback controller. Docker image sizes and build timings depend on the host and are reported from the acceptance run, not promised here. The demo is synthetic assessment data and the simulator is not payment processing.
