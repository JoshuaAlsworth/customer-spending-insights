import { expect, it } from "vitest";
import config from "../nginx.conf?raw";
import secureConfig from "../nginx-secure.conf?raw";

it("does not expose API or Actuator routes through the public origin", () => {
  expect(config).toMatch(/location \/api\/ \{ return 404; \}/);
  expect(config).toMatch(/location \/actuator\/ \{\s*return 404;/);
  expect(config).toMatch(
    /location \/api\/v1\/ \{[\s\S]*?proxy_pass http:\/\/api:8080;/,
  );
  expect(config).toMatch(/zone=login_limit:10m rate=1r\/s/);
  expect(config).toMatch(/zone=api_limit:10m rate=60r\/s/);
  expect(config).toMatch(/proxy_set_header X-Forwarded-For \$remote_addr;/);
  expect(config).toMatch(/gzip on;/);
  expect(config).toMatch(
    /gzip_types text\/css application\/javascript application\/json;/,
  );
  expect(config).toMatch(
    /location ~ \^\/api\/v1\/auth\/login\$ \{[\s\S]*?limit_req zone=login_limit burst=5/,
  );
  expect(config).not.toMatch(/location \^~ \/api\/v1\//);
  expect(config).not.toMatch(
    /location[^\n]*actuator[^\n]*\{[\s\S]*?proxy_pass/,
  );
});

it("keeps the secure profile on TLS with Secure-cookie forwarding", () => {
  expect(secureConfig).toMatch(/listen 8443 ssl;/);
  expect(secureConfig).toMatch(/proxy_set_header X-Forwarded-Proto https;/);
  expect(secureConfig).toMatch(/add_header Strict-Transport-Security/);
  expect(secureConfig).toMatch(/add_header Content-Security-Policy/);
  expect(secureConfig).toMatch(/zone=login_limit:10m rate=1r\/s/);
});
