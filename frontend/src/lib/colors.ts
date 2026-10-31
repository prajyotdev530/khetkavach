// Colours and words for risk levels and evidence layers (BUILD_SPEC §4). Colour is never the only signal:
// every level is also written as a word.
import type { Hazard, Level } from "./api";

export const LEVEL_COLOR: Record<Level, string> = { low: "#2E7D32", moderate: "#F9A825", high: "#C62828" };
export const LEVEL_TEXT: Record<Level, string> = { low: "#1B5E20", moderate: "#6D4C00", high: "#B71C1C" };
export const LEVEL_BG: Record<Level, string> = { low: "#E8F5E9", moderate: "#FFF8E1", high: "#FFEBEE" };
export const LEVEL_WORD: Record<Level, string> = { low: "Low", moderate: "Moderate", high: "High" };
export const LEVEL_FILL_OPACITY: Record<Level, number> = { low: 0.15, moderate: 0.15, high: 0.2 };
export const RUNNING_GREY = "#9E9E9E";

export const HAZARD_LABEL: Record<Hazard, string> = { drought: "Drought", excess_rain: "Excess rain", heat: "Heat" };

export const CHANGE_RAMP = [
  { color: "#B2182B", label: "much less green" },
  { color: "#EF8A62", label: "less green" },
  { color: "#F0F0F0", label: "no change" },
  { color: "#91CF60", label: "greener" },
  { color: "#1A9850", label: "much greener" },
];
export const NDVI_RAMP = [
  { color: "#A50026", label: "< 0.15 bare / sparse" },
  { color: "#F46D43", label: "0.15–0.30" },
  { color: "#FEE08B", label: "0.30–0.45" },
  { color: "#A6D96A", label: "0.45–0.60" },
  { color: "#1A9850", label: "≥ 0.60 dense green" },
];
