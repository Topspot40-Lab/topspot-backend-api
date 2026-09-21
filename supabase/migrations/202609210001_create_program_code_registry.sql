-- Permanent public codes for fixed Program Mode programs. Radio Mode has no rows here.
create table if not exists public.program_code (
    code text primary key,
    program_kind text not null,
    decade_genre_id integer references public.decade_genre(id),
    collection_id integer references public.collection(id),
    artist_id integer references public.artist(id),
    music_docuseries_collection_id integer references public.music_docuseries_collection(id),
    is_active boolean not null default true,
    created_at timestamptz not null default now(),
    retired_at timestamptz,
    constraint program_code_format_check check (code ~ '^[NCAD]-[0-9]{3}$'),
    constraint program_code_kind_check check (program_kind in ('nostalgia', 'collection', 'artist_spotlight', 'docuseries_group')),
    constraint program_code_prefix_check check ((program_kind = 'nostalgia' and code like 'N-%') or (program_kind = 'collection' and code like 'C-%') or (program_kind = 'artist_spotlight' and code like 'A-%') or (program_kind = 'docuseries_group' and code like 'D-%')),
    constraint program_code_one_target_check check ((program_kind = 'nostalgia' and decade_genre_id is not null and collection_id is null and artist_id is null and music_docuseries_collection_id is null) or (program_kind = 'collection' and decade_genre_id is null and collection_id is not null and artist_id is null and music_docuseries_collection_id is null) or (program_kind = 'artist_spotlight' and decade_genre_id is null and collection_id is null and artist_id is not null and music_docuseries_collection_id is null) or (program_kind = 'docuseries_group' and decade_genre_id is null and collection_id is null and artist_id is null and music_docuseries_collection_id is not null)),
    constraint program_code_retirement_check check ((is_active and retired_at is null) or (not is_active and retired_at is not null))
);
create unique index if not exists uq_program_code_decade_genre on public.program_code (decade_genre_id) where decade_genre_id is not null;
create unique index if not exists uq_program_code_collection on public.program_code (collection_id) where collection_id is not null;
create unique index if not exists uq_program_code_artist on public.program_code (artist_id) where artist_id is not null;
create unique index if not exists uq_program_code_docuseries_collection on public.program_code (music_docuseries_collection_id) where music_docuseries_collection_id is not null;

create or replace function public.program_code_prevent_identity_change() returns trigger language plpgsql as $$
begin
    if tg_op = 'DELETE' then raise exception 'program codes are permanent and may not be deleted'; end if;
    if old.code is distinct from new.code or old.program_kind is distinct from new.program_kind or old.decade_genre_id is distinct from new.decade_genre_id or old.collection_id is distinct from new.collection_id or old.artist_id is distinct from new.artist_id or old.music_docuseries_collection_id is distinct from new.music_docuseries_collection_id then raise exception 'program code identity is immutable'; end if;
    return new;
end;
$$;
create or replace function public.program_code_reject_tv_themes_artist() returns trigger language plpgsql as $$
begin
    if new.program_kind = 'artist_spotlight' and exists (select 1 from public.artist_genre ag join public.genre g on g.id = ag.genre_id where ag.artist_id = new.artist_id and g.slug = 'tv_themes') then raise exception 'TV Themes artists cannot receive Artist Spotlight program codes'; end if;
    return new;
end;
$$;
create or replace function public.artist_genre_reject_tv_themes_coded_artist() returns trigger language plpgsql as $$
begin
    if exists (select 1 from public.genre g where g.id = new.genre_id and g.slug = 'tv_themes') and exists (select 1 from public.program_code pc where pc.program_kind = 'artist_spotlight' and pc.artist_id = new.artist_id) then raise exception 'TV Themes artists cannot receive Artist Spotlight program codes'; end if;
    return new;
end;
$$;
drop trigger if exists program_code_identity_immutable on public.program_code;
create trigger program_code_identity_immutable before update or delete on public.program_code for each row execute function public.program_code_prevent_identity_change();
drop trigger if exists program_code_no_tv_themes_artist on public.program_code;
create trigger program_code_no_tv_themes_artist before insert or update on public.program_code for each row execute function public.program_code_reject_tv_themes_artist();
drop trigger if exists artist_genre_no_tv_themes_coded_artist on public.artist_genre;
create trigger artist_genre_no_tv_themes_coded_artist before insert or update of artist_id, genre_id on public.artist_genre for each row execute function public.artist_genre_reject_tv_themes_coded_artist();
