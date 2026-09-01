begin;

create unique index if not exists unique_topspot_users_stripe_customer_id
    on public.topspot_users(stripe_customer_id)
    where stripe_customer_id is not null;

commit;
