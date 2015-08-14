import mock
import pytest

from cloudprint import cloudprint


@pytest.fixture
def cpp(monkeypatch):
    printers = {}

    def add_printer(name):
        printer = mock.Mock(name='cpp printer ' + name)
        printer.name = name
        printers[name] = printer
        return printer

    cpp = mock.Mock(name='cpp')
    cpp.get_printers.side_effect = lambda: list(printers.values())
    cpp.include = []
    cpp.exclude = []

    def get_printer_info(cpp, name):
        try:
            printer = printers[name]
            return printer.ppd, printer.description
        except KeyError:
            return None, None

    monkeypatch.setattr(cloudprint, 'get_printer_info', get_printer_info)

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


def test_get_printer_info(tmpdir):
    ppd_path = tmpdir.join('ppd')
    ppd_path.write('this is a ppd')

    cups = mock.Mock(name='cups')
    cups.getPPD.return_value = str(ppd_path)
    cups.getPrinterAttributes.return_value = {
        'printer-info': mock.sentinel.desc
    }

    ppd, description = cloudprint.get_printer_info(cups, 'foo')

    assert ppd == 'this is a ppd'
    assert description == mock.sentinel.desc

    cups.getPPD.assert_called_with('foo')
    cups.getPrinterAttributes.assert_called_with('foo')


def test_sync_add_printer(cups, cpp):
    cups.test_add_printer('new')

    cloudprint.sync_printers(cups, cpp)

    cpp.add_printer.assert_called_with('new', mock.ANY, mock.ANY)


def test_sync_rm_printer(cups, cpp):
    old_printer = cpp.test_add_printer('old')

    cloudprint.sync_printers(cups, cpp)

    old_printer.delete.assert_called_with()


def test_sync_update_printer(cups, cpp):
    cups.test_add_printer('old')
    old_printer = cpp.test_add_printer('old')

    cloudprint.sync_printers(cups, cpp)

    old_printer.update.assert_called_with(
        old_printer.description,
        old_printer.ppd,
    )
