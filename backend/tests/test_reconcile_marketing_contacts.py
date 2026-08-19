from unittest.mock import MagicMock, patch

from backend.scripts.reconcile_marketing_contacts import reconcile


def _make_supabase(preferences: list[dict], users: list[dict]) -> MagicMock:
    def table(name: str) -> MagicMock:
        mock_table = MagicMock()

        if name == "marketing_email_preferences":
            mock_table.select.return_value.execute.return_value.data = preferences
        elif name == "topspot_users":
            mock_table.select.return_value.in_.return_value.execute.return_value.data = users
        else:
            raise AssertionError(f"Unexpected table: {name}")

        return mock_table

    supabase = MagicMock()
    supabase.table.side_effect = table
    return supabase


# =====================================================
# a) dry-run does not call Resend
# =====================================================

def test_dry_run_does_not_call_resend():
    preferences = [{"user_id": "u1", "marketing_opt_in": True}]
    users = [{"id": "u1", "email": "User@Example.com"}]
    supabase = _make_supabase(preferences, users)

    with patch(
        "backend.scripts.reconcile_marketing_contacts.set_contact_unsubscribed"
    ) as mock_set:
        summary = reconcile(supabase, apply=False)

    mock_set.assert_not_called()
    assert summary.synced == 0
    assert summary.skipped == 0
    assert summary.failed == 0
    assert len(summary.items) == 1
    assert summary.items[0].email == "user@example.com"
    assert summary.items[0].desired_unsubscribed is False


# =====================================================
# b) --apply with marketing_opt_in=true calls
#    set_contact_unsubscribed(email, False)
# =====================================================

def test_apply_opted_in_calls_resend_with_unsubscribed_false():
    preferences = [{"user_id": "u1", "marketing_opt_in": True}]
    users = [{"id": "u1", "email": "User@Example.com"}]
    supabase = _make_supabase(preferences, users)

    with patch(
        "backend.scripts.reconcile_marketing_contacts.set_contact_unsubscribed"
    ) as mock_set:
        summary = reconcile(supabase, apply=True)

    mock_set.assert_called_once_with("user@example.com", False)
    assert summary.synced == 1
    assert summary.failed == 0
    assert summary.exit_code == 0


# =====================================================
# c) --apply with marketing_opt_in=false calls
#    set_contact_unsubscribed(email, True)
# =====================================================

def test_apply_opted_out_calls_resend_with_unsubscribed_true():
    preferences = [{"user_id": "u1", "marketing_opt_in": False}]
    users = [{"id": "u1", "email": "user@example.com"}]
    supabase = _make_supabase(preferences, users)

    with patch(
        "backend.scripts.reconcile_marketing_contacts.set_contact_unsubscribed"
    ) as mock_set:
        summary = reconcile(supabase, apply=True)

    mock_set.assert_called_once_with("user@example.com", True)
    assert summary.synced == 1
    assert summary.failed == 0


# =====================================================
# d) missing user/email is skipped without stopping later rows
# =====================================================

def test_missing_user_or_email_is_skipped_but_others_continue():
    preferences = [
        {"user_id": "missing-user", "marketing_opt_in": True},
        {"user_id": "no-email-user", "marketing_opt_in": True},
        {"user_id": "u2", "marketing_opt_in": False},
    ]
    users = [
        {"id": "no-email-user", "email": None},
        {"id": "u2", "email": "user2@example.com"},
    ]
    supabase = _make_supabase(preferences, users)

    with patch(
        "backend.scripts.reconcile_marketing_contacts.set_contact_unsubscribed"
    ) as mock_set:
        summary = reconcile(supabase, apply=True)

    mock_set.assert_called_once_with("user2@example.com", True)
    assert summary.skipped == 2
    assert summary.synced == 1
    assert summary.failed == 0


# =====================================================
# e) one Resend failure does not stop remaining users
# =====================================================

def test_one_resend_failure_does_not_stop_remaining_users():
    preferences = [
        {"user_id": "u1", "marketing_opt_in": True},
        {"user_id": "u2", "marketing_opt_in": False},
    ]
    users = [
        {"id": "u1", "email": "a@example.com"},
        {"id": "u2", "email": "b@example.com"},
    ]
    supabase = _make_supabase(preferences, users)

    with patch(
        "backend.scripts.reconcile_marketing_contacts.set_contact_unsubscribed"
    ) as mock_set:
        mock_set.side_effect = [RuntimeError("resend down"), None]
        summary = reconcile(supabase, apply=True)

    assert mock_set.call_count == 2
    assert summary.failed == 1
    assert summary.synced == 1


# =====================================================
# f) one or more Resend failures produce a non-zero exit result
# =====================================================

def test_any_failure_produces_nonzero_exit_code():
    preferences = [
        {"user_id": "u1", "marketing_opt_in": True},
        {"user_id": "u2", "marketing_opt_in": False},
    ]
    users = [
        {"id": "u1", "email": "a@example.com"},
        {"id": "u2", "email": "b@example.com"},
    ]
    supabase = _make_supabase(preferences, users)

    with patch(
        "backend.scripts.reconcile_marketing_contacts.set_contact_unsubscribed"
    ) as mock_set:
        mock_set.side_effect = [RuntimeError("resend down"), None]
        summary = reconcile(supabase, apply=True)

    assert summary.exit_code == 1

    with patch(
        "backend.scripts.reconcile_marketing_contacts.set_contact_unsubscribed"
    ) as mock_set_ok:
        mock_set_ok.side_effect = [None, None]
        ok_summary = reconcile(supabase, apply=True)

    assert ok_summary.exit_code == 0
