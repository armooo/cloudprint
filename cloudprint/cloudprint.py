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

import rest
import platform
import cups
import hashlib
import time
import urllib2
import tempfile
import shutil
import os
import json
import getpass
import stat
import sys
import argparse
import re
import logging
import logging.handlers

import xmpp

XMPP_SERVER_HOST = 'talk.google.com'
XMPP_USE_SSL = True
XMPP_SERVER_PORT = 5223

SOURCE = 'Armooo-PrintProxy-1'
PRINT_CLOUD_SERVICE_ID = 'cloudprint'
CLIENT_LOGIN_URL = '/accounts/ClientLogin'
PRINT_CLOUD_URL = '/cloudprint/'

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

LOGGER = logging.getLogger('cloudprint')
LOGGER.setLevel(logging.INFO)


class CloudPrintProxy(object):

    def __init__(self, verbose=True):
        self.verbose = verbose
        self.auth = None
        self.cups = cups.Connection()
        self.proxy = platform.node() + '-Armooo-PrintProxy'
        self.auth_path = os.path.expanduser('~/.cloudprintauth')
        self.xmpp_auth_path = os.path.expanduser('~/.cloudprintauth.sasl')
        self.username = None
        self.password = None
        self.sleeptime = 0
        self.storepw = False
        self.include = []
        self.exclude = []

    def get_auth(self):
        if self.auth:
            return self.auth
        if not self.auth:
            auth = self.get_saved_auth()
            if auth:
                return auth

            r = rest.REST('https://www.google.com', debug=False)
            try:
                auth_response = r.post(
                    CLIENT_LOGIN_URL,
                    {
                        'accountType': 'GOOGLE',
                        'Email': self.username,
                        'Passwd': self.password,
                        'service': PRINT_CLOUD_SERVICE_ID,
                        'source': SOURCE,
                   },
                    'application/x-www-form-urlencoded')
                xmpp_response = r.post(
                    CLIENT_LOGIN_URL,
                    {
                        'accountType': 'GOOGLE',
                        'Email': self.username,
                        'Passwd': self.password,
                        'service': 'mail',
                        'source': SOURCE,
                   },
                    'application/x-www-form-urlencoded'
                )
                jid = self.username if '@' in self.username else self.username + '@gmail.com'
                sasl_token = ('\0%s\0%s' % (jid, xmpp_response['Auth'])).encode('base64')
                file(self.xmpp_auth_path, 'w').write(sasl_token)
            except rest.REST.RESTException, e:
                if 'InvalidSecondFactor' in e.msg:
                    raise rest.REST.RESTException(
                        '2-Step',
                        '403',
                        'You have 2-Step authentication enabled on your '
                        'account. \n\nPlease visit '
                        'https://www.google.com/accounts/IssuedAuthSubTokens '
                        'to generate an application-specific password.'
                    )
                else:
                    raise

            self.set_auth(auth_response['Auth'])
            return self.auth

    def get_saved_auth(self):
        if os.path.exists(self.auth_path):
            auth_file = open(self.auth_path)
            self.auth = auth_file.readline().rstrip()
            self.username = auth_file.readline().rstrip()
            self.password = auth_file.readline().rstrip()
            auth_file.close()
            return self.auth

    def del_saved_auth(self):
        if os.path.exists(self.auth_path):
            os.unlink(self.auth_path)

    def set_auth(self, auth):
            self.auth = auth
            if not os.path.exists(self.auth_path):
                auth_file = open(self.auth_path, 'w')
                os.chmod(self.auth_path, stat.S_IRUSR | stat.S_IWUSR)
                auth_file.close()
            auth_file = open(self.auth_path, 'w')
            auth_file.write(self.auth)
            if self.storepw:
                auth_file.write("\n%s\n%s\n" % (self.username, self.password))
            auth_file.close()

    def get_rest(self):
        class check_new_auth(object):
            def __init__(self, rest):
                self.rest = rest

            def __getattr__(in_self, key):
                attr = getattr(in_self.rest, key)
                if not attr:
                    raise AttributeError()
                if not hasattr(attr, '__call__'):
                    return attr

                def f(*arg, **karg):
                    r = attr(*arg, **karg)
                    if 'update-client-auth' in r.headers:
                        LOGGER.info("Updating authentication token")
                        self.set_auth(r.headers['update-client-auth'])
                    return r
                return f

        auth = self.get_auth()
        return check_new_auth(rest.REST('https://www.google.com', auth=auth, debug=False))

    def get_printers(self):
        r = self.get_rest()
        printers = r.post(
            PRINT_CLOUD_URL + 'list',
            {
                'output': 'json',
                'proxy': self.proxy,
           },
            'application/x-www-form-urlencoded',
            {'X-CloudPrint-Proxy': 'ArmoooIsAnOEM'},
        )
        return [PrinterProxy(self, p['id'], p['name']) for p in printers['printers']]

    def delete_printer(self, printer_id):
        r = self.get_rest()
        r.post(
            PRINT_CLOUD_URL + 'delete',
            {
                'output': 'json',
                'printerid': printer_id,
           },
            'application/x-www-form-urlencoded',
            {'X-CloudPrint-Proxy': 'ArmoooIsAnOEM'},
        )
        if self.verbose:
            LOGGER.info('Deleted printer ' + printer_id)

    def add_printer(self, name, description, ppd):
        r = self.get_rest()
        r.post(
            PRINT_CLOUD_URL + 'register',
            {
                'output': 'json',
                'printer': name,
                'proxy':  self.proxy,
                'capabilities': ppd.encode('utf-8'),
                'defaults': ppd.encode('utf-8'),
                'status': 'OK',
                'description': description,
                'capsHash': hashlib.sha1(ppd.encode('utf-8')).hexdigest(),
           },
            'application/x-www-form-urlencoded',
            {'X-CloudPrint-Proxy': 'ArmoooIsAnOEM'},
        )
        if self.verbose:
            LOGGER.info('Added Printer ' + name)

    def update_printer(self, printer_id, name, description, ppd):
        r = self.get_rest()
        r.post(
            PRINT_CLOUD_URL + 'update',
            {
                'output': 'json',
                'printerid': printer_id,
                'printer': name,
                'proxy': self.proxy,
                'capabilities': ppd.encode('utf-8'),
                'defaults': ppd.encode('utf-8'),
                'status': 'OK',
                'description': description,
                'capsHash': hashlib.sha1(ppd.encode('utf-8')).hexdigest(),
           },
            'application/x-www-form-urlencoded',
            {'X-CloudPrint-Proxy': 'ArmoooIsAnOEM'},
        )
        if self.verbose:
            LOGGER.info('Updated Printer ' + name)

    def get_jobs(self, printer_id):
        r = self.get_rest()
        docs = r.post(
            PRINT_CLOUD_URL + 'fetch',
            {
                'output': 'json',
                'printerid': printer_id,
           },
            'application/x-www-form-urlencoded',
            {'X-CloudPrint-Proxy': 'ArmoooIsAnOEM'},
        )

        if not 'jobs' in docs:
            return []
        else:
            return docs['jobs']

    def finish_job(self, job_id):
        r = self.get_rest()
        r.post(
            PRINT_CLOUD_URL + 'control',
            {
                'output': 'json',
                'jobid': job_id,
                'status': 'DONE',
           },
            'application/x-www-form-urlencoded',
            {'X-CloudPrint-Proxy': 'ArmoooIsAnOEM'},
        )

    def fail_job(self, job_id):
        r = self.get_rest()
        r.post(
            PRINT_CLOUD_URL + 'control',
            {
                'output': 'json',
                'jobid': job_id,
                'status': 'ERROR',
           },
            'application/x-www-form-urlencoded',
            {'X-CloudPrint-Proxy': 'ArmoooIsAnOEM'},
        )


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


