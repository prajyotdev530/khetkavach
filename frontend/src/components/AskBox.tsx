// AskBox (F11): the farmer asks a question about this analysis by voice (≤ 30 s, Sarvam Saaras speech-to-text
// with language auto-detect) or by typing. The answer uses only this analysis's data and cites its numbers.
import { useRef, useState } from "react";
import { Loader2, Mic, Send, Square } from "lucide-react";
import { API_URL, postJson, type Citation } from "@/lib/api";
import { CitationChip } from "./SourceBadge";

interface Answer {
  question: string;
  answer: string;
  citations: Citation[];
  source: "llm" | "rules";
  english_fallback?: boolean;
}

const PLACEHOLDER: Record<string, string> = {
  "hi-IN": "क्या मुझे इस हफ्ते सिंचाई करनी चाहिए?", "mr-IN": "मी या आठवड्यात पाणी द्यावे का?",
};

export function AskBox({ analysisId, lang }: { analysisId: string; lang: string }) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Answer[]>([]);
  const recRef = useRef<MediaRecorder | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const ask = async (question: string) => {
    if (!question.trim()) return;
    setBusy(true); setErr(null);
    try {
      const res = await postJson<Answer>("/api/ask", { analysis_id: analysisId, question, lang }, 45000);
      setAnswers((a) => [res, ...a]); setQ("");
    } catch (e: any) {
      setErr(e?.message ?? "Could not answer right now");
    } finally { setBusy(false); }
  };

  const sendAudio = async (blob: Blob) => {
    setBusy(true); setErr(null);
    const form = new FormData();
    form.append("file", blob, "question.webm");
    form.append("analysis_id", analysisId);
    form.append("lang", lang);
    try {
      const res = await fetch(`${API_URL}/api/ask`, { method: "POST", body: form });
      const body = await res.json();
      if (!res.ok) throw body;
      setAnswers((a) => [body, ...a]);
    } catch (e: any) {
      setErr(e?.message ?? "Voice input unavailable right now. Please type your question.");
    } finally { setBusy(false); }
  };

  const toggleMic = async () => {
    if (recording) { recRef.current?.stop(); return; }
    setErr(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = () => {
        window.clearTimeout(timer.current);
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        sendAudio(new Blob(chunks, { type: rec.mimeType || "audio/webm" }));
      };
      recRef.current = rec;
      rec.start();
      setRecording(true);
      timer.current = window.setTimeout(() => rec.state === "recording" && rec.stop(), 30000);
    } catch {
      setErr("Microphone not available. Please type your question.");
    }
  };

  return (
    <section className="mt-3 rounded-lg border border-slate-200 bg-white p-3" aria-label="Ask a question">
      <h3 className="text-sm font-semibold text-slate-900">Ask about this farm</h3>
      <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); ask(q); }}>
        <button type="button" onClick={toggleMic} disabled={busy}
          aria-label={recording ? "Stop recording" : "Ask by voice (up to 30 seconds)"}
          className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-full ${recording ? "animate-pulse bg-high text-white" : "bg-brand-50 text-brand-900 hover:bg-brand-100"} disabled:opacity-50`}>
          {recording ? <Square className="h-4 w-4" /> : <Mic className="h-5 w-5" />}
        </button>
        <input className="min-h-[44px] min-w-0 flex-1 rounded-md border border-slate-300 px-3 text-sm" value={q}
          onChange={(e) => setQ(e.target.value)} placeholder={PLACEHOLDER[lang] ?? "Should I irrigate this week?"}
          aria-label="Your question" />
        <button type="submit" disabled={busy || !q.trim()} aria-label="Ask"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md bg-brand-700 text-white disabled:bg-slate-300">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        </button>
      </form>
      {recording && <p className="mt-1 text-xs text-high-text">Listening… tap the square to stop (max 30 s).</p>}
      {err && <p className="mt-1 text-xs text-high-text" role="alert">{err}</p>}
      <ul className="mt-2 space-y-2">
        {answers.map((a, i) => (
          <li key={i} className="rounded-md bg-slate-50 p-2 text-sm">
            <p className="text-xs text-slate-600">Q: {a.question}</p>
            <p className="mt-1 text-slate-900">{a.answer}{a.english_fallback && <span className="text-xs text-slate-500"> (English)</span>}</p>
            {a.citations.length > 0 && <div className="mt-1 flex flex-wrap gap-1">{a.citations.map((c, j) => <CitationChip key={j} c={c} />)}</div>}
            {a.source === "rules" && <p className="mt-1 text-[11px] text-slate-500">Answered from rules (AI unavailable).</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}
