const canonical = /^(0|-?[1-9]\d*)$/;
export function money(minor: string, signed = false): string {
  if (!canonical.test(minor)) throw new Error("Invalid monetary value");
  const value = BigInt(minor);
  const absolute = value < 0n ? -value : value;
  const whole = (absolute / 100n)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const fraction = (absolute % 100n).toString().padStart(2, "0");
  return `${value < 0n ? "−" : signed && value > 0n ? "+" : ""}R${whole}.${fraction}`;
}
