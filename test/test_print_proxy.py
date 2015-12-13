try:
    import urlparse as parse
except ImportError:
    from urllib import parse

import mock
import pytest
import requests

from cloudprint.cloudprint import (
    CloudPrintProxy,
    PRINT_CLOUD_URL,
)


@pytest.fixture(params=('', 'prefix'))
def proxy(request):
    auth = mock.Mock(session=requests)
    proxy = CloudPrintProxy(auth)
    proxy.site = request.param
    return proxy


@pytest.fixture
def add_site(proxy):
    def add_site(name):
        if not proxy.site:
            return name
        else:
            return '{0}-{1}'.format(proxy.site, name)
    return add_site


@pytest.fixture
def remove_site(proxy):
    def remove_site(name):
        if not proxy.site:
            return name
        else:
            return name.replace(proxy.site + '-', '')
    return remove_site


def test_get_printers(proxy, requests, remove_site):
    requests.post(
        PRINT_CLOUD_URL + 'list',
        json={
            'printers': [
                {
                    'id': '1',
                    'name': 'printer 1',
                },
                {
                    'id': '2',
                    'name': 'printer 2',
                },
            ]
        },
    )

    printers = proxy.get_printers()

    assert printers[0].id == '1'
    assert remove_site(printers[0].name) == 'printer 1'
    assert printers[1].id == '2'
    assert remove_site(printers[1].name) == 'printer 2'


def test_delete_printer(proxy, requests):
    requests.post(
        PRINT_CLOUD_URL + 'delete',
        status_code=200,
    )

    proxy.delete_printer('1')

    data = parse.parse_qs(requests.request_history[0].text)
    assert data['printerid'][0] == '1'


def test_add_printer(proxy, requests, add_site):
    requests.post(
        PRINT_CLOUD_URL + 'register',
        status_code=200,
    )

    proxy.add_printer(
        name='printer_name',
        description='printer_description',
        ppd='printer_ppd',
    )

    data = parse.parse_qs(requests.request_history[0].text)
    assert data['printer'][0] == add_site('printer_name')
    assert data['description'][0] == 'printer_description'
    assert data['capabilities'][0] == 'printer_ppd'
    assert data['defaults'][0] == 'printer_ppd'


def test_update_printer(proxy, requests, add_site):
    requests.post(
        PRINT_CLOUD_URL + 'update',
        status_code=200,
    )

    proxy.update_printer(
        printer_id='1',
        name='printer_name',
        description='printer_description',
        ppd='printer_ppd',
    )

    data = parse.parse_qs(requests.request_history[0].text)
    assert data['printerid'][0] == '1'
    assert data['printer'][0] == add_site('printer_name')
    assert data['description'][0] == 'printer_description'
    assert data['capabilities'][0] == 'printer_ppd'
    assert data['defaults'][0] == 'printer_ppd'


def test_get_jobs(proxy, requests):
    requests.post(
        PRINT_CLOUD_URL + 'fetch',
        json={
            'jobs': [
                'job1',
                'job2',
            ]
        }
    )

    jobs = proxy.get_jobs(
        printer_id='1',
    )

    data = parse.parse_qs(requests.request_history[0].text)
    assert data['printerid'][0] == '1'
    assert jobs == ['job1', 'job2']


def test_finish_job(proxy, requests):
    requests.post(
        PRINT_CLOUD_URL + 'control',
        json={},
    )

    proxy.finish_job(
        job_id='1',
    )

    data = parse.parse_qs(requests.request_history[0].text)
    assert data['jobid'][0] == '1'
    assert data['status'][0] == 'DONE'


def test_fail_job(proxy, requests):
    requests.post(
        PRINT_CLOUD_URL + 'control',
        json={},
    )

    proxy.fail_job(
        job_id='1',
    )

    data = parse.parse_qs(requests.request_history[0].text)
    assert data['jobid'][0] == '1'
    assert data['status'][0] == 'ERROR'
