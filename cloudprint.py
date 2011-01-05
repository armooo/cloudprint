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
            if os.path.exists(self.auth_path):
                self.auth = open(self.auth_path).read()
                return self.auth

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

    def set_auth(self, auth):
            self.auth = auth
            if not os.path.exists(self.auth_path):
                os.mknod(self.auth_path)
            open(self.auth_path, 'w').write(self.auth)

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
            'text/json'
        )
        return printers['printers']

    def add_update_printer(self, name, description, ppd):
        r = self.get_rest()
        printers = self.get_printers()
        if not printers:
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
                'text/json'
            )
            if self.verbose:
                print 'Added Printer', name
        else:
            r.post(
                PRINT_CLOUD_URL + 'update',
                {
                    'output' : 'json',
                    'printerid' : printers[0]['id'],
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
                'text/json'
            )
            if self.verbose:
                print 'Updated Printer', name

    def get_priner_id(self):
        if not self.printer_id:
            printers = self.get_printers()
            if len(printers) != 1:
                raise Exception('I only support a single printer\nManage your printers at http://www.google.com/cloudprint')
            self.printer_id = printers[0]['id']
        return self.printer_id

    def get_jobs(self):
        r = self.get_rest()
        printer_id = self.get_priner_id()
        docs = r.post(
            PRINT_CLOUD_URL + 'fetch',
            {
                'printerid': printer_id
            },
            'application/x-www-form-urlencoded',
            { 'X-CloudPrint-Proxy' : 'ArmoooIsAnOEM'},
            'text/json'
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
                'jobid': job_id,
                'status': 'DONE',
            },
            'application/x-www-form-urlencoded',
            { 'X-CloudPrint-Proxy' : 'ArmoooIsAnOEM' },
            'text/json'
            )


if __name__ == '__main__':

    cups_connection = cups.Connection()
    default_printer = cups_connection.getDefault()
    if not default_printer:
        raise Exception('No default printer found')
    ppd = open(cups_connection.getPPD(default_printer)).read()

    #This is bad it should use the LanguageEncoding in the PPD
    #But a lot of utf-8 PPDs seem to say they are ISOLatin1
    try:
        ppd = ppd.decode('utf-8')
    except UnicodeDecodeError:
        pass

    description = cups_connection.getPrinterAttributes(default_printer)['printer-info']

    cpp = CloudPrintProxy()
    cpp.add_update_printer(default_printer, description, ppd)

    while True:
        for job in cpp.get_jobs():
            request = urllib2.Request(job['fileUrl'], headers={'X-CloudPrint-Proxy' : 'ArmoooIsAnOEM'})
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

            cups_connection.printFile(default_printer, tmp.name, job['title'], options)
            os.unlink(tmp.name)

        time.sleep(60)

