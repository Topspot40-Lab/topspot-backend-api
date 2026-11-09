-- Run after the access_codes migration. All fixture changes are rolled back.
-- Uses synthetic users, never existing customers.
begin;
set local role service_role;
do $$
declare
    u uuid := gen_random_uuid();
    paid_u uuid := gen_random_uuid();
    r jsonb;
    first_date timestamptz;
    expiry timestamptz;
    n integer;
begin
    insert into public.topspot_users(id,display_name) values(u,'Access code test'),(paid_u,'Paid code test');
    insert into public.access_codes(code,access_days) values('test_access_90',90);
    insert into public.access_codes(code,access_expires_at) values('test_access_fixed',now()+interval '1 year');
    insert into public.access_codes(code) values('test_access_forever');
    insert into public.access_codes(code,active) values('test_access_disabled',false);
    insert into public.access_codes(code,redeem_by) values('test_access_late',now()-interval '1 day');
    insert into public.access_codes(code,access_expires_at) values('test_access_ended',now()-interval '1 day');

    r := public.redeem_access_code(u,'missing_code');
    assert r->>'result' = 'invalid_code', 'invalid code';
    r := public.redeem_access_code(u,'test_access_disabled');
    assert r->>'result' = 'unavailable_code', 'disabled code';
    r := public.redeem_access_code(u,'test_access_late');
    assert r->>'result' = 'unavailable_code', 'redeem deadline';
    r := public.redeem_access_code(u,'test_access_ended');
    assert r->>'result' = 'unavailable_code', 'access deadline';

    r := public.redeem_access_code(u,' TEST_ACCESS_90 ');
    assert r->>'result' = 'activated', 'normalized code';
    expiry := (r->>'access_expires_at')::timestamptz;
    assert expiry = statement_timestamp()+interval '2160 hours', '90 exact days';
    select complimentary_access_granted_at into first_date from public.topspot_users where id=u;
    update public.access_codes set active=false where code='test_access_90';
    r := public.redeem_access_code(u,'test_access_90');
    assert r->>'result' = 'already_redeemed', 'idempotent after deactivation';
    assert (r->>'access_expires_at')::timestamptz=expiry, 'does not restart duration';
    assert (select complimentary_access_granted_at from public.topspot_users where id=u)=first_date, 'keeps original date';
    select count(*) into n from public.access_code_redemptions where user_id=u;
    assert n=1, 'one redemption per user per code';

    r := public.redeem_access_code(u,'test_access_fixed');
    assert r->>'result'='activated', 'longer fixed grant';
    r := public.redeem_access_code(u,'test_access_forever');
    assert r->>'result'='activated' and r->>'access_expires_at' is null, 'no expiration';
    insert into public.access_codes(code,access_days) values('test_access_short',1);
    r := public.redeem_access_code(u,'test_access_short');
    assert r->>'result'='unchanged' and r->>'access_expires_at' is null, 'never shorten unlimited';
    r := public.redeem_access_code(u,'test_access_forever');
    assert r->>'result'='already_redeemed', 'unlimited repeat';
    r := public.redeem_access_code(u,'test_access_forever');
    assert r->>'result'='rate_limited', 'persistent attempt limit';

    -- Used codes cannot be deleted or renamed; unused codes can be deleted.
    begin
        delete from public.access_codes where code='test_access_forever';
        raise exception 'used code was deleted';
    exception when foreign_key_violation then null;
    end;
    begin
        update public.access_codes set code='renamed_test_code' where code='test_access_forever';
        raise exception using errcode='P0002', message='used code was renamed';
    exception when raise_exception then null;
    end;
    delete from public.access_codes where code='test_access_disabled';
    insert into public.subscriptions(user_id,status) values(paid_u,'active');
    r := public.redeem_access_code(paid_u,'test_access_forever');
    assert r->>'result'='paid_subscription', 'paid billing stays untouched';
    assert (select count(*) from public.access_code_redemptions where user_id=paid_u)=0, 'no paid grant';

    -- Expired grants can be replaced; shorter offers preserve dated grants.
    delete from public.subscriptions where user_id=paid_u;
    update public.topspot_users set complimentary_access=true, complimentary_access_expires_at=now()-interval '1 day' where id=paid_u;
    r := public.redeem_access_code(paid_u,'test_access_short');
    assert r->>'result'='activated', 'expired grant replaced';
    update public.topspot_users set complimentary_access_expires_at=now()+interval '1 year' where id=paid_u;
    update public.access_codes set active=true where code='test_access_90';
    r := public.redeem_access_code(paid_u,'test_access_90');
    assert r->>'result'='unchanged', 'shorter offer preserves dated access';

    assert not has_function_privilege('anon','public.redeem_access_code(uuid,text)','execute'), 'anonymous cannot call RPC';
    assert not has_function_privilege('authenticated','public.redeem_access_code(uuid,text)','execute'), 'browser cannot impersonate user';
    assert not has_table_privilege('authenticated','public.access_codes','select'), 'code list is private';
    assert not has_table_privilege('authenticated','public.access_code_redemptions','insert'), 'browser cannot grant access';
    assert has_function_privilege('service_role','public.redeem_access_code(uuid,text)','execute'), 'backend can redeem';
end;
$$;

rollback;
