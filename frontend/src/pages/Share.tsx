// Share page (route "/a/:id", F15): a read-only view of a saved analysis, read back from the database.
// It rebuilds the screen by replaying the saved trace, so it shows exactly what the live run showed.
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Loader2, MapPin } from "lucide-react";
import { getJson } from "@/lib/api";
import { replayRun, type RunState } from "@/lib/sse";
import { clock } from "@/lib/format";
import { MapView, type LayerState } from "@/components/MapView";
import { RiskCard } from "@/components/RiskCard";
import { ActionPlan } from "@/components/ActionPlan";
import { EvidencePanel } from "@/components/EvidencePanel";
import { TracePanel } from "@/components/TracePanel";

export function Share({ lang, languageName }: { lang: string; languageName: string }) {
  const { id } = useParams();
  const [run, setRun] = useState<RunState | null>(null);
  const [created, setCreated] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [layers, setLayers] = useState<LayerState>({ base: "satellite", risk: true, delta_ndvi: true, ndvi: false, truecolor: false, radar: true });

  useEffect(() => {
    getJson<any>(`/api/analysis/${id}`, 15000)
      .then((p) => { setRun(replayRun(p)); setCreated(p.created_at); })
      .catch((e) => setErr(e?.message ?? "This analysis link was not found."));
  }, [id]);

  if (err) return <div className="m-6 rounded-md border border-slate-300 bg-white p-4 text-sm">{err} <Link className="underline" to="/">Run a new analysis</Link></div>;
  if (!run) return <div className="m-6 flex items-center gap-2 text-sm text-slate-600"><Loader2 className="h-4 w-4 animate-spin" /> Loading the saved analysis…</div>;
  const place = run.place ? [run.place.name, run.place.district, run.place.state].filter(Boolean).join(", ") : "";
  const live = `/?lat=${run.params?.lat}&lon=${run.params?.lon}&crop=${run.params?.crop}`;

  return (
    <main className="flex min-h-0 flex-1 flex-col md:flex-row">
      <section className="h-[45vh] min-h-[300px] md:h-auto md:w-3/5" aria-label="Map">
        <MapView run={run} layers={layers} setLayers={setLayers} compare={null} onPick={() => undefined} />
      </section>
      <section className="min-h-0 flex-1 space-y-3 overflow-y-auto border-l border-slate-200 bg-slate-50 p-3 md:w-2/5" aria-label="Saved analysis">
        <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm">
          <div className="flex items-center gap-2 font-medium"><MapPin className="h-4 w-4 text-brand-700" aria-hidden />{place}</div>
          <p className="mt-1 text-xs text-slate-600">Saved analysis from {clock(created)}. Values are as fetched then, not live.</p>
          <Link to={live} className="mt-2 inline-block text-xs font-medium text-brand-700 underline">Run a fresh live analysis for this farm</Link>
        </div>
        <RiskCard run={run} />
        <ActionPlan run={run} lang={lang} languageName={languageName} translationError={null} />
        <details className="rounded-lg border border-slate-200 bg-white p-3"><summary className="cursor-pointer text-sm font-semibold">Evidence</summary><div className="mt-2"><EvidencePanel run={run} /></div></details>
        <details className="rounded-lg border border-slate-200 bg-white p-3"><summary className="cursor-pointer text-sm font-semibold">Agent trace</summary><div className="mt-2"><TracePanel run={run} /></div></details>
      </section>
    </main>
  );
}
