begin;

alter table public.topspot_users
    add column if not exists preferred_language text;

alter table public.topspot_users
    add constraint topspot_users_preferred_language_check
    check (preferred_language is null or preferred_language in ('en', 'es', 'pt-BR'));

alter table public.topspot_users
    add constraint topspot_users_display_name_check
    check (
        display_name is null
        or char_length(btrim(display_name)) between 2 and 50
    );

create or replace function public.complete_topspot_user_display_name(
    p_user_id uuid,
    p_display_name text
)
returns table (id uuid, display_name text)
language sql
security definer
set search_path = pg_catalog, public
as $$
    update public.topspot_users
    set display_name = p_display_name
    where id = p_user_id
      and (display_name is null or btrim(display_name) = '')
    returning topspot_users.id, topspot_users.display_name;
$$;

revoke all on function public.complete_topspot_user_display_name(uuid, text)
from public;
revoke all on function public.complete_topspot_user_display_name(uuid, text)
from anon;
revoke all on function public.complete_topspot_user_display_name(uuid, text)
from authenticated;
grant execute on function public.complete_topspot_user_display_name(uuid, text)
to service_role;

commit;
