// Home (route "/"): the main demo screen. Map on the left (60%), results on the right (40%); stacked on phones
// with the map in the top 45%. Screen states from BUILD_SPEC §3: idle, running, done, partial, rejected, error.
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Check, Info, MapPin, RotateCcw, Share2, XCircle } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { postJson, type Crop, type Language, type Meta, type Translation } from "@/lib/api";
import { useAnalysis, type RunParams } from "@/lib/sse";
import { todayIST } from "@/lib/format";
import { QUICK_FARMS } from "@/lib/farms";
import { MapView, type CompareState, type LayerState } from "@/components/MapView";
import { BeforeNowSlider } from "@/components/BeforeNowSlider";
import { TracePanel } from "@/components/TracePanel";
import { RiskCard } from "@/components/RiskCard";
import { ActionPlan } from "@/components/ActionPlan";
import { EvidencePanel } from "@/components/EvidencePanel";
import { DemoMenu } from "@/components/DemoMenu";
import { AskBox } from "@/components/AskBox";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";

const CROPS: { value: Crop; label: string }[] = [
  { value: "wheat", label: "Wheat" }, { value: "mustard", label: "Mustard" },
  { value: "gram", label: "Gram (chickpea)" }, { value: "unknown", label: "Not sure" },
];

export function Home({ meta, lang, languages }: { meta: Meta | null; lang: string; languages: Language[] }) {
  const { state: run, start, setTranslation } = useAnalysis();
  const [translationError, setTranslationError] = useState<string | null>(null);
  const [crop, setCrop] = useState<Crop>("wheat");
  const [sowing, setSowing] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [tab, setTab] = useState("trace");
  const [layers, setLayers] = useState<LayerState>({
    base: "satellite", risk: true, delta_ndvi: true, ndvi: false, truecolor: false, radar: true,
  });
  const [compare, setCompare] = useState<CompareState | null>(null);
  const [demoOpen, setDemoOpen] = useState(false);

  const launch = useCallback((lat: number, lon: number, fail?: string) => {
    if (sowing && sowing > todayIST()) {
      setFormError("Sowing date cannot be in the future.");
      return;
    }
    setFormError(null);
    setCompare(null);
    setTab("trace");
    const params: RunParams = { lat, lon, crop, lang, sowing_date: sowing || undefined, fail };
    start(params);
  }, [crop, lang, sowing, start]);

  // Links like /?lat=19.1&lon=74.7&crop=wheat (from the batch view) start a live analysis on load.
  const [search, setSearch] = useSearchParams();
  useEffect(() => {
    const la = Number(search.get("lat")), lo = Number(search.get("lon"));
    const c = search.get("crop") as Crop | null;
    if (Number.isFinite(la) && Number.isFinite(lo) && search.get("lat") && search.get("lon")) {
      if (c && CROPS.some((x) => x.value === c)) setCrop(c);
      setSearch({}, { replace: true });
      setTimeout(() => start({ lat: la, lon: lo, crop: c ?? crop, lang }), 0);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const [copied, setCopied] = useState(false);
  const share = async () => {
    if (!run.analysisId) return;
    const url = `${window.location.origin}${window.location.pathname}#/a/${run.analysisId}`;
    try { await navigator.clipboard.writeText(url); } catch { /* clipboard blocked: the link is still shown in the address bar of the share page */ }
    setCopied(true);
    setTimeout(() => setCopied(false), 2500);
  };

  // Switch to the Risk tab automatically when the run finishes.
  useEffect(() => {
    if (run.status === "done") setTab("risk");
  }, [run.status]);

  // Translate the checked English plan when the user picks another language after (or during) a run.
  useEffect(() => {
    setTranslationError(null);
    if (run.status !== "done" || !run.analysisId || lang === "en-IN") return;
    if (run.translation?.lang === lang) return;
    let alive = true;
    postJson<Translation>("/api/translate", { analysis_id: run.analysisId, lang })
      .then((t) => { if (alive) setTranslation(t); })
      .catch(() => { if (alive) setTranslationError("Translation unavailable right now"); });
    return () => { alive = false; };
  }, [lang, run.status, run.analysisId]); // eslint-disable-line react-hooks/exhaustive-deps

  const languageName = languages.find((l) => l.code === lang)?.name ?? lang;
  const retry = () => run.params && launch(run.params.lat, run.params.lon);
  const placeLabel = run.place
    ? [run.place.name, run.place.district, run.place.state].filter(Boolean).join(", ")
    : run.params ? `${run.params.lat.toFixed(4)}, ${run.params.lon.toFixed(4)}` : null;

  return (
    <main className="flex min-h-0 flex-1 flex-col md:flex-row">
      <section className="relative flex h-[45vh] min-h-[300px] flex-col md:h-auto md:w-3/5" aria-label="Map">
        <div className="relative min-h-0 flex-1">
          <MapView run={run} layers={layers} setLayers={setLayers} compare={compare} onPick={(la, lo) => launch(la, lo)} />
        </div>
        <BeforeNowSlider overlays={run.overlays} compare={compare} setCompare={setCompare} />
      </section>

      <section className="flex min-h-0 flex-1 flex-col border-l border-slate-200 bg-slate-50 md:w-2/5" aria-label="Results">
        <form className="space-y-2 border-b border-slate-200 bg-white p-3" onSubmit={(e) => e.preventDefault()}>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col text-xs font-medium text-slate-700">
              Crop
              <select className="mt-1 min-h-[44px] rounded-md border border-slate-300 bg-white px-2 text-sm md:min-h-[36px]" value={crop}
                onChange={(e) => setCrop(e.target.value as Crop)}>
                {CROPS.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select>
            </label>
            <label className="flex flex-col text-xs font-medium text-slate-700">
              Sowing date (optional)
              <input type="date" className="mt-1 min-h-[44px] rounded-md border border-slate-300 px-2 text-sm md:min-h-[36px]" value={sowing}
                max={todayIST()} onChange={(e) => setSowing(e.target.value)} aria-invalid={!!formError} />
            </label>
          </div>
          {formError && <p className="text-xs font-medium text-high-text" role="alert">{formError}</p>}
          {!sowing && <p className="text-[11px] text-slate-500">Without a sowing date the crop stage is unknown and stage-specific advice is skipped.</p>}
          {QUICK_FARMS.length > 0 && (
            <div className="flex flex-wrap gap-1.5" aria-label="Quick farms">
              {QUICK_FARMS.map((f) => (
                <button key={f.label} type="button" title={f.why}
                  className="min-h-[36px] rounded-full border border-brand-600 bg-brand-50 px-3 text-xs font-medium text-brand-900 hover:bg-brand-100"
                  onClick={() => { setCrop(f.crop); launch(f.lat, f.lon); }}>
                  {f.label}
                </button>
              ))}
            </div>
          )}
        </form>

        {placeLabel && (
          <div className="flex items-center gap-2 border-b border-slate-200 bg-white px-3 py-2 text-sm">
            <MapPin className="h-4 w-4 shrink-0 text-brand-700" aria-hidden />
            <span className="flex-1 font-medium text-slate-900">{placeLabel}</span>
            {run.stage && run.stage.key !== "unknown" && (
              <span className="text-xs text-slate-600">· {run.stage.label}{run.stage.days_after_sowing != null ? ` (day ${run.stage.days_after_sowing})` : ""}</span>
            )}
            {run.analysisId && (
              <Button size="sm" variant="outline" onClick={share} aria-label="Copy a link to this analysis">
                {copied ? <Check className="h-3.5 w-3.5" /> : <Share2 className="h-3.5 w-3.5" />} {copied ? "Link copied" : "Share"}
              </Button>
            )}
          </div>
        )}

        {run.status === "rejected" && (
          <div className="m-3 flex gap-2 rounded-md border border-slate-300 bg-white p-3 text-sm text-slate-800" role="status">
            <Info className="h-4 w-4 shrink-0 text-slate-500" aria-hidden />{run.error?.message}
          </div>
        )}
        {run.status === "error" && run.error && (
          <div className="m-3 flex flex-wrap items-center gap-2 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900" role="alert">
            <XCircle className="h-4 w-4 shrink-0" aria-hidden /><span className="flex-1">{run.error.message}</span>
            {run.error.retryable && run.params && <Button size="sm" variant="danger" onClick={retry}><RotateCcw className="h-3.5 w-3.5" /> Retry</Button>}
          </div>
        )}
        {run.missing.length > 0 && run.status !== "error" && (
          <div className="mx-3 mt-3 flex gap-2 rounded-md border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900" role="status">
            <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />
            <span>{run.missing.length === 1 && run.missing[0] === "Forecast" ? "Forecast unavailable, using recent observations." :
              `${run.missing.join(", ")} unavailable right now. Showing a partial result.`}</span>
          </div>
        )}
        {run.notes.map((n) => (
          <div key={n} className="mx-3 mt-2 flex gap-2 rounded-md border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900">
            <AlertTriangle className="h-4 w-4 shrink-0" aria-hidden />{n}
          </div>
        ))}

        {run.status === "idle" ? (
          <div className="flex flex-1 items-center justify-center p-6 text-center text-slate-600">
            <div>
              <MapPin className="mx-auto mb-2 h-8 w-8 text-brand-600" aria-hidden />
              <p className="font-medium text-slate-800">Click any farm in India or search a village</p>
              <p className="mt-1 text-sm">KhetKavach checks live satellite images, the 16-day forecast and the 20-year normal for a 500 m box around it.</p>
            </div>
          </div>
        ) : run.status !== "rejected" && (
          <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
            <TabsList>
              <TabsTrigger value="trace">Trace</TabsTrigger>
              <TabsTrigger value="risk">Risk</TabsTrigger>
              <TabsTrigger value="plan">Plan</TabsTrigger>
              <TabsTrigger value="evidence">Evidence</TabsTrigger>
            </TabsList>
            <div className="min-h-0 flex-1 overflow-y-auto">
              <TabsContent value="trace"><TracePanel run={run} /></TabsContent>
              <TabsContent value="risk"><RiskCard run={run} /></TabsContent>
              <TabsContent value="plan">
                <ActionPlan run={run} lang={lang} languageName={languageName} translationError={translationError} />
                {run.analysisId && run.status === "done" && <AskBox analysisId={run.analysisId} lang={lang} />}
              </TabsContent>
              <TabsContent value="evidence"><EvidencePanel run={run} /></TabsContent>
            </div>
          </Tabs>
        )}
      </section>

      <DemoMenu open={demoOpen} setOpen={setDemoOpen} options={meta?.fail_options ?? []} enabled={!!meta?.demo_controls}
        canRun={!!run.params} onRun={(fail) => run.params && launch(run.params.lat, run.params.lon, fail)} />
    </main>
  );
}
