#!/usr/bin/env python
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
import getopt

SOURCE = 'Armooo-PrintProxy-1'
PRINT_CLOUD_SERICE_ID = 'cloudprint'
CLIENT_LOGIN_URL = '/accounts/ClientLogin'
PRINT_CLOUD_URL = '/cloudprint/'

class CloudPrintProxy(object):

    def __init__(self, verbose=True):
        self.verbose = verbose
        self.auth = None
        self.printer_id = None
        self.cups= cups.Connection()
        self.proxy =  platform.node() + '-Armooo-PrintProxy'
        self.auth_path = os.path.expanduser('~/.cloudprintauth')

    def get_auth(self):
        if self.auth:
            return self.auth
        if not self.auth:
            auth = self.get_saved_auth()
            if auth:
                return auth

            username = raw_input('Google username: ')
            password = getpass.getpass()

            r = rest.REST('https://www.google.com', debug=False)
            auth_response = r.post(
                CLIENT_LOGIN_URL,
                {
                    'accountType': 'GOOGLE',
                    'Email': username,
                    'Passwd': password,
                    'service': PRINT_CLOUD_SERICE_ID,
                    'source': SOURCE,
                },
                'application/x-www-form-urlencoded')
            self.set_auth(auth_response['Auth'])
            return self.auth

    def get_saved_auth(self):
        if os.path.exists(self.auth_path):
            auth_file =  open(self.auth_path)
            self.auth = auth_file.read()
            auth_file.close()
            return self.auth

    def set_auth(self, auth):
            self.auth = auth
            if not os.path.exists(self.auth_path):
                auth_file = open(self.auth_path, 'w')
                os.chmod(self.auth_path, stat.S_IRUSR | stat.S_IWUSR)
                auth_file.close()
            auth_file = open(self.auth_path, 'w')
            auth_file.write(self.auth)
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
            { 'X-CloudPrint-Proxy' : 'ArmoooIsAnOEM'},
        )
        return [ PrinterProxy(self, p['id'], p['name']) for p in printers['printers'] ]

    def delete_printer(self, printer_id):
        r = self.get_rest()
        docs = r.post(
            PRINT_CLOUD_URL + 'delete',
            {
                'output' : 'json',
                'printerid': printer_id,
            },
            'application/x-www-form-urlencoded',
            { 'X-CloudPrint-Proxy' : 'ArmoooIsAnOEM'},
        )
        if self.verbose:
            print 'Deleted printer', printer_id

    def add_printer(self, name, description, ppd):
        r = self.get_rest()
        r.post(
            PRINT_CLOUD_URL + 'register',
            {
                'output' : 'json',
                'printer' : name,
                'proxy' :  self.proxy,
                'capabilities' : ppd.encode('utf-8'),
                'defaults' : ppd.encode('utf-8'),
                'status' : 'OK',
                'description' : description,
                'capsHash' : hashlib.sha1(ppd.encode('utf-8')).hexdigest(),
            },
            'application/x-www-form-urlencoded',
            { 'X-CloudPrint-Proxy' : 'ArmoooIsAnOEM'},
        )
        if self.verbose:
            print 'Added Printer', name

    def update_printer(self, printer_id, name, description, ppd):
        r = self.get_rest()
        r.post(
            PRINT_CLOUD_URL + 'update',
            {
                'output' : 'json',
                'printerid' : printer_id,
                'printer' : name,
                'proxy' : self.proxy,
                'capabilities' : ppd.encode('utf-8'),
                'defaults' : ppd.encode('utf-8'),
                'status' : 'OK',
                'description' : description,
                'capsHash' : hashlib.sha1(ppd.encode('utf-8')).hexdigest(),
            },
            'application/x-www-form-urlencoded',
            { 'X-CloudPrint-Proxy' : 'ArmoooIsAnOEM'},
        )
        if self.verbose:
            print 'Updated Printer', name

    def get_jobs(self, printer_id):
        r = self.get_rest()
        docs = r.post(
            PRINT_CLOUD_URL + 'fetch',
            {
                'output' : 'json',
                'printerid': printer_id,
            },
            'application/x-www-form-urlencoded',
            { 'X-CloudPrint-Proxy' : 'ArmoooIsAnOEM'},
        )

        if not 'jobs' in docs:
            return []
        else:
            return docs['jobs']

    def finish_job(self, job_id):
        r = self.get_rest()
        r.post(
            PRINT_CLOUD_URL + '/control',
            {
                'output' : 'json',
                'jobid': job_id,
                'status': 'DONE',
            },
            'application/x-www-form-urlencoded',
            { 'X-CloudPrint-Proxy' : 'ArmoooIsAnOEM' },
            )

class PrinterProxy(object):
    def __init__(self, cpp, printer_id, name):
        self.cpp = cpp
        self.id = printer_id
        self.name = name

    def get_jobs(self):
        return self.cpp.get_jobs(self.id)

    def update(self, description, ppd):
        return self.cpp.update_printer(self.id, self.name, description, ppd)

    def delete(self):
        return self.cpp.delete_printer(self.id)


def sync_printers(cups_connection, cpp):
    local_printer_names = set(cups_connection.getPrinters().keys())
    remote_printers = dict([(p.name, p) for p in cpp.get_printers()])
    remote_printer_names = set(remote_printers)

    #New printers
    for printer_name in local_printer_names - remote_printer_names:
        try:
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
            cpp.add_printer(printer_name, description, ppd)
        except cups.IPPError:
            print 'Skipping ' + printer_name

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
        'X-CloudPrint-Proxy' : 'ArmoooIsAnOEM',
        'Authorization' : 'GoogleLogin auth=%s' % cpp.get_auth()
    })
    pdf = urllib2.urlopen(request)
    tmp = tempfile.NamedTemporaryFile(delete=False)
    shutil.copyfileobj(pdf, tmp)
    tmp.flush()

    request = urllib2.Request(job['ticketUrl'], headers={
        'X-CloudPrint-Proxy' : 'ArmoooIsAnOEM',
        'Authorization' : 'GoogleLogin auth=%s' % cpp.get_auth()
    })
    options = json.loads(urllib2.urlopen(request).read())
    del options['request']
    options = dict( (str(k), str(v)) for k, v in options.items() )

    cpp.finish_job(job['id'])

    cups_connection.printFile(printer.name, tmp.name, job['title'], options)
    os.unlink(tmp.name)

def process_jobs(cups_connection, cpp, printers):
    while True:
        for printer in printers:
            for job in printer.get_jobs():
                process_job(cups_connection, cpp, printer, job)
        time.sleep(60)

def usage():
    print sys.argv[0] + ' [-d] [-p pid_file] [-h]'
    print '-d\t\t: enable daemon mode (requires the daemon module)'
    print '-p pid_file\t: path to write the pid to (default cloudprint.pid)'
    print '-h\t\t: display this help'

def main():
    opts, args = getopt.getopt(sys.argv[1:], 'dhp:')
    daemon = False
    pidfile = None
    for o, a in opts:
        if o == '-d':
            daemon = True
        elif o == '-p':
            pidfile = a
        elif o =='-h':
            usage()
            sys.exit()
    if not pidfile:
        pidfile = 'cloudprint.pid'

    cups_connection = cups.Connection()
    cpp = CloudPrintProxy()

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

    printers = cpp.get_printers()

    if daemon:
        try:
            import daemon
        except ImportError:
            print 'daemon module required for -d'
            sys.exit(1)
        daemon.daemonize(pidfile)

    process_jobs(cups_connection, cpp, printers)


if __name__ == '__main__':
    main()
