import type { Money, Rating } from "./types";

export function cn(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

const moneyFmt = new Map<string, Intl.NumberFormat>();
export function formatMoney(m: Money | undefined | null, opts: { compact?: boolean } = {}) {
  if (!m || !Number.isFinite(m.amount)) return "—";
  const key = `${m.currency}-${opts.compact ? "c" : "f"}`;
  let fmt = moneyFmt.get(key);
  if (!fmt) {
    try {
      fmt = new Intl.NumberFormat(m.currency === "INR" ? "en-IN" : "en-US", {
        style: "currency",
        currency: m.currency,
        maximumFractionDigits: opts.compact ? 1 : 0,
        notation: opts.compact ? "compact" : "standard",
      });
    } catch {
      fmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
    }
    moneyFmt.set(key, fmt);
  }
  return fmt.format(m.amount);
}

export function currencySymbol(currency: string) {
  try {
    const part = new Intl.NumberFormat("en", { style: "currency", currency, currencyDisplay: "narrowSymbol" })
      .formatToParts(0)
      .find((p) => p.type === "currency");
    return part?.value ?? currency;
  } catch {
    return currency;
  }
}

/** Parse "YYYY-MM-DD" as a local calendar date (no timezone drift). */
export function parseISODate(s: string) {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
}

export function toISODate(d: Date) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function addDays(d: Date, n: number) {
  const out = new Date(d);
  out.setDate(out.getDate() + n);
  return out;
}

export function daysBetweenInclusive(start: string, end: string) {
  const a = parseISODate(start).getTime();
  const b = parseISODate(end).getTime();
  return Math.round((b - a) / 86_400_000) + 1;
}

export function formatDate(s: string, opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" }) {
  if (!s) return "";
  return parseISODate(s).toLocaleDateString("en-GB", opts);
}

export function formatDateRange(start: string, end: string) {
  if (!start || !end) return "";
  const a = parseISODate(start);
  const b = parseISODate(end);
  const sameYear = a.getFullYear() === b.getFullYear();
  const sameMonth = sameYear && a.getMonth() === b.getMonth();
  const left = a.toLocaleDateString("en-GB", { day: "numeric", ...(sameMonth ? {} : { month: "short" }) });
  const right = b.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  return `${left} – ${right}`;
}

export function formatDuration(min: number) {
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

export function formatMs(ms: number) {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
}

export function formatClock(totalSeconds: number) {
  const m = Math.floor(totalSeconds / 60);
  const s = Math.floor(totalSeconds % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function pct(v: number, digits = 0) {
  return `${(v * 100).toFixed(digits)}%`;
}

/** SPEC: Good ≥ 0.70, OK ≥ 0.40, Weak < 0.40. */
export function ratingFor(value: number): Rating {
  if (value >= 0.7) return "Good";
  if (value >= 0.4) return "OK";
  return "Weak";
}

export function travellers(adults: number, children: number) {
  const a = `${adults} adult${adults === 1 ? "" : "s"}`;
  return children ? `${a}, ${children} child${children === 1 ? "" : "ren"}` : a;
}
