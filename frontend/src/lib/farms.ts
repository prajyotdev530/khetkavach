// Quick-farm chips (BUILD_SPEC §11): only a name and real coordinates the team picked by running live analyses
// on 31 Oct 2026. Clicking a chip moves the map and starts a normal live analysis; no result is stored here.
import type { Crop } from "./api";

export interface QuickFarm {
  label: string;
  lat: number;
  lon: number;
  crop: Crop;
  why: string;
}

export const QUICK_FARMS: QuickFarm[] = [
  { label: "Ahilyanagar, MH", lat: 19.1, lon: 74.7, crop: "wheat", why: "Rabi farm: High drought risk in the 31 Oct check" },
  { label: "Niphad, Nashik", lat: 20.05, lon: 74.05, crop: "wheat", why: "Wheat/grape belt: Moderate drought risk, green crop" },
  { label: "Thanjavur, TN", lat: 10.75, lon: 79.1, crop: "unknown", why: "Cauvery delta: Low risk, for contrast" },
];
