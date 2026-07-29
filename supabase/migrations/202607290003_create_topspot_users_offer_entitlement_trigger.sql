begin;

drop trigger if exists create_topspot_offer_entitlement_after_insert
on public.topspot_users;

drop function if exists public.create_topspot_offer_entitlement_for_new_user();

create function public.create_topspot_offer_entitlement_for_new_user()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
    if new.created_at < (
        timestamp '2027-01-01 00:00:00'
        at time zone 'America/Chicago'
    ) then
        insert into public.topspot_offer_entitlements (
            user_id,
            offer_code,
            eligibility_source,
            qualified_user_created_at,
            free_access_expires_at,
            grace_access_expires_at,
            standard_transition_at
        )
        values (
            new.id,
            'topspot_2026_free_2027_discount',
            'topspot_users.created_at',
            new.created_at,
            timestamp '2027-01-01 00:00:00'
                at time zone 'America/Chicago',
            timestamp '2027-01-31 00:00:00'
                at time zone 'America/Chicago',
            timestamp '2028-01-01 00:00:00'
                at time zone 'America/Chicago'
        )
        on conflict (user_id, offer_code) do nothing;
    end if;

    return new;
end;
$$;

revoke all
on function public.create_topspot_offer_entitlement_for_new_user()
from public;

revoke all
on function public.create_topspot_offer_entitlement_for_new_user()
from anon;

revoke all
on function public.create_topspot_offer_entitlement_for_new_user()
from authenticated;

create trigger create_topspot_offer_entitlement_after_insert
after insert on public.topspot_users
for each row
execute function public.create_topspot_offer_entitlement_for_new_user();

commit;
