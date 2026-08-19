begin;

create table if not exists public.marketing_email_preferences (
    user_id uuid primary key
        references public.topspot_users(id)
        on delete cascade,

    marketing_opt_in boolean not null default false,
    marketing_opt_in_at timestamp with time zone,
    marketing_unsubscribed_at timestamp with time zone,
    consent_source text,

    created_at timestamp with time zone not null default now(),
    updated_at timestamp with time zone not null default now()
);

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'marketing_email_preferences_opt_in_validity_check'
        and conrelid = 'public.marketing_email_preferences'::regclass
    ) then
        alter table public.marketing_email_preferences
            add constraint marketing_email_preferences_opt_in_validity_check
            check (
                marketing_opt_in = false
                or (
                    marketing_opt_in_at is not null
                    and marketing_unsubscribed_at is null
                )
            );
    end if;
end;
$$;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'marketing_email_preferences_consent_source_check'
        and conrelid = 'public.marketing_email_preferences'::regclass
    ) then
        alter table public.marketing_email_preferences
            add constraint marketing_email_preferences_consent_source_check
            check (
                consent_source is null
                or btrim(consent_source) <> ''
            );
    end if;
end;
$$;

alter table public.marketing_email_preferences enable row level security;

revoke all on table public.marketing_email_preferences from public;
revoke all on table public.marketing_email_preferences from anon;
revoke all on table public.marketing_email_preferences from authenticated;

grant all on table public.marketing_email_preferences to service_role;

commit;
