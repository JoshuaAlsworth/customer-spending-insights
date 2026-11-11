# Customer Spending Insights

Initial monorepo foundation for the Capitec Software Engineer assessment. Approved project and financial/UI specifications are held privately outside this repository. The Vue bootstrap, Spring API security boundary, PostgreSQL role provisioning and toolchains are present; the financial dashboard, authentication, migrations, simulator and OpenAPI contract remain future work.

## Requirements

- Java 25, Node.js 24, pnpm 12.19.0, uv with Python 3.14, Docker Desktop with Compose.
- For the container runtime, copy `.env.example` to `.env` and set distinct, generated local admin and API passwords. Keep `.env` private.

## Commands

- `./dev check` runs the Java, Vue, Python, and Compose configuration checks.
- `./dev test` runs the current unit tests.
- `./dev build` builds the Java and Vue applications.
- `./dev provision customer-spending-insights` creates or updates the restricted API role on the existing database without resetting its volume. Run once before `up`, and after changing the API password. Use an explicit project name when working with a separate Compose project.
- `./dev up` builds and starts the local containers after provisioning. Open <http://127.0.0.1:8088>.
- `./dev down` stops the containers and preserves the database volume.

The API health endpoint is available on the private Compose network for probes. The public web origin blocks API and Actuator paths until customer API routes and their security controls are implemented. Database migrations and seed imports are disabled pending their controlled lifecycle.

The OpenAPI source will live at `contracts/openapi.yaml`. A TypeScript generator will be pinned only after a small contract fixture verifies decimal-string money, nullable fields, and discriminated activity types.
