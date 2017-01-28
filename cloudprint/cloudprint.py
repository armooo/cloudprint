#!/usr/bin/env python
# Copyright 2014 Jason Michalski <armooo@armooo.net>
#
# This file is part of cloudprint.
#
# cloudprint is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# cloudprint is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with cloudprint.  If not, see <http://www.gnu.org/licenses/>.

from __future__ import absolute_import
from __future__ import print_function

import configargparse
import cups
import datetime
import hashlib
import io
import json
import logging
import logging.handlers
import os
import re
import requests
import shutil
import stat
import sys
import tempfile
import time
import uuid

from cloudprint import xmpp


XMPP_SERVER_HOST = 'talk.google.com'
XMPP_SERVER_PORT = 5223

SOURCE = 'Armooo-PrintProxy-1'
PRINT_CLOUD_SERVICE_ID = 'cloudprint'
CLIENT_LOGIN_URL = '/accounts/ClientLogin'
PRINT_CLOUD_URL = 'https://www.google.com/cloudprint/'

# period in seconds with which we should poll for new jobs via the HTTP api,
# when xmpp is connecting properly.
# 'None' to poll only on startup and when we get XMPP notifications.
# 'Fast Poll' is used as a workaround when notifications are not working.
POLL_PERIOD = 3600.0
FAST_POLL_PERIOD = 30.0

# wait period to retry when xmpp fails
FAIL_RETRY = 60

# how often, in seconds, to send a keepalive character over xmpp
KEEPALIVE = 600.0

# failed job retries
RETRIES = 1
num_retries = 0

LOGGER = logging.getLogger('cloudprint')
LOGGER.setLevel(logging.INFO)

CLIENT_ID = ('607830223128-rqenc3ekjln2qi4m4ntudskhnsqn82gn'
             '.apps.googleusercontent.com')
CLIENT_KEY = 'T0azsx2lqDztSRyPHQaERJJH'


def unicode_escape(string):
    return string.encode('unicode-escape').decode('ascii')


class CloudPrintAuth(object):
    AUTH_POLL_PERIOD = 10.0

    def __init__(self, auth_path):
        self.auth_path = auth_path
        self.guid = None
        self.email = None
        self.xmpp_jid = None
        self.exp_time = None
        self.refresh_token = None
        self._access_token = None

    @property
    def session(self):
        s = requests.session()
        s.headers['X-CloudPrint-Proxy'] = 'ArmoooIsAnOEM'
        s.headers['Authorization'] = 'Bearer {0}'.format(self.access_token)
        return s

    @property
    def access_token(self):
        if datetime.datetime.now() > self.exp_time:
            self.refresh()
        return self._access_token

    def no_auth(self):
        return not os.path.exists(self.auth_path)

    def login(self, name, description, ppd):
        self.guid = str(uuid.uuid4())
        reg_data = requests.post(
            PRINT_CLOUD_URL + 'register',
            {
                'output': 'json',
                'printer': name,
                'proxy':  self.guid,
                'capabilities': ppd.encode('utf-8'),
                'defaults': ppd.encode('utf-8'),
                'status': 'OK',
                'description': description,
                'capsHash': hashlib.sha1(ppd.encode('utf-8')).hexdigest(),
            },
            headers={'X-CloudPrint-Proxy': 'ArmoooIsAnOEM'},
        ).json()
        print('Go to {0} to claim this printer'.format(
            reg_data['complete_invite_url']
        ))

        end = time.time() + int(reg_data['token_duration'])
        while time.time() < end:
            time.sleep(self.AUTH_POLL_PERIOD)
            print('trying for the win')
            poll = requests.get(
                reg_data['polling_url'] + CLIENT_ID,
                headers={'X-CloudPrint-Proxy': 'ArmoooIsAnOEM'},
            ).json()
            if poll['success']:
                break
        else:
            print('The login request timedout')

        self.xmpp_jid = poll['xmpp_jid']
        self.email = poll['user_email']
        print('Printer claimed by {0}.'.format(self.email))

        token = requests.post(
            'https://accounts.google.com/o/oauth2/token',
            data={
                'redirect_uri': 'oob',
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_KEY,
                'grant_type': 'authorization_code',
                'code': poll['authorization_code'],
            }
        ).json()

        self.refresh_token = token['refresh_token']
        self.refresh()

        self.save()

    def refresh(self):
        token = requests.post(
            'https://accounts.google.com/o/oauth2/token',
            data={
                'client_id': CLIENT_ID,
                'client_secret': CLIENT_KEY,
                'grant_type': 'refresh_token',
                'refresh_token': self.refresh_token,
            }
        ).json()
        self._access_token = token['access_token']

        slop_time = datetime.timedelta(minutes=15)
        expires_in = datetime.timedelta(seconds=token['expires_in'])
        self.exp_time = datetime.datetime.now() + (expires_in - slop_time)

    def load(self):
        if os.path.exists(self.auth_path):
            with open(self.auth_path) as auth_file:
                auth_data = json.load(auth_file)
            self.guid = auth_data['guid']
            self.xmpp_jid = auth_data['xmpp_jid']
            self.email = auth_data['email']
            self.refresh_token = auth_data['refresh_token']

        self.refresh()

    def delete(self):
        if os.path.exists(self.auth_path):
            os.unlink(self.auth_path)

    def save(self):
            if not os.path.exists(self.auth_path):
                with open(self.auth_path, 'w') as auth_file:
                    os.chmod(self.auth_path, stat.S_IRUSR | stat.S_IWUSR)
            with open(self.auth_path, 'w') as auth_file:
                json.dump({
                    'guid':  self.guid,
                    'email': self.email,
                    'xmpp_jid': self.xmpp_jid,
                    'refresh_token': self.refresh_token,
                    },
                    auth_file
                )