class App(object):
    def __init__(self, cups_connection=None, cpp=None, printers=None, pidfile_path=None):
        self.cups_connection = cups_connection
        self.cpp = cpp
        self.printers = printers
        self.pidfile_path = pidfile_path
        self.stdin_path = '/dev/null'
        self.stdout_path = '/dev/null'
        self.stderr_path = '/dev/null'
        self.pidfile_timeout = 5

    def run(self):
        process_jobs(self.cups_connection, self.cpp, self.printers)


#True if printer name matches *any* of the regular expressions in regexps
def match_re(prn, regexps, empty=False):
    if len(regexps):
        try:
            return re.match(regexps[0], prn, re.UNICODE) or match_re(prn, regexps[1:])
        except:
            sys.stderr.write('cloudprint: invalid regular expression: ' + regexps[0] + '\n')
            sys.exit(1)
    else:
        return empty


def sync_printers(cups_connection, cpp):
    local_printer_names = set(cups_connection.getPrinters().keys())
    remote_printers = dict([(p.name, p) for p in cpp.get_printers()])
    remote_printer_names = set(remote_printers)

    #Include/exclude local printers
    local_printer_names = set([prn for prn in local_printer_names if match_re(prn, cpp.include, True)])
    local_printer_names = set([prn for prn in local_printer_names if not match_re(prn, cpp.exclude)])

    #New printers
    for printer_name in local_printer_names - remote_printer_names:
        try:
            ppd_file = open(cups_connection.getPPD(printer_name))
            ppd = ppd_file.read()
            ppd_file.close()
            #This is bad it should use the LanguageEncoding in the PPD
            #But a lot of utf-8 PPDs seem to say they are ISOLatin1
            ppd = ppd.decode('utf-8')
            description = cups_connection.getPrinterAttributes(printer_name)['printer-info']
            cpp.add_printer(printer_name, description, ppd)
        except (cups.IPPError, UnicodeDecodeError):
            LOGGER.info('Skipping ' + printer_name)

    #Existing printers
    for printer_name in local_printer_names & remote_printer_names:
        ppd_file = open(cups_connection.getPPD(printer_name))
        ppd = ppd_file.read()
        ppd_file.close()
        #This is bad it should use the LanguageEncoding in the PPD
        #But a lot of utf-8 PPDs seem to say they are ISOLatin1
        try:
            ppd = ppd.decode('utf-8')
        except UnicodeDecodeError:
            pass
        description = cups_connection.getPrinterAttributes(printer_name)['printer-info']
        remote_printers[printer_name].update(description, ppd)

    #Printers that have left us
    for printer_name in remote_printer_names - local_printer_names:
        remote_printers[printer_name].delete()


