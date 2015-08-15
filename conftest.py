import mock
import pytest
import requests as requests_lib

import requests_mock


@pytest.yield_fixture
def requests():
    with requests_mock.Mocker() as m:
        yield m


@pytest.fixture
def cpp(monkeypatch):
    printers = {}

    def add_printer(name):
        printer = mock.Mock(name='cpp printer ' + name)
        printer.name = name
        printers[name] = printer
        return printer

    cpp = mock.Mock(name='cpp')
    cpp.auth.session = requests_lib
    cpp.get_printers.side_effect = lambda: list(printers.values())
    cpp.include = []
    cpp.exclude = []

    def get_printer_info(cpp, name):
        try:
            printer = printers[name]
            return printer.ppd, printer.description
        except KeyError:
            return None, None

    monkeypatch.setattr(
        'cloudprint.cloudprint.get_printer_info',
        get_printer_info,
    )

    cpp.test_add_printer = add_printer
    return cpp


@pytest.fixture
def cups():
    printers = {}

    def add_printer(name):
        printers[name] = 1

    cups = mock.Mock(name='cups')
    cups.getPrinters.side_effect = printers.copy

    cups.test_add_printer = add_printer
    return cups