class CloudPrintProxy(object):

    def __init__(self, auth):
        self.auth = auth
        self.sleeptime = 0
        self.site = ''
        self.include = []
        self.exclude = []

    def get_printers(self):
        printers = self.auth.session.post(
            PRINT_CLOUD_URL + 'list',
            {
                'output': 'json',
                'proxy': self.auth.guid,
            },
        ).json()
        return [
            PrinterProxy(
                self,
                p['id'],
                re.sub('^' + self.site + '-', '', p['name'])
            )
            for p in printers['printers']
        ]

    def delete_printer(self, printer_id):
        self.auth.session.post(
            PRINT_CLOUD_URL + 'delete',
            {
                'output': 'json',
                'printerid': printer_id,
            },
        ).raise_for_status()
        LOGGER.debug('Deleted printer ' + printer_id)

    def add_printer(self, name, description, ppd):
        if self.site:
            name = self.site + '-' + name
        self.auth.session.post(
            PRINT_CLOUD_URL + 'register',
            {
                'output': 'json',
                'printer': name,
                'proxy':  self.auth.guid,
                'capabilities': ppd.encode('utf-8'),
                'defaults': ppd.encode('utf-8'),
                'status': 'OK',
                'description': description,
                'capsHash': hashlib.sha1(ppd.encode('utf-8')).hexdigest(),
            },
        ).raise_for_status()
        LOGGER.debug('Added Printer ' + name)

    def update_printer(self, printer_id, name, description, ppd):
        if self.site:
            name = self.site + '-' + name
        self.auth.session.post(
            PRINT_CLOUD_URL + 'update',
            {
                'output': 'json',
                'printerid': printer_id,
                'printer': name,
                'proxy': self.auth.guid,
                'capabilities': ppd.encode('utf-8'),
                'defaults': ppd.encode('utf-8'),
                'status': 'OK',
                'description': description,
                'capsHash': hashlib.sha1(ppd.encode('utf-8')).hexdigest(),
            },
        ).raise_for_status()
        LOGGER.debug('Updated Printer ' + name)

    def get_jobs(self, printer_id):
        docs = self.auth.session.post(
            PRINT_CLOUD_URL + 'fetch',
            {
                'output': 'json',
                'printerid': printer_id,
            },
        ).json()

        if 'jobs' not in docs:
            return []
        else:
            return docs['jobs']

    def finish_job(self, job_id):
        self.auth.session.post(
            PRINT_CLOUD_URL + 'control',
            {
                'output': 'json',
                'jobid': job_id,
                'status': 'DONE',
            },
        ).json()
        LOGGER.debug('Finished Job' + job_id)

    def fail_job(self, job_id):
        self.auth.session.post(
            PRINT_CLOUD_URL + 'control',
            {
                'output': 'json',
                'jobid': job_id,
                'status': 'ERROR',
            },
        ).json()
        LOGGER.debug('Failed Job' + job_id)


class PrinterProxy(object):
    def __init__(self, cpp, printer_id, name):
        self.cpp = cpp
        self.id = printer_id
        self.name = name

    def get_jobs(self):
        LOGGER.info('Polling for jobs on ' + self.name)
        return self.cpp.get_jobs(self.id)

    def update(self, description, ppd):
        return self.cpp.update_printer(self.id, self.name, description, ppd)

    def delete(self):
        return self.cpp.delete_printer(self.id)


