import pytest

import requests_mock


@pytest.yield_fixture
def requests():
    with requests_mock.Mocker() as m:
        yield m
