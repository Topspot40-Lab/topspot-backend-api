begin;

alter table public.topspot_users enable row level security;

revoke all on table public.topspot_users from public;
revoke all on table public.topspot_users from anon;
revoke all on table public.topspot_users from authenticated;

grant all on table public.topspot_users to service_role;

commit;
