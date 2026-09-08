import os
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")

from backend.routers import supabase_auth as auth


class Query:
    def __init__(self, store, table):
        self.store, self.table, self.filters, self.mode, self.payload, self.want_single = store, table, [], "select", None, False
    def select(self, *_): return self
    def eq(self, key, value): self.filters.append((key, value)); return self
    def is_(self, key, value): self.filters.append((key, None if value == "null" else value)); return self
    def limit(self, *_): return self
    def single(self): self.want_single = True; return self
    def insert(self, payload): self.mode, self.payload = "insert", payload; return self
    def update(self, payload): self.mode, self.payload = "update", payload; return self
    def _rows(self): return [row for row in self.store[self.table] if all(row.get(k) == v for k, v in self.filters)]
    def execute(self):
        if self.mode == "select":
            rows = self._rows()
            return SimpleNamespace(data=rows[0] if self.want_single and rows else (None if self.want_single else rows))
        if self.mode == "insert":
            row = dict(self.payload); row.setdefault("id", f"user-{len(self.store[self.table]) + 1}"); self.store[self.table].append(row); return SimpleNamespace(data=[row])
        rows = self._rows()
        for row in rows: row.update(self.payload)
        return SimpleNamespace(data=rows)


class FakeSupabase:
    def __init__(self, rows, auth_id="auth-1", email="member@example.com"):
        self.rows = {"topspot_users": rows, "marketing_email_preferences": []}
        user = SimpleNamespace(id=auth_id, email=email, email_confirmed_at="confirmed")
        self.auth = SimpleNamespace(get_user=lambda _: SimpleNamespace(user=user))
    def table(self, name): return Query(self.rows, name)
    def rpc(self, name, payload):
        assert name == "complete_topspot_user_display_name"
        row = next((row for row in self.rows["topspot_users"] if row["id"] == payload["p_user_id"]), None)
        if row is None or (row.get("display_name") or "").strip():
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=[]))
        row["display_name"] = payload["p_display_name"]
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=[{"id": row["id"], "display_name": row["display_name"]}]))


@pytest.fixture(autouse=True)
def safe_auth(monkeypatch):
    monkeypatch.setattr(auth, "create_jwt_token", lambda user_id: f"jwt-{user_id}")
    monkeypatch.setattr(auth, "create_marketing_contact", lambda _: None)
    monkeypatch.setattr(auth, "set_contact_unsubscribed", lambda *_: None)


def signup(**overrides):
    data = {"access_token": "token", "display_name": "New Member", "preferred_language": "en", "marketing_opt_in": False}
    data.update(overrides)
    return auth.SupabaseSignupRequest(**data)


def test_new_signup_inserts_one_linked_row_and_keeps_marketing_behavior(monkeypatch):
    fake = FakeSupabase([]); monkeypatch.setattr(auth, "supabase", fake)
    response = auth.create_supabase_signup(signup(marketing_opt_in=True))
    assert response.status_code == 201
    assert fake.rows["topspot_users"] == [{"email": "member@example.com", "auth_user_id": "auth-1", "display_name": "New Member", "preferred_language": "en", "id": "user-1"}]
    assert fake.rows["marketing_email_preferences"][0]["marketing_opt_in"] is True


@pytest.mark.parametrize("name,language", [(" ", "en"), ("x", "en"), ("x" * 51, "en"), ("Valid", "ptbr")])
def test_signup_rejects_invalid_profile_values_before_writes(monkeypatch, name, language):
    fake = FakeSupabase([]); monkeypatch.setattr(auth, "supabase", fake)
    with pytest.raises(HTTPException) as exc: auth.create_supabase_signup(signup(display_name=name, preferred_language=language))
    assert exc.value.status_code == 422 and fake.rows["topspot_users"] == []


def test_verified_legacy_signup_links_only_null_auth_and_preserves_row(monkeypatch):
    legacy = {"id": "legacy-id", "email": "member@example.com", "auth_user_id": None, "spotify_user_id": "spotify", "stripe_customer_id": "cus_1", "complimentary_access": True, "display_name": None}
    fake = FakeSupabase([legacy]); monkeypatch.setattr(auth, "supabase", fake)
    response = auth.create_supabase_signup(signup())
    assert response.status_code == 200 and legacy == {**legacy, "auth_user_id": "auth-1"}
    assert len(fake.rows["topspot_users"]) == 1
    with pytest.raises(HTTPException) as repeated:
        auth.create_supabase_signup(signup())
    assert repeated.value.status_code == 409 and len(fake.rows["topspot_users"]) == 1


def test_signup_rejects_non_null_conflict_and_repeated_finalization(monkeypatch):
    row = {"id": "legacy-id", "email": "member@example.com", "auth_user_id": "other-auth", "display_name": "Existing"}
    fake = FakeSupabase([row]); monkeypatch.setattr(auth, "supabase", fake)
    with pytest.raises(HTTPException) as exc: auth.create_supabase_signup(signup())
    assert exc.value.status_code == 409 and row["auth_user_id"] == "other-auth"


def test_signin_requires_exact_auth_match_and_never_relinks(monkeypatch):
    row = {"id": "u1", "email": "member@example.com", "auth_user_id": "other-auth", "display_name": "Existing"}
    fake = FakeSupabase([row]); monkeypatch.setattr(auth, "supabase", fake)
    with pytest.raises(HTTPException) as exc: auth.create_supabase_session(auth.SupabaseSessionRequest(access_token="token"))
    assert exc.value.status_code == 403 and row["auth_user_id"] == "other-auth"


def test_profile_completion_requires_jwt_and_only_changes_display_name(monkeypatch):
    row = {"id": "u1", "email": "member@example.com", "auth_user_id": "auth-1", "display_name": None, "stripe_customer_id": "cus_1"}
    fake = FakeSupabase([row]); monkeypatch.setattr(auth, "supabase", fake)
    monkeypatch.setattr(auth, "decode_jwt_token", lambda _: None)
    with pytest.raises(HTTPException) as exc: auth.complete_profile(auth.ProfileCompletionRequest(display_name="Name"), "bad")
    assert exc.value.status_code == 401
    monkeypatch.setattr(auth, "decode_jwt_token", lambda _: {"user_id": "u1"})
    assert auth.complete_profile(auth.ProfileCompletionRequest(display_name="Name"), "jwt") == {"display_name": "Name"}
    assert row == {**row, "display_name": "Name"}
    with pytest.raises(HTTPException) as conflict:
        auth.complete_profile(auth.ProfileCompletionRequest(display_name="Later Name"), "jwt")
    assert conflict.value.status_code == 409
    assert row == {**row, "display_name": "Name"}
