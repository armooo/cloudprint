import mock
import pytest

from cloudprint import cloudprint


@pytest.fixture
def xmpp_conn(monkeypatch):
    XmppConnection = mock.Mock(name='XmppConnection')
    monkeypatch.setattr('cloudprint.xmpp.XmppConnection', XmppConnection)
    return XmppConnection.return_value


def test_print(requests, cups, cpp, xmpp_conn):
    cloudprint.num_retries = 0

    printer = cpp.test_add_printer('printer')
    printer.get_jobs.return_value = [{
        'fileUrl': 'http://print_job.pdf',
        'ticketUrl': 'http://ticket',
        'title': '*' * 300,
        'id': 'job_1',
        'ownerId': 'owner@example.com'
    }]

    xmpp_conn.is_connected.return_value = True

    requests.get('http://print_job.pdf', text='This is a PDF')
    requests.get(
        'http://ticket',
        json={
            'request': '',
            'a': 1,
            'b': 2,
        },
    )

    cloudprint.process_jobs_once(cups, cpp, xmpp_conn)

    cups.printFile.assert_called_with(
        'printer',
        mock.ANY,
        '*' * 255,
        {
            'a': '1',
            'b': '2',
            'job-originating-user-name': 'owner@example.com',
        },
    )
    cpp.finish_job.assert_called_with('job_1')
    assert xmpp_conn.await_notification.called
    assert cloudprint.num_retries == 0


def test_retry(requests, cups, cpp, xmpp_conn):
    cloudprint.num_retries = 0

    printer = cpp.test_add_printer('printer')
    printer.get_jobs.return_value = [{
        'fileUrl': 'http://print_job.pdf',
        'ticketUrl': 'http://ticket',
        'title': '*' * 300,
        'id': 'job_1',
        'ownerId': 'owner@example.com'
    }]

    requests.get(url='http://print_job.pdf', status_code=500)

    cloudprint.process_jobs_once(cups, cpp, xmpp_conn)

    assert cloudprint.num_retries == 1


def test_failed(requests, cups, cpp, xmpp_conn):
    cloudprint.num_retries = 0

    printer = cpp.test_add_printer('printer')
    printer.get_jobs.return_value = [{
        'fileUrl': 'http://print_job.pdf',
        'ticketUrl': 'http://ticket',
        'title': '*' * 300,
        'id': 'job_1',
        'ownerId': 'owner@example.com'
    }]

    requests.get(url='http://print_job.pdf', status_code=500)

    for _ in range(cloudprint.RETRIES + 1):
        cloudprint.process_jobs_once(cups, cpp, xmpp_conn)

    cpp.fail_job.assert_called_with('job_1')
    assert cloudprint.num_retries == 0
