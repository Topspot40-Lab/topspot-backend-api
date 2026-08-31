begin;

alter table public.topspot_users
    add column if not exists complimentary_access boolean not null default false,
    add column if not exists complimentary_access_expires_at timestamp with time zone,
    add column if not exists complimentary_access_reason text;

-- Keep public.topspot_users.is_tester for now. Drop it only after this deployment
-- has been verified in production and any external consumers have been audited.

commit;
