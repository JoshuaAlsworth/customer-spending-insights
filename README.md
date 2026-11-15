# Customer Spending Insights

## Project overview

Customer Spending Insights is a synthetic ZAR banking dashboard. Customers can sign in, view exact posted balances and spending summaries, switch accounts and periods, and inspect posted, pending and cancelled transactions. Transactions supports search, status and category filters, cursor pagination and entry details. Financial amounts are stored and returned in integer cents.

## Technology stack

Vue 3 and TypeScript provide the interface. Spring Boot serves the API, PostgreSQL stores financial data and sessions, and Flyway manages schema changes. Nginx serves the built frontend and proxies the API. Docker Compose runs the local application and data tools.

## Quick start with Docker

From the repository root, start Docker Desktop and run:

```sh
./dev up
./dev credentials
```

Open the URL printed by `./dev up` and sign in as `synthetic-00007` with the password printed by `./dev credentials`. Normal startup needs a POSIX shell, Docker and Docker Compose; it does **not** need host Java, Node, pnpm, Python or uv. The first run creates local secrets and a deterministic demo dataset. Later runs preserve the existing dataset and credentials.

The default URL is `http://127.0.0.1:8088`. If that port is busy, `./dev up` chooses an available loopback port through 8098 and prints it. Set `CSI_WEB_PORT=8089 ./dev up` to request a specific free port. Set `CSI_COMPOSE_PROJECT=<name>` consistently on commands to use a separate project and database. `./dev down` stops the selected project **without deleting its financial data, database volume or credentials**.

## Showcase login and customer scenarios

`synthetic-00007` has balances, spending and transaction history to explore. Other generated customers illustrate empty accounts (customer 2), pending-only activity (customer 3), a dormant account (customer 4), a recently opened account (customer 5), and higher activity (customers 19 and 20). Customer 1 has no accounts.

To demonstrate the pending, posted and cancelled lifecycle, run:

```sh
./dev demo review1 --approve
```

Use a new lowercase run ID for a new demonstration. This operator-only command **changes the selected synthetic database**: it creates a R100.00 pending purchase, posts it for R85.00, then creates and cancels a separate R40.00 purchase. Pending and cancelled authorisations do not change posted totals. The command reports balance changes and verifies an idempotent posting replay. **Reload the dashboard page** after external simulator changes; the interface does not poll or provide a general Refresh control.

## Commands

Run `./dev help` for complete syntax. Commands below run from the repository root.

| Command                                                                                                                              | Purpose                                                                                                                                                                                            |
| ------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `./dev up`                                                                                                                           | Start or resume the Docker application and demo dataset.                                                                                                                                           |
| `./dev down`                                                                                                                         | Stop the selected project; retain its database volume, dataset and credentials.                                                                                                                    |
| `./dev status`, `./dev logs`                                                                                                         | Show service health or recent database, API and web logs.                                                                                                                                          |
| `./dev credentials`                                                                                                                  | Show the selected project's local `synthetic-00007` password.                                                                                                                                      |
| `./dev demo <run-id> --approve`                                                                                                      | Apply the pending/post/cancel example to the selected demo database.                                                                                                                               |
| `./dev test:docker all`                                                                                                              | Run Docker-only API, frontend and data-tool checks, validate Compose and build images.                                                                                                             |
| `./dev test:docker api\|web\|python\|browser`                                                                                        | Run one Docker test area; `browser` uses an isolated disposable fixture.                                                                                                                           |
| `./dev check`, `./dev test`, `./dev build`, `./dev format`                                                                           | Run host-toolchain quality checks, tests, builds or formatters.                                                                                                                                    |
| `./dev secure:up <project>`                                                                                                          | Start the optional local HTTPS profile with a self-signed certificate.                                                                                                                             |
| `./dev benchmark:prepare\|run\|metrics\|down ...`                                                                                    | Prepare, measure or stop an isolated benchmark project; `down` retains its data.                                                                                                                   |
| `./dev k8s:up\|demo\|down ...`                                                                                                       | Run or remove the optional local k3d experiment.                                                                                                                                                   |
| `./dev recovery:backup <project> <absolute-private-file>`                                                                            | Create a restricted database dump outside Git; refuse an existing output file.                                                                                                                     |
| `./dev recovery:restore <absolute-private-file> <new-csi-recovery-project> <same-name-to-approve>`                                   | Restore into a **new**, approved project; refuse an existing target and leave its API stopped.                                                                                                     |
| `./dev data:generate <demo\|benchmark> <directory>`, `./dev data:validate <directory>`                                               | Generate or validate an optional dataset with host uv; neither imports it.                                                                                                                         |
| `./dev data:import <directory> <project> <same-name-to-approve>`                                                                     | Import a validated dataset into an explicitly approved project database; requires host uv.                                                                                                         |
| `./dev data:demo\|data:benchmark <project> <same-name-to-approve>`                                                                   | Generate if needed, validate and import a dataset into the approved project; requires host uv.                                                                                                     |
| `./dev provision <project>`, `CSI_ISOLATED_TEST_DB=1 ./dev fixture <project>`                                                        | Provision a named database role or create an isolated test fixture; both modify the named database and require `.env`.                                                                             |
| `./dev simulate:provision <project> <project> --dataset <directory>`, `./dev simulate <project> <project> pending\|post\|cancel ...` | Approve a dataset for the restricted simulator, then perform individual operator actions that modify financial activity. Individual actions require host Python 3; see `./dev help` for arguments. |

