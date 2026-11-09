from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.isaiah.access_codes import create_access_code_router
from backend.isaiah import access_codes

USER_ID = '11111111-1111-4111-8111-111111111111'

@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(access_codes, 'decode_jwt_token', lambda token: {'user_id': USER_ID})
    db = Mock()
    db.rpc.return_value.execute.return_value = SimpleNamespace(data={
        'result': 'activated', 'complimentary_access': True,
        'access_expires_at': None, 'redeemed_at': '2026-11-09T12:00:00Z'})
    app = FastAPI()
    app.include_router(create_access_code_router(lambda: db), prefix='/api')
    return TestClient(app), db

def post(client, code=' SQUIRES67 '):
    return client.post('/api/access-codes/redeem', json={'code': code},
        headers={'X-TopSpot-Access-Code': '1'}, cookies={'access_token': 'session'})

def test_authenticated_user_and_normalization(setup):
    client, db = setup
    response = post(client)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    db.rpc.assert_called_once_with('redeem_access_code', {'p_user_id': USER_ID, 'p_code': 'squires67'})

def test_cannot_choose_another_account(setup):
    client, db = setup
    response = client.post('/api/access-codes/redeem', json={'code': 'hello', 'user_id': USER_ID},
        headers={'X-TopSpot-Access-Code': '1'}, cookies={'access_token': 'session'})
    assert response.status_code == 422
    db.rpc.assert_not_called()

@pytest.mark.parametrize('payload', [None, {}, {'guest_id': USER_ID}, {'user_id': 'bad'}])
def test_invalid_session(setup, monkeypatch, payload):
    client, db = setup
    monkeypatch.setattr(access_codes, 'decode_jwt_token', lambda token: payload)
    assert post(client).status_code == 401
    db.rpc.assert_not_called()

def test_missing_cookie_or_custom_header(setup):
    client, db = setup
    assert client.post('/api/access-codes/redeem', json={'code': 'hello'},
        headers={'X-TopSpot-Access-Code': '1'}).status_code == 401
    assert client.post('/api/access-codes/redeem', json={'code': 'hello'},
        cookies={'access_token': 'session'}).status_code == 403
    db.rpc.assert_not_called()

@pytest.mark.parametrize('code', ['a', 'hello world', 'a' * 129, '💰💰💰'])
def test_invalid_format(setup, code):
    client, db = setup
    assert post(client, code).status_code in (400, 422)
    db.rpc.assert_not_called()

@pytest.mark.parametrize('outcome,status', [
    ('invalid_code', 400), ('unavailable_code', 400), ('rate_limited', 429),
    ('sign_in_required', 401), ('paid_subscription', 409),
    ('already_redeemed', 200), ('unchanged', 200)])
def test_outcomes(setup, outcome, status):
    client, db = setup
    db.rpc.return_value.execute.return_value.data = {'result': outcome}
    response = post(client)
    assert response.status_code == status
    if status == 429: assert response.headers['retry-after'] == '900'

def test_database_failure_is_private(setup):
    client, db = setup
    db.rpc.return_value.execute.side_effect = RuntimeError('secret credentials')
    response = post(client)
    assert response.status_code == 503
    assert 'secret' not in response.text
    assert response.json()['detail']['code'] == 'temporarily_unavailable'

def test_malformed_rpc_response(setup):
    client, db = setup
    db.rpc.return_value.execute.return_value.data = []
    assert post(client).status_code == 503
