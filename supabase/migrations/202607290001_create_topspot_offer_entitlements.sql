begin;

create table public.topspot_offer_entitlements (
    id uuid primary key default gen_random_uuid(),

    user_id uuid not null
        references public.topspot_users(id)
        on delete cascade,

    offer_code text not null,

    eligibility_source text not null,
    qualified_user_created_at timestamp with time zone not null,

    free_access_expires_at timestamp with time zone not null,
    grace_access_expires_at timestamp with time zone not null,

    discount_redeemed_at timestamp with time zone,
    discount_consumed_at timestamp with time zone,
    discount_stripe_subscription_id text,
    discount_stripe_customer_id text,
    discount_ended_at timestamp with time zone,
    discount_end_reason text,

    standard_transition_at timestamp with time zone not null,

    created_at timestamp with time zone not null default now(),
    updated_at timestamp with time zone not null default now(),

    constraint topspot_offer_entitlements_user_offer_key
        unique (user_id, offer_code),

    constraint topspot_offer_entitlements_offer_code_check
        check (btrim(offer_code) <> ''),

    constraint topspot_offer_entitlements_eligibility_source_check
        check (btrim(eligibility_source) <> ''),

    constraint topspot_offer_entitlements_access_order_check
        check (
            free_access_expires_at <= grace_access_expires_at
            and grace_access_expires_at <= standard_transition_at
        ),

    constraint topspot_offer_entitlements_discount_consumed_requires_redeemed_check
        check (
            discount_consumed_at is null
            or discount_redeemed_at is not null
        ),

    constraint topspot_offer_entitlements_discount_consumed_order_check
        check (
            discount_redeemed_at is null
            or discount_consumed_at is null
            or discount_redeemed_at <= discount_consumed_at
        ),

    constraint topspot_offer_entitlements_discount_ended_order_check
        check (
            discount_redeemed_at is null
            or discount_ended_at is null
            or discount_redeemed_at <= discount_ended_at
        ),

    constraint topspot_offer_entitlements_discount_end_reason_not_blank_check
        check (
            discount_end_reason is null
            or btrim(discount_end_reason) <> ''
        ),

    constraint topspot_offer_entitlements_discount_subscription_not_blank_check
        check (
            discount_stripe_subscription_id is null
            or btrim(discount_stripe_subscription_id) <> ''
        ),

    constraint topspot_offer_entitlements_discount_customer_not_blank_check
        check (
            discount_stripe_customer_id is null
            or btrim(discount_stripe_customer_id) <> ''
        )
);

create index idx_topspot_offer_entitlements_discount_subscription
    on public.topspot_offer_entitlements(discount_stripe_subscription_id)
    where discount_stripe_subscription_id is not null;

create index idx_topspot_offer_entitlements_discount_customer
    on public.topspot_offer_entitlements(discount_stripe_customer_id)
    where discount_stripe_customer_id is not null;

drop trigger if exists update_topspot_offer_entitlements_updated_at
on public.topspot_offer_entitlements;

create trigger update_topspot_offer_entitlements_updated_at
before update on public.topspot_offer_entitlements
for each row
execute function public.update_updated_at_column();

alter table public.topspot_offer_entitlements enable row level security;

revoke all on table public.topspot_offer_entitlements from anon;
revoke all on table public.topspot_offer_entitlements from authenticated;

grant all on table public.topspot_offer_entitlements to service_role;

insert into public.topspot_offer_entitlements (
    user_id,
    offer_code,
    eligibility_source,
    qualified_user_created_at,
    free_access_expires_at,
    grace_access_expires_at,
    standard_transition_at
)
select
    u.id,
    'topspot_2026_free_2027_discount',
    'topspot_users.created_at',
    u.created_at,
    timestamp '2027-01-01 00:00:00' at time zone 'America/Chicago',
    timestamp '2027-01-31 00:00:00' at time zone 'America/Chicago',
    timestamp '2028-01-01 00:00:00' at time zone 'America/Chicago'
from public.topspot_users u
where u.created_at < (
    timestamp '2027-01-01 00:00:00'
    at time zone 'America/Chicago'
)
on conflict (user_id, offer_code) do nothing;

commit;
