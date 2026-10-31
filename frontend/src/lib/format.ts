// Small formatting helpers for dates, "fetched 3 min ago" labels and numbers.

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-11-06" → "6 Nov" (or "6 Nov 2025" with the year). */
export function shortDate(iso: string | null | undefined, withYear = false): string {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]}${withYear ? ` ${y}` : ""}`;
}

/** "fetched 3 min ago" style label for a timestamp. */
export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const secs = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (secs < 60) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 48) return `${hrs} h ago`;
  return `${Math.round(hrs / 24)} days ago`;
}

/** Local time like "15:03, 31 Oct" for tooltips. */
export function clock(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}, ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

/** Format a cited value for display (numbers keep their precision, lists are summarised). */
export function showValue(value: unknown, unit = ""): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return `${value.length}-day table`;
  if (typeof value === "number") return `${value}${unit ? ` ${unit}` : ""}`;
  return `${String(value)}${unit ? ` ${unit}` : ""}`;
}

/** Today's date in India as YYYY-MM-DD (for the sowing-date picker's max). */
export function todayIST(): string {
  const now = new Date(Date.now() + (330 + new Date().getTimezoneOffset()) * 60000);
  return now.toISOString().slice(0, 10);
}
