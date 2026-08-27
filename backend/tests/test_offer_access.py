from datetime import datetime, timedelta, timezone

import pytest

from backend.isaiah.offer_access import (
    OFFER_CODE,
    compute_offer_access,
    parse_supabase_timestamptz,
    utc_now,
)


FREE_EXPIRES = "2027-01-01T06:00:00+00:00"
GRACE_EXPIRES = "2027-01-31T06:00:00+00:00"
STANDARD_TRANSITION = "2028-01-01T06:00:00+00:00"


def entitlement(**overrides):
    base = {
        "offer_code": OFFER_CODE,
        "free_access_expires_at": FREE_EXPIRES,
        "grace_access_expires_at": GRACE_EXPIRES,
        "standard_transition_at": STANDARD_TRANSITION,
        "discount_consumed_at": None,
    }
    base.update(overrides)
    return base


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_utc_now_returns_aware_utc_datetime():
    result = utc_now()

    assert result.tzinfo is timezone.utc
    assert result.utcoffset().total_seconds() == 0


def test_no_entitlement():
    assert compute_offer_access(None) == {
        "access_state": "none",
        "access_source": "none",
        "is_subscribed": False,
        "status": "inactive",
        "requires_checkout": True,
        "eligible_for_2027_discount": False,
        "discount_used": False,
        "discount_available": False,
    }


def test_free_access_immediately_before_free_boundary():
    result = compute_offer_access(
        entitlement(),
        now=dt("2027-01-01T05:59:59.999999+00:00"),
    )

    assert result["access_state"] == "free_2026"
    assert result["access_source"] == "offer"
    assert result["is_subscribed"] is True
    assert result["status"] == "free_2026"
    assert result["requires_checkout"] is False
    assert result["access_expires_at"] == FREE_EXPIRES


def test_exactly_at_free_boundary_becomes_grace():
    result = compute_offer_access(entitlement(), now=dt(FREE_EXPIRES))

    assert result["access_state"] == "grace_2027"
    assert result["access_source"] == "offer_grace"
    assert result["is_subscribed"] is True
    assert result["status"] == "grace_2027"
    assert result["requires_checkout"] is True
    assert result["access_expires_at"] == GRACE_EXPIRES


def test_during_grace():
    result = compute_offer_access(
        entitlement(),
        now=dt("2027-01-15T12:00:00+00:00"),
    )

    assert result["access_state"] == "grace_2027"


def test_immediately_before_grace_boundary():
    result = compute_offer_access(
        entitlement(),
        now=dt("2027-01-31T05:59:59.999999+00:00"),
    )

    assert result["access_state"] == "grace_2027"
    assert result["access_expires_at"] == GRACE_EXPIRES


def test_exactly_at_grace_boundary_becomes_expired():
    result = compute_offer_access(entitlement(), now=dt(GRACE_EXPIRES))

    assert result["access_state"] == "expired"
    assert result["access_source"] == "none"
    assert result["is_subscribed"] is False
    assert result["status"] == "expired"
    assert result["requires_checkout"] is True
    assert "access_expires_at" not in result


def test_after_grace_is_expired():
    result = compute_offer_access(
        entitlement(),
        now=dt("2027-02-01T00:00:00+00:00"),
    )

    assert result["access_state"] == "expired"


def test_discount_consumed_at_null_means_available_and_unused():
    result = compute_offer_access(entitlement(discount_consumed_at=None), now=dt(FREE_EXPIRES))

    assert result["discount_used"] is False
    assert result["discount_available"] is True


def test_discount_consumed_at_set_means_unavailable_and_used():
    result = compute_offer_access(
        entitlement(discount_consumed_at="2027-01-10T00:00:00+00:00"),
        now=dt(FREE_EXPIRES),
    )

    assert result["discount_used"] is True
    assert result["discount_available"] is False


def test_unused_discount_available_immediately_before_standard_transition():
    result = compute_offer_access(
        entitlement(discount_consumed_at=None),
        now=dt("2028-01-01T05:59:59.999999+00:00"),
    )

    assert result["discount_used"] is False
    assert result["discount_available"] is True


def test_unused_discount_unavailable_exactly_at_standard_transition():
    result = compute_offer_access(
        entitlement(discount_consumed_at=None),
        now=dt(STANDARD_TRANSITION),
    )

    assert result["discount_used"] is False
    assert result["discount_available"] is False


def test_supabase_timestamp_string_with_plus_utc_offset():
    result = parse_supabase_timestamptz("2027-01-01T06:00:00+00:00")

    assert result == dt("2027-01-01T06:00:00+00:00")


def test_supabase_timestamp_string_ending_in_z():
    result = parse_supabase_timestamptz("2027-01-01T06:00:00Z")

    assert result == dt("2027-01-01T06:00:00+00:00")


def test_aware_datetime_normalization_to_utc():
    chicago_time = datetime(2027, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=-6)))

    result = parse_supabase_timestamptz(chicago_time)

    assert result == dt("2027-01-01T06:00:00+00:00")


def test_naive_entitlement_datetime_raises_value_error():
    with pytest.raises(ValueError):
        compute_offer_access(
            entitlement(free_access_expires_at=datetime(2027, 1, 1, 0, 0)),
            now=dt("2026-12-31T00:00:00+00:00"),
        )


def test_naive_injected_now_raises_value_error():
    with pytest.raises(ValueError):
        compute_offer_access(entitlement(), now=datetime(2027, 1, 1, 0, 0))


def test_malformed_timestamp_raises_value_error():
    with pytest.raises(ValueError):
        parse_supabase_timestamptz("not-a-timestamp")


@pytest.mark.parametrize("missing_field", ["free_access_expires_at", "grace_access_expires_at"])
def test_missing_required_expiration_raises_value_error(missing_field):
    data = entitlement()
    data.pop(missing_field)

    with pytest.raises(ValueError):
        compute_offer_access(data, now=dt("2026-12-31T00:00:00+00:00"))


def test_free_expiration_later_than_grace_expiration_raises_value_error():
    with pytest.raises(ValueError):
        compute_offer_access(
            entitlement(
                free_access_expires_at="2027-02-01T00:00:00+00:00",
                grace_access_expires_at=GRACE_EXPIRES,
            ),
            now=dt("2026-12-31T00:00:00+00:00"),
        )


def test_blank_offer_code_raises_value_error():
    with pytest.raises(ValueError):
        compute_offer_access(
            entitlement(offer_code=" "),
            now=dt("2026-12-31T00:00:00+00:00"),
        )
