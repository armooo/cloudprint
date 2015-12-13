import datetime
import json

from cloudprint.cloudprint import (
    CLIENT_ID,
    PRINT_CLOUD_URL,
    CloudPrintAuth,
)


def test_login(tmpdir, requests):
    requests.post(
        PRINT_CLOUD_URL + 'register',
        json={
            'token_duration': 30,
            'complete_invite_url': 'http://doit',
            'polling_url': 'http://poll',
        },
    )

    requests.get(
        'http://poll' + CLIENT_ID,
        json={
            'success': True,
            'xmpp_jid': 'my_xmpp',
            'user_email': 'me@example.com',
            'authorization_code': 'auth-123abc',
        },
    )

    requests.post(
        'https://accounts.google.com/o/oauth2/token',
        [
            {
                'json': {
                    'refresh_token': 'refresh-123abc',
                }
            },
            {
                'json': {
                    'access_token': 'access_token-123abc',
                    'expires_in': 15,
                }
            },
        ]
    )

    auth_path = tmpdir.join('auth')
    auth = CloudPrintAuth(str(auth_path))
    auth.AUTH_POLL_PERIOD = 0
    auth.login('name', 'description', 'ppd')

    with auth_path.open() as auth_file:
        auth_data = json.load(auth_file)
        assert auth_data['email'] == 'me@example.com'
        assert auth_data['xmpp_jid'] == 'my_xmpp'
        assert auth_data['refresh_token'] == 'refresh-123abc'

    assert auth.access_token == 'access_token-123abc'


def test_no_auth(tmpdir):
    auth_path = tmpdir.join('auth')
    auth = CloudPrintAuth(str(auth_path))

    assert auth.no_auth()

    auth_path.ensure()

    assert not auth.no_auth()


def test_refresh(tmpdir, requests):
    requests.post(
        'https://accounts.google.com/o/oauth2/token',
        json={
            'access_token': 'access_token-123abc',
            'expires_in': 15,
        }
    )

    auth_path = tmpdir.join('auth')
    auth = CloudPrintAuth(str(auth_path))
    auth._access_token = 'dead'
    auth.refresh_token = 'refresh-123abc'
    auth.exp_time = datetime.datetime.fromtimestamp(0)

    assert auth.access_token == 'access_token-123abc'


def test_load(tmpdir, requests):
    requests.post(
        'https://accounts.google.com/o/oauth2/token',
        json={
            'access_token': 'access_token-123abc',
            'expires_in': 15,
        }
    )

    auth_path = tmpdir.join('auth')
    with auth_path.open('w') as auth_file:
        json.dump(
            {
                'guid': 'guid123',
                'email': 'example@example.com',
                'xmpp_jid': 'my_xmpp',
                'refresh_token': 'refresh_123',
            },
            auth_file,
        )

    auth = CloudPrintAuth(str(auth_path))
    auth.load()

    assert auth.guid == 'guid123'
    assert auth.email == 'example@example.com'
    assert auth.xmpp_jid == 'my_xmpp'
    assert auth.refresh_token == 'refresh_123'
