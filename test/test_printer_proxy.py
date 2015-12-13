import mock
import pytest

from cloudprint.cloudprint import PrinterProxy


@pytest.fixture
def cpp():
    return mock.Mock(name='cpp')


@pytest.fixture
def printer_proxy(cpp):
    return PrinterProxy(
        cpp=cpp,
        printer_id='1',
        name='printer 1',
    )


def test_get_jobs(cpp, printer_proxy):
    printer_proxy.get_jobs()

    cpp.get_jobs.assert_called_with(printer_proxy.id)


def test_update(cpp, printer_proxy):
    printer_proxy.update(
        description='printer_description',
        ppd='printer_ppd',
    )

    cpp.update_printer.assert_called_with(
        printer_proxy.id,
        printer_proxy.name,
        'printer_description',
        'printer_ppd',
    )


def test_delete(cpp, printer_proxy):
    printer_proxy.delete()

    cpp.delete_printer.assert_called_with(
        printer_proxy.id,
    )
