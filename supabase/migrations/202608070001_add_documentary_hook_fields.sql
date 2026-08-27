alter table public.artist_story add column if not exists hook_text text, add column if not exists hook_tts_bucket text, add column if not exists hook_tts_key text;
alter table public.music_docuseries_locale add column if not exists hook_text text, add column if not exists hook_tts_bucket text, add column if not exists hook_tts_key text;
