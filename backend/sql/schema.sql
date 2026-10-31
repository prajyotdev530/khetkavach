-- KhetKavach Supabase schema (BUILD_SPEC §11). Run once in the Supabase SQL editor.
-- The backend uses the service-role key (server side only), so row-level security stays ON with no public
-- policies: browsers can never read or write these tables directly.

-- Cache of real provider responses, each with the time it was originally fetched.
create table if not exists public.cache (
  key        text primary key,
  value      jsonb not null,
  source     text not null,
  fetched_at timestamptz not null,
  expires_at timestamptz
);
create index if not exists cache_expires_at_idx on public.cache (expires_at);

-- Finished analyses, read back by the share page /a/:id (F15).
create table if not exists public.analyses (
  id         uuid primary key,
  created_at timestamptz not null default now(),
  lat        double precision not null,
  lon        double precision not null,
  crop       text not null,
  payload    jsonb not null
);

-- Translations and text-to-speech audio, keyed by sha256(model + language + voice + text). Permanent.
create table if not exists public.media (
  key        text primary key,
  lang       text not null,
  kind       text not null,          -- 'translation' or 'audio'
  data       text not null,          -- JSON text for translations, base64 WAV for audio
  created_at timestamptz not null default now()
);

alter table public.cache    enable row level security;
alter table public.analyses enable row level security;
alter table public.media    enable row level security;
