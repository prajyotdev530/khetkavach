// SearchBox: village/town search over the map (top-left). Debounced, needs ≥ 3 characters, results limited to
// India by the backend (Nominatim, ≤ 1 request/second). Picking a result starts a normal live analysis.
import { useEffect, useRef, useState } from "react";
import { Search, Loader2 } from "lucide-react";
import { searchPlaces, type SearchHit } from "@/lib/api";

export function SearchBox({ onPick }: { onPick: (hit: SearchHit) => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    window.clearTimeout(timer.current);
    if (q.trim().length < 3) {
      setHits([]);
      setErr(null);
      return;
    }
    timer.current = window.setTimeout(async () => {
      setBusy(true);
      try {
        const res = await searchPlaces(q.trim());
        setHits(res.results);
        setErr(res.results.length ? null : "No places in India found");
        setOpen(true);
      } catch (e: any) {
        setErr(e?.message ?? "Search unavailable");
        setOpen(true);
      } finally {
        setBusy(false);
      }
    }, 500);
    return () => window.clearTimeout(timer.current);
  }, [q]);

  return (
    <div className="absolute left-3 top-3 z-[1000] w-[min(20rem,calc(100%-5rem))]" onClick={(e) => e.stopPropagation()}>
      <label className="sr-only" htmlFor="kk-search">Search a village or town in India</label>
      <div className="flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 shadow-md">
        <Search className="h-4 w-4 shrink-0 text-slate-500" aria-hidden />
        <input
          id="kk-search"
          className="min-h-[44px] w-full bg-transparent text-sm outline-none placeholder:text-slate-500"
          placeholder="Search a village or town"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && hits[0]) { onPick(hits[0]); setOpen(false); }
            if (e.key === "Escape") setOpen(false);
          }}
          autoComplete="off"
        />
        {busy && <Loader2 className="h-4 w-4 animate-spin text-slate-500" aria-label="Searching" />}
      </div>
      {open && (hits.length > 0 || err) && (
        <ul className="mt-1 max-h-64 overflow-auto rounded-lg border border-slate-200 bg-white text-sm shadow-lg" role="listbox">
          {err && <li className="px-3 py-2 text-slate-600">{err}</li>}
          {hits.map((h) => (
            <li key={`${h.lat},${h.lon}`}>
              <button
                type="button"
                className="w-full px-3 py-2 text-left hover:bg-brand-50 focus:bg-brand-50 focus:outline-none"
                onClick={() => { onPick(h); setOpen(false); setQ(h.name); }}
              >
                <div className="font-medium text-slate-900">{h.name}</div>
                <div className="text-xs text-slate-600">{[h.district, h.state].filter(Boolean).join(", ")}</div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