# True if printer name matches *any* of the regular expressions in regexps
def match_re(prn, regexps, empty=False):
    if len(regexps):
        try:
            return (
                re.match(regexps[0], prn, re.UNICODE)
                or match_re(prn, regexps[1:])
            )
        except Exception:
            sys.stderr.write(
                'cloudprint: invalid regular expression: ' +
                regexps[0] +
                '\n'
            )
            sys.exit(1)
    else:
        return empty


def get_printer_info(cups_connection, printer_name):
        # This is bad it should use the LanguageEncoding in the PPD
        # But a lot of utf-8 PPDs seem to say they are ISOLatin1
        ppd_path = cups_connection.getPPD(printer_name)
        with io.open(ppd_path, encoding='utf-8') as ppd_file:
            ppd = ppd_file.read()

        printer_attrs = cups_connection.getPrinterAttributes(printer_name)
        description = printer_attrs['printer-info']
        return ppd, description


def sync_printers(cups_connection, cpp):
    local_printer_names = set(cups_connection.getPrinters().keys())
    remote_printers = dict([(p.name, p) for p in cpp.get_printers()])
    remote_printer_names = set(remote_printers)

    # Include/exclude local printers
    local_printer_names = set([
        prn for prn in local_printer_names
        if match_re(prn, cpp.include, True)
    ])
    local_printer_names = set([
        prn for prn in local_printer_names
        if not match_re(prn, cpp.exclude)
    ])

    # New printers
    for printer_name in local_printer_names - remote_printer_names:
        try:
            ppd, description = get_printer_info(cups_connection, printer_name)
            cpp.add_printer(printer_name, description, ppd)
        except (cups.IPPError, UnicodeDecodeError):
            LOGGER.exception('Skipping ' + printer_name)

    # Existing printers
    for printer_name in local_printer_names & remote_printer_names:
        ppd, description = get_printer_info(cups_connection, printer_name)
        remote_printers[printer_name].update(description, ppd)

    # Printers that have left us
    for printer_name in remote_printer_names - local_printer_names:
        remote_printers[printer_name].delete()


def process_job(cups_connection, cpp, printer, job):
    global num_retries

    try:
        pdf = cpp.auth.session.get(job['fileUrl'], stream=True)
        tmp = tempfile.NamedTemporaryFile(delete=False)
        shutil.copyfileobj(pdf.raw, tmp)
        tmp.flush()

        options = cpp.auth.session.get(job['ticketUrl']).json()
        if 'request' in options:
            del options['request']

        options = dict((str(k), str(v)) for k, v in list(options.items()))
        options['job-originating-user-name'] = job['ownerId']

        # Cap the title length to 255, or cups will complain about invalid
        # job-name
        cups_connection.printFile(
            printer.name,
            tmp.name,
            job['title'][:255],
            options,
        )
        os.unlink(tmp.name)
        LOGGER.info(unicode_escape('SUCCESS ' + job['title']))

        cpp.finish_job(job['id'])
        num_retries = 0

    except Exception:
        if num_retries >= RETRIES:
            num_retries = 0
            cpp.fail_job(job['id'])
            LOGGER.error(unicode_escape('ERROR ' + job['title']))
        else:
            num_retries += 1
            LOGGER.info(
                unicode_escape('Job %s failed - Will retry' % job['title'])
            )


def process_jobs(cups_connection, cpp):
    xmpp_conn = xmpp.XmppConnection(keepalive_period=KEEPALIVE)

    while True:
        process_jobs_once(cups_connection, cpp, xmpp_conn)


def process_jobs_once(cups_connection, cpp, xmpp_conn):
    printers = cpp.get_printers()
    try:
        for printer in printers:
            for job in printer.get_jobs():
                process_job(cups_connection, cpp, printer, job)

        if not xmpp_conn.is_connected():
            xmpp_conn.connect(XMPP_SERVER_HOST, XMPP_SERVER_PORT, cpp.auth)

        xmpp_conn.await_notification(cpp.sleeptime)

    except Exception:
        LOGGER.exception(
            'ERROR: Could not Connect to Cloud Service. '
            'Will Try again in %d Seconds' %
            FAIL_RETRY
        )
        time.sleep(FAIL_RETRY)


