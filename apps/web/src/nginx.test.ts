import { expect, it } from "vitest";
import config from "../nginx.conf?raw";

it("does not expose API or Actuator routes through the public origin", () => {
  expect(config).toMatch(/location \/api\/ \{ return 404; \}/);
  expect(config).toMatch(/location \/actuator\/ \{\s*return 404;/);
  expect(config).toMatch(
    /location \/api\/v1\/ \{[\s\S]*?proxy_pass http:\/\/api:8080;/,
  );
  expect(config).toMatch(/zone=login_limit:10m rate=1r\/s/);
  expect(config).toMatch(
    /location ~ \^\/api\/v1\/auth\/login\$ \{[\s\S]*?limit_req zone=login_limit burst=5/,
  );
  expect(config).not.toMatch(/location \^~ \/api\/v1\//);
  expect(config).not.toMatch(
    /location[^\n]*actuator[^\n]*\{[\s\S]*?proxy_pass/,
  );
});
