-- Access codes are managed through the Supabase table editor by administrators.
-- No examples are activated automatically.
create table public.access_codes (
    id uuid primary key default gen_random_uuid(),
    code text not null unique check (code = lower(btrim(code)) and code ~ '^[a-z0-9_-]{3,64}$'),
    active boolean not null default true,
    description text,
    redeem_by timestamptz,
    access_expires_at timestamptz,
    access_days integer check (access_days between 1 and 36500),
    created_at timestamptz not null default now(),
    constraint access_code_one_expiration check (access_expires_at is null or access_days is null)
);
comment on column public.access_codes.redeem_by is 'Exclusive UTC deadline for new redemptions. NULL means no redemption deadline.';
comment on column public.access_codes.access_expires_at is 'Exclusive UTC end of granted access. Leave this and access_days blank for no expiration.';
comment on column public.access_codes.access_days is 'Days from first redemption; repeat redemption never restarts the offer.';

alter table public.topspot_users
    add column complimentary_access_code text,
    add column complimentary_access_granted_at timestamptz;

create table public.access_code_redemptions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.topspot_users(id) on delete cascade,
    access_code_id uuid not null references public.access_codes(id) on delete restrict,
    code text not null,
    redeemed_at timestamptz not null default now(),
    granted_expires_at timestamptz,
    access_changed boolean not null,
    unique (user_id, access_code_id)
);
create index access_code_redemptions_code_idx on public.access_code_redemptions(access_code_id);
create table public.access_code_attempts (
    user_id uuid primary key references public.topspot_users(id) on delete cascade,
    window_started_at timestamptz not null,
    attempts integer not null check (attempts between 1 and 10)
);

alter table public.access_codes enable row level security;
alter table public.access_code_redemptions enable row level security;
alter table public.access_code_attempts enable row level security;
revoke all on public.access_codes, public.access_code_redemptions, public.access_code_attempts from anon, authenticated;
grant all on public.access_codes, public.access_code_redemptions, public.access_code_attempts to service_role;

create function public.redeem_access_code(p_user_id uuid, p_code text)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
    v_user public.topspot_users%rowtype;
    v_code public.access_codes%rowtype;
    v_prior public.access_code_redemptions%rowtype;
    v_attempt public.access_code_attempts%rowtype;
    v_now timestamptz := statement_timestamp();
    v_expiry timestamptz;
    v_current boolean;
    v_changed boolean;
begin
    -- Called only by the authenticated FastAPI backend using its service role.
    -- Locking the user serializes concurrent grants and attempt counting.
    select * into v_user from public.topspot_users where id = p_user_id for update;
    if not found then return jsonb_build_object('result', 'sign_in_required'); end if;

    select * into v_attempt from public.access_code_attempts where user_id = p_user_id;
    if found and v_attempt.window_started_at > v_now - interval '15 minutes' then
        if v_attempt.attempts >= 10 then
            return jsonb_build_object('result', 'rate_limited');
        end if;
        update public.access_code_attempts set attempts = attempts + 1 where user_id = p_user_id;
    else
        insert into public.access_code_attempts values (p_user_id, v_now, 1)
        on conflict (user_id) do update set window_started_at = v_now, attempts = 1;
    end if;

    select * into v_code from public.access_codes where code = lower(btrim(p_code)) for share;
    if not found then return jsonb_build_object('result', 'invalid_code'); end if;
    select * into v_prior from public.access_code_redemptions
        where user_id = p_user_id and access_code_id = v_code.id;
    if found then
        return jsonb_build_object('result', 'already_redeemed',
            'complimentary_access', v_user.complimentary_access,
            'access_expires_at', v_user.complimentary_access_expires_at,
            'redeemed_at', v_prior.redeemed_at);
    end if;
    if not v_code.active or (v_code.redeem_by is not null and v_code.redeem_by <= v_now)
        or (v_code.access_expires_at is not null and v_code.access_expires_at <= v_now) then
        return jsonb_build_object('result', 'unavailable_code');
    end if;
    -- Do not imply that applying a code cancels an existing Stripe subscription.
    if exists (select 1 from public.subscriptions where user_id = p_user_id and status in ('active', 'past_due')) then
        return jsonb_build_object('result', 'paid_subscription');
    end if;

    v_expiry := case when v_code.access_days is not null
        then v_now + v_code.access_days * interval '24 hours'
        else v_code.access_expires_at end;
    v_current := v_user.complimentary_access and
        (v_user.complimentary_access_expires_at is null or v_user.complimentary_access_expires_at > v_now);
    v_changed := not v_current or
        (v_user.complimentary_access_expires_at is not null and
            (v_expiry is null or v_expiry > v_user.complimentary_access_expires_at));

    insert into public.access_code_redemptions(user_id, access_code_id, code, granted_expires_at, access_changed, redeemed_at)
        values (p_user_id, v_code.id, v_code.code, v_expiry, v_changed, v_now);
    if v_changed then
        update public.topspot_users set complimentary_access = true,
            complimentary_access_expires_at = v_expiry,
            complimentary_access_code = v_code.code,
            complimentary_access_granted_at = v_now,
            complimentary_access_reason = 'Access code redemption'
        where id = p_user_id;
        return jsonb_build_object('result', 'activated', 'complimentary_access', true,
            'access_expires_at', v_expiry, 'redeemed_at', v_now);
    end if;
    return jsonb_build_object('result', 'unchanged', 'complimentary_access', true,
        'access_expires_at', v_user.complimentary_access_expires_at, 'redeemed_at', v_now);
end;
$$;
revoke all on function public.redeem_access_code(uuid, text) from public, anon, authenticated;
grant execute on function public.redeem_access_code(uuid, text) to service_role;

-- Preserve code identity after use; edit terms for future redemptions or deactivate.
create function public.keep_redeemed_access_code() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
    if new.code is distinct from old.code and exists (
        select 1 from public.access_code_redemptions where access_code_id = old.id
    ) then
        raise exception 'Used codes cannot be renamed. Deactivate this code and create a new one.';
    end if;
    return new;
end;
$$;
revoke all on function public.keep_redeemed_access_code() from public, anon, authenticated;
grant execute on function public.keep_redeemed_access_code() to service_role;
create trigger keep_redeemed_access_code before update of code on public.access_codes
    for each row execute function public.keep_redeemed_access_code();