For import, simulator and recovery commands, the repeated project name is explicit target approval. Check the name and dataset before running them.

## Testing and verification

`./dev test:docker all` needs Docker with Compose and access to the Docker daemon. It covers Java formatting and integration tests, Vue type, lint, format, OpenAPI drift and unit checks, Python Ruff and pytest checks, Compose validation and application image builds.

To run six Chromium journeys against a disposable database, choose an available loopback port:

```sh
CSI_WEB_PORT=8101 ./dev test:docker browser
```

The host commands `./dev check`, `./dev test`, `./dev build` and `./dev format` require their respective local Java, Node/pnpm, Python/uv and Docker tools. Normal `./dev up` does not.

## System architecture

Only the Nginx web container publishes a host port. It serves Vue and proxies `/api/v1/` to Spring Boot. PostgreSQL stores posted entries, authorisations and sessions. Separate one-off roles perform migration, dataset import and operator simulation. The restricted API database role cannot write financial tables or change the schema. Dataset import validates identity and reconciles totals before accepting data.

## Optional demonstrations

- **Benchmark:** With host `uv` and `k6`, at least 4 GiB free disk and 4 GiB Docker memory, run `./dev benchmark:prepare csi-benchmark-review csi-benchmark-review`, then `./dev benchmark:run csi-benchmark-review smoke synthetic-00004,synthetic-00014`. The default loopback port is 18090; set `CSI_WEB_PORT` consistently if it is occupied. `compare` and `reference` are other local profiles; `hpa` requires the k3d ingress. `benchmark:metrics` records a named phase for 1–360 seconds. Results stay outside Git. Stop with `./dev benchmark:down csi-benchmark-review csi-benchmark-review`; its database remains.
- **Kubernetes:** After preparing the benchmark project, install `k3d` and `kubectl`. Run `./dev k8s:up csi-benchmark-review csi-hardening-review`, then `./dev k8s:demo csi-benchmark-review csi-hardening-review hpa synthetic-00004,synthetic-00014`. Remove that cluster with `./dev k8s:down csi-benchmark-review csi-hardening-review csi-hardening-review`. The benchmark database remains. This local HTTP experiment needs at least 6 GiB free disk and 7 GiB Docker memory.
- **HTTPS:** With host OpenSSL, run `./dev secure:up csi-secure-check` and open `https://localhost:8443` (or set `CSI_HTTPS_PORT`). The certificate is self-signed and stored in ignored `.local-certs/<project>/`; explicitly trust it for local testing. Use `CSI_COMPOSE_PROJECT=csi-secure-check` for subsequent project commands.
- **Recovery:** Run `./dev recovery:backup csi-benchmark-review /absolute/private/path/review.dump`, then `./dev recovery:restore /absolute/private/path/review.dump csi-recovery-review csi-recovery-review`. The backup directory must exist outside Git. Restore requires a new target without a volume or containers, invalidates restored sessions, changes the dataset epoch and leaves the API stopped. Verify it before further use.

## Important limitations

This is synthetic assessment data, not payment processing. Ordinary `./dev up` and the Kubernetes experiment use local HTTP; the self-signed HTTPS profile is for local checks, not production deployment. Benchmark results describe the measured host, not guaranteed production capacity. Kubernetes scaling is a local demonstration, not automatic deployment or rollback.

Keep ignored `.env`, `.env.demo.<project>`, `.env.benchmark.<project>`, generated datasets and backups private. Keep `.env` with its matching database volume: startup rejects a changed API password rather than rotating the existing role. A database restarted without its original login file retains its existing credentials; startup does not reset them. Never delete a project volume or its credential files unless that project's data is intentionally disposable.
