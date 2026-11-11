import { expect, it } from "vitest";
import config from "../nginx.conf?raw";

it("does not expose API or Actuator routes through the public origin", () => {
  expect(config).toMatch(
    /location ~\* \^\/\(api\|actuator\)\(\/\|\$\)\s*\{\s*return 404;/,
  );
  expect(config).not.toMatch(/proxy_pass/);
});
