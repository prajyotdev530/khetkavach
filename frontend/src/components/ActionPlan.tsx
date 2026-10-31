// ActionPlan (F8): 3-5 dated action cards ("by 6 Nov"), each with the action, a one-line reason and citation
// chips (hover shows source, value and fetch time). When a translation exists it is shown instead; any line whose
// numbers did not survive translation stays in English with an "(English)" tag.
import { CalendarDays } from "lucide-react";
import type { Action } from "@/lib/api";
import type { RunState } from "@/lib/sse";
import { shortDate } from "@/lib/format";
import { CitationChip } from "./SourceBadge";
import { Skeleton } from "./ui/skeleton";
import { VoicePlayer } from "./VoicePlayer";

function ActionCard({ a, english }: { a: Action; english?: Action }) {
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-brand-700">
        <CalendarDays className="h-3.5 w-3.5" aria-hidden /> by {shortDate(a.by_date)}
        {a.english_fallback && <span className="font-normal text-slate-500">(English)</span>}
      </div>
      <p className="mt-1 text-sm font-medium text-slate-900">{a.action}</p>
      <p className="mt-0.5 text-xs text-slate-700">{a.reason}</p>
      {(english ?? a).citations.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {(english ?? a).citations.map((c, i) => <CitationChip key={i} c={c} />)}
        </div>
      )}
    </li>
  );
}

export function ActionPlan({ run, lang, languageName, translationError }: {
  run: RunState; lang: string; languageName: string; translationError: string | null;
}) {
  if (!run.plan) {
    if (run.status !== "running") return <p className="p-2 text-sm text-slate-600">The action plan appears after the risk is scored.</p>;
    return <div className="space-y-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-20 w-full" />)}</div>;
  }
  const tr = run.translation && run.translation.lang === lang && lang !== "en-IN" ? run.translation : null;
  const actions = tr ? tr.actions : run.plan.actions;
  const summary = tr ? tr.summary : run.plan.summary;
  return (
    <div className="space-y-2">
      {run.analysisId && (
        <VoicePlayer analysisId={run.analysisId} lang={lang} languageName={languageName}
          auto={lang !== "en-IN" && (!!tr || !!translationError)} />
      )}
      {translationError && lang !== "en-IN" && (
        <p className="rounded-md bg-amber-50 px-2 py-1 text-xs text-amber-900">{translationError}. Showing English.</p>
      )}
      {lang !== "en-IN" && !tr && !translationError && run.status === "done" && (
        <p className="text-xs text-slate-500">Translating…</p>
      )}
      {run.plan.source === "rules" && (
        <p className="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-700">Plan generated from rules (AI writer unavailable); every number is still cited.</p>
      )}
      <p className="text-sm leading-relaxed text-slate-900">
        {summary}
        {tr?.summary_english_fallback && <span className="text-xs text-slate-500"> (English)</span>}
      </p>
      <ul className="space-y-2">
        {actions.map((a, i) => <ActionCard key={i} a={a} english={run.plan!.actions[i]} />)}
      </ul>
      {run.validation && (
        <p className="text-[11px] text-slate-500">
          Citation check: {run.validation.numbers_checked} numbers checked, {run.validation.numbers_rejected} rejected.
          No pesticide or fertiliser doses are given; consult your local KVK or agriculture officer.
        </p>
      )}
    </div>
  );
}