def parse_args():
    parser = configargparse.ArgParser(
        default_config_files=['/etc/cloudprint.conf',
                              '~/.cloudprint.conf'],
    )
    parser.add_argument(
        '-d', '--daemon',
        dest='daemon',
        action='store_true',
        help='enable daemon mode (requires the daemon module)',
    )
    parser.add_argument(
        '-l', '--logout',
        dest='logout',
        action='store_true',
        help='logout of the google account',
    )
    parser.add_argument(
        '-p', '--pidfile',
        metavar='pid_file',
        dest='pidfile',
        default='cloudprint.pid',
        help='path to write the pid to (default %(default)s)',
    )
    parser.add_argument(
        '-a', '--account_file',
        metavar='account_file',
        dest='authfile',
        default=os.path.expanduser('~/.cloudprintauth.json'),
        help='path to google account ident data (default %(default)s)',
    )
    parser.add_argument(
        '-c', '--credentials',
        dest='authonly',
        action='store_true',
        help='establish and store login credentials, then exit',
    )
    parser.add_argument(
        '-f', '--fastpoll',
        dest='fastpoll',
        action='store_true',
        help='use fast poll if notifications are not working',
    )
    parser.add_argument(
        '-i', '--include',
        metavar='regexp',
        dest='include',
        default=[],
        action='append',
        help='include local printers matching %(metavar)s',
    )
    parser.add_argument(
        '-x', '--exclude',
        metavar='regexp',
        dest='exclude',
        default=[],
        action='append',
        help='exclude local printers matching %(metavar)s',
    )
    parser.add_argument(
        '-v', '--verbose',
        dest='verbose',
        action='store_true',
        help='verbose logging',
    )
    parser.add_argument(
        '--syslog-address',
        help='syslog address to use in daemon mode',
    )
    parser.add_argument(
        '-s', '--sitename',
        metavar='sitename',
        dest='site',
        default='',
        help='one-word site-name that will prefix printers',
    )

    return parser.parse_args()


def main():
    args = parse_args()

    if args.syslog_address and not args.daemon:
        print('syslog_address is only valid in daemon mode')
        sys.exit(1)

    # if daemon, log to syslog, otherwise log to stdout
    if args.daemon:
        if args.syslog_address:
            handler = logging.handlers.SysLogHandler(
                address=args.syslog_address
            )
        else:
            handler = logging.handlers.SysLogHandler()
        handler.setFormatter(
            logging.Formatter(fmt='cloudprint.py: %(message)s')
        )
    else:
        handler = logging.StreamHandler(sys.stdout)
    LOGGER.addHandler(handler)

    if args.verbose:
        LOGGER.info('Setting DEBUG-level logging')
        LOGGER.setLevel(logging.DEBUG)

        try:
            import http.client as httpclient
        except ImportError:
            import httplib as httpclient
        httpclient.HTTPConnection.debuglevel = 1

        requests_log = logging.getLogger("requests.packages.urllib3")
        requests_log.setLevel(logging.DEBUG)
        requests_log.propagate = True

    auth = CloudPrintAuth(args.authfile)
    if args.logout:
        auth.delete()
        LOGGER.info('logged out')
        return

    cups_connection = cups.Connection()
    cpp = CloudPrintProxy(auth)

    cpp.sleeptime = POLL_PERIOD
    if args.fastpoll:
        cpp.sleeptime = FAST_POLL_PERIOD

    cpp.include = args.include
    cpp.exclude = args.exclude
    cpp.site = args.site

    printers = list(cups_connection.getPrinters().keys())
    if not printers:
        LOGGER.error('No printers found')
        return

    if auth.no_auth():
        authed = False
        for name in printers:
            try:
                ppd, description = get_printer_info(cups_connection, name)
                auth.login(name, description, ppd)
                authed = True
                break
            except (cups.IPPError):
                LOGGER.error('Unable to login with: ' + name)
        if not authed:
            LOGGER.error('Unable to find any valid printer.')
            sys.exit(-1)
    else:
        auth.load()

    sync_printers(cups_connection, cpp)

    if args.authonly:
        sys.exit(0)

    if args.daemon:
        try:
            import daemon
            import daemon.pidfile
        except ImportError:
            print('daemon module required for -d')
            print(
                '\tyum install python-daemon, or apt-get install '
                'python-daemon, or pip install python-daemon'
            )
            sys.exit(1)

        pidfile = daemon.pidfile.TimeoutPIDLockFile(
            path=os.path.abspath(args.pidfile),
            timeout=5,
        )
        with daemon.DaemonContext(pidfile=pidfile):
            process_jobs(cups_connection, cpp)

    else:
        process_jobs(cups_connection, cpp)


if __name__ == '__main__':
    main()
