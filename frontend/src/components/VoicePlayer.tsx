// VoicePlayer (F9): plays the plan aloud in the selected language (Sarvam Bulbul v4 Flash, via the backend).
// Play/pause, a progress bar, the language name and a "Voice by Sarvam" note. The button is disabled (with a
// tooltip) while audio is generating, and shows "Voice unavailable" if Sarvam fails; the text always stays.
import { useEffect, useRef, useState } from "react";
import { Loader2, Pause, Play, VolumeX } from "lucide-react";
import { postJson } from "@/lib/api";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

type VoiceState = "idle" | "generating" | "ready" | "unavailable";

export function VoicePlayer({ analysisId, lang, languageName, auto }: {
  analysisId: string; lang: string; languageName: string; auto: boolean;
}) {
  const [state, setState] = useState<VoiceState>("idle");
  const [url, setUrl] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const wantPlay = useRef(false);

  // A new analysis or language means new audio.
  useEffect(() => {
    setState("idle"); setPlaying(false); setProgress(0); setDuration(0);
    setUrl((old) => { if (old) URL.revokeObjectURL(old); return null; });
    wantPlay.current = false;
  }, [analysisId, lang]);

  const inFlight = useRef<string | null>(null);
  const generate = async () => {
    const key = `${analysisId}:${lang}`;
    if (inFlight.current === key) return; // one request per analysis+language (React may run effects twice)
    inFlight.current = key;
    setState("generating");
    try {
      const res = await postJson<{ audio_base64: string; mime: string }>("/api/tts", { analysis_id: analysisId, lang }, 45000);
      const bytes = Uint8Array.from(atob(res.audio_base64), (c) => c.charCodeAt(0));
      setUrl(URL.createObjectURL(new Blob([bytes], { type: res.mime })));
      setState("ready");
    } catch {
      setState("unavailable");
    } finally {
      inFlight.current = null;
    }
  };

  useEffect(() => {
    if (auto && state === "idle") generate();
  }, [auto, state]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (url && wantPlay.current) { wantPlay.current = false; audioRef.current?.play(); }
  }, [url]);

  const toggle = () => {
    if (state === "idle") { wantPlay.current = true; generate(); return; }
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) a.play(); else a.pause();
  };

  const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
  const button = (
    <button
      type="button"
      onClick={toggle}
      disabled={state === "generating" || state === "unavailable"}
      aria-label={playing ? "Pause" : `Play the plan in ${languageName}`}
      className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-brand-700 text-white hover:bg-brand-900 disabled:bg-slate-300"
    >
      {state === "generating" ? <Loader2 className="h-5 w-5 animate-spin" /> : state === "unavailable" ? <VolumeX className="h-5 w-5" />
        : playing ? <Pause className="h-5 w-5" /> : <Play className="ml-0.5 h-5 w-5" />}
    </button>
  );

  return (
    <div className="flex items-center gap-3 rounded-lg border border-brand-100 bg-brand-50 p-2">
      {state === "generating" || state === "unavailable" ? (
        <Tooltip>
          <TooltipTrigger asChild><span tabIndex={0}>{button}</span></TooltipTrigger>
          <TooltipContent>{state === "generating" ? "Generating audio…" : "Voice unavailable right now"}</TooltipContent>
        </Tooltip>
      ) : button}
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between text-xs">
          <span className="font-semibold text-brand-900">{state === "unavailable" ? "Voice unavailable" : `Listen in ${languageName}`}</span>
          <span className="font-mono text-slate-600">{duration ? `${fmt(progress)} / ${fmt(duration)}` : ""}</span>
        </div>
        <input
          type="range" min={0} max={duration || 1} step={0.1} value={progress} disabled={!url}
          aria-label="Playback position"
          className="h-2 w-full accent-brand-700"
          onChange={(e) => { if (audioRef.current) audioRef.current.currentTime = Number(e.target.value); }}
        />
        <div className="text-[10px] text-slate-500">Voice by Sarvam (Bulbul v4)</div>
      </div>
      {url && (
        <audio
          ref={audioRef} src={url} preload="auto"
          onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)}
          onTimeUpdate={(e) => setProgress(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        />
      )}
    </div>
  );
}
