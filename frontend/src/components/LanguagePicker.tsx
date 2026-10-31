// LanguagePicker: the 9 languages that have both text and voice in Sarvam Bulbul v4, each in its own script.
import type { Language } from "@/lib/api";

export const DEFAULT_LANGUAGES: Language[] = [
  { code: "en-IN", name: "English" }, { code: "hi-IN", name: "हिन्दी" }, { code: "mr-IN", name: "मराठी" },
  { code: "bn-IN", name: "বাংলা" }, { code: "gu-IN", name: "ગુજરાતી" }, { code: "kn-IN", name: "ಕನ್ನಡ" },
  { code: "pa-IN", name: "ਪੰਜਾਬੀ" }, { code: "ta-IN", name: "தமிழ்" }, { code: "te-IN", name: "తెలుగు" },
];

export function LanguagePicker({ value, onChange, languages }: { value: string; onChange: (code: string) => void; languages: Language[] }) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="sr-only sm:not-sr-only sm:text-brand-100">Language</span>
      <select
        className="min-h-[40px] rounded-md border border-white/30 bg-white px-2 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-white"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label="Language for the plan and voice"
      >
        {languages.map((l) => <option key={l.code} value={l.code}>{l.name}</option>)}
      </select>
    </label>
  );
}
