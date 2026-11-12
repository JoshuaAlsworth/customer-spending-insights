import { expect, it } from "vitest";
import { money } from "./money";

it("formats large signed minor units without floating point", () => {
  expect(money("12345678901234567890", true)).toBe(
    "+R123,456,789,012,345,678.90",
  );
  expect(money("-15000")).toBe("−R150.00");
  expect(money("0")).toBe("R0.00");
  expect(() => money("1.5")).toThrow();
  expect(() => money("-0")).toThrow();
});
