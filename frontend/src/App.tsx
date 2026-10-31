// App shell: header (wordmark, tagline, language picker), the server wake-up check, and the routes.
// If /health does not answer, we retry for 20 s with "Waking up the server…" (free hosting can sleep).
import { useEffect, useState } from "react";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { getJson, type Meta } from "@/lib/api";
import { Home } from "@/pages/Home";
import { Batch } from "@/pages/Batch";
import { Share } from "@/pages/Share";
import { DEFAULT_LANGUAGES, LanguagePicker } from "@/components/LanguagePicker";
import { TooltipProvider } from "@/components/ui/tooltip";

type Wake = "checking" | "waking" | "ready" | "down";

function useServer() {
  const [wake, setWake] = useState<Wake>("checking");
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    let alive = true;
    const startedAt = Date.now();
    const attempt = async () => {
      try {
        await getJson("/health", 5000);
        if (!alive) return;
        setWake("ready");
        setMeta(await getJson<Meta>("/api/meta", 5000));
      } catch {
        if (!alive) return;
        if (Date.now() - startedAt < 20000) {
          setWake("waking");
          setTimeout(attempt, 2000);
        } else {
          setWake("down");
        }
      }
    };
    attempt();
    return () => { alive = false; };
  }, []);
  return { wake, meta };
}

export default function App() {
  const { wake, meta } = useServer();
  const [lang, setLang] = useState(() => {
    try { return localStorage.getItem("kk-lang") || "en-IN"; } catch { return "en-IN"; }
  });
  useEffect(() => {
    try { localStorage.setItem("kk-lang", lang); } catch { /* storage may be blocked */ }
  }, [lang]);
  const languages = meta?.languages ?? DEFAULT_LANGUAGES;

  return (
    <BrowserRouter>
      <TooltipProvider delayDuration={150}>
        <div className="flex h-[100dvh] flex-col bg-slate-50 text-slate-900">
          <header className="flex flex-wrap items-center justify-between gap-2 bg-brand-900 px-4 py-2 text-white">
            <div className="flex items-baseline gap-3">
              <Link to="/" className="text-lg font-bold tracking-tight">KhetKavach</Link>
              <span className="hidden text-sm text-brand-100 sm:inline">Farm-level climate risk, in your language</span>
            </div>
            <div className="flex items-center gap-3">
              <Link to="/batch" className="rounded-md px-2 py-2 text-sm font-medium text-brand-100 underline-offset-4 hover:underline">Batch (FPO)</Link>
              <LanguagePicker value={lang} onChange={setLang} languages={languages} />
            </div>
          </header>
          {wake === "waking" && (
            <div className="flex items-center gap-2 bg-amber-50 px-4 py-1.5 text-sm text-amber-900" role="status">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Waking up the server…
            </div>
          )}
          {wake === "down" && (
            <div className="bg-red-50 px-4 py-1.5 text-sm text-red-900" role="alert">
              The analysis server is not answering right now. The map still works; try again in a minute.
            </div>
          )}
          <Routes>
            <Route path="/batch" element={<Batch />} />
            <Route path="/a/:id" element={<Share lang={lang} languageName={languages.find((l) => l.code === lang)?.name ?? lang} />} />
            <Route path="*" element={<Home meta={meta} lang={lang} languages={languages} />} />
          </Routes>
        </div>
      </TooltipProvider>
    </BrowserRouter>
  );
}