def process_job(cups_connection, cpp, printer, job):
    request = urllib2.Request(job['fileUrl'], headers={
        'X-CloudPrint-Proxy': 'ArmoooIsAnOEM',
        'Authorization': 'GoogleLogin auth=%s' % cpp.get_auth()
   })

    try:
        pdf = urllib2.urlopen(request)
        tmp = tempfile.NamedTemporaryFile(delete=False)
        shutil.copyfileobj(pdf, tmp)
        tmp.flush()

        request = urllib2.Request(job['ticketUrl'], headers={
            'X-CloudPrint-Proxy': 'ArmoooIsAnOEM',
            'Authorization': 'GoogleLogin auth=%s' % cpp.get_auth()
       })
        options = json.loads(urllib2.urlopen(request).read())
        if 'request' in options:
            del options['request']

        options = dict((str(k), str(v)) for k, v in options.items())

        cpp.finish_job(job['id'])

        cups_connection.printFile(printer.name, tmp.name, job['title'], options)
        os.unlink(tmp.name)
        LOGGER.info('SUCCESS ' + job['title'].encode('unicode-escape'))

    except:
        cpp.fail_job(job['id'])
        LOGGER.error('ERROR ' + job['title'].encode('unicode-escape'))


def process_jobs(cups_connection, cpp, printers):
    xmpp_auth = file(cpp.xmpp_auth_path).read()
    xmpp_conn = xmpp.XmppConnection(keepalive_period=KEEPALIVE)

    while True:
        try:
            for printer in printers:
                for job in printer.get_jobs():
                    process_job(cups_connection, cpp, printer, job)

            if not xmpp_conn.is_connected():
                xmpp_conn.connect(XMPP_SERVER_HOST, XMPP_SERVER_PORT,
                                  XMPP_USE_SSL, xmpp_auth)

            xmpp_conn.await_notification(cpp.sleeptime)

        except:
            global FAIL_RETRY
            LOGGER.error('ERROR: Could not Connect to Cloud Service. Will Try again in %d Seconds' % FAIL_RETRY)
            time.sleep(FAIL_RETRY)

        if cpp.username and not xmpp_conn.is_connected():
            LOGGER.debug('Refreshing authentication')
            cpp.set_auth('')
            try:
                cpp.get_auth()
                xmpp_auth = file(cpp.xmpp_auth_path).read()
            except:
                LOGGER.debug('Error refreshing authentication')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', dest='daemon', action='store_true',
                        help='enable daemon mode (requires the daemon module)')
    parser.add_argument('-l', dest='logout', action='store_true',
                        help='logout of the google account')
    parser.add_argument('-p', metavar='pid_file', dest='pidfile', default='cloudprint.pid',
                        help='path to write the pid to (default %(default)s)')
    parser.add_argument('-a', metavar='account_file', dest='authfile', default=os.path.expanduser('~/.cloudprintauth'),
                        help='path to google account ident data (default %(default)s)')
    parser.add_argument('-c', dest='authonly', action='store_true',
                        help='establish and store login credentials, then exit')
    parser.add_argument('-f', dest='fastpoll', action='store_true',
                        help='use fast poll if notifications are not working')
    parser.add_argument('-u', dest='storepw', action='store_true',
                        help='store username/password in addition to login token')
    parser.add_argument('-i', metavar='regexp', dest='include', default=[], action='append',
                        help='include local printers matching %(metavar)s')
    parser.add_argument('-x', metavar='regexp', dest='exclude', default=[], action='append',
                        help='exclude local printers matching %(metavar)s')
    parser.add_argument('-v', dest='verbose', action='store_true',
                        help='verbose logging')
    args = parser.parse_args()

    # if daemon, log to syslog, otherwise log to stdout
    if args.daemon:
        handler = logging.handlers.SysLogHandler()
        handler.setFormatter(logging.Formatter(fmt='cloudprint.py: %(message)s'))
    else:
        handler = logging.StreamHandler(sys.stdout)
    LOGGER.addHandler(handler)

    if args.verbose:
        LOGGER.info('Setting DEBUG-level logging')
        LOGGER.setLevel(logging.DEBUG)

    cups_connection = cups.Connection()
    cpp = CloudPrintProxy()
    if args.authfile:
        cpp.auth_path = args.authfile
        cpp.xmpp_auth_path = args.authfile+'.sasl'

    cpp.sleeptime = POLL_PERIOD
    if args.fastpoll:
        cpp.sleeptime = FAST_POLL_PERIOD

    if args.storepw:
        cpp.storepw = True

    if args.logout:
        cpp.del_saved_auth()
        LOGGER.info('logged out')
        return

    # Check if password authentification is needed
    if not cpp.get_saved_auth():
        if args.authfile is None or not os.path.exists(args.authfile):
            cpp.username = raw_input('Google username: ')
            cpp.password = getpass.getpass()

    cpp.include = args.include
    cpp.exclude = args.exclude

    #try to login
    while True:
        try:
            sync_printers(cups_connection, cpp)
            break
        except rest.REST.RESTException, e:
            #not a auth error
            if e.code != 403:
                raise
            #don't have a stored auth key
            if not cpp.get_saved_auth():
                raise
            #reset the stored auth
            cpp.set_auth('')

    if args.authonly:
        sys.exit(0)

    printers = cpp.get_printers()

    if args.daemon:
        try:
            from daemon import runner
        except ImportError:
            print 'daemon module required for -d'
            print '\tyum install python-daemon, or apt-get install python-daemon, or pip install python-daemon'
            sys.exit(1)

        app = App(cups_connection=cups_connection,
                  cpp=cpp, printers=printers,
                  pidfile_path=os.path.abspath(args.pidfile))
        sys.argv = [sys.argv[0], 'start']
        daemon_runner = runner.DaemonRunner(app)
        daemon_runner.do_action()
    else:
        process_jobs(cups_connection, cpp, printers)

if __name__ == '__main__':
    main()
