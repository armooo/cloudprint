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
PRINT_CLOUD_SERVICE_ID = 'cloudprint'
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
        self.xmpp_auth_path = os.path.expanduser('~/.cloudprintsaslauth')

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
            try:
                auth_response = r.post(
                    CLIENT_LOGIN_URL,
                    {
                        'accountType': 'GOOGLE',
                        'Email': username,
                        'Passwd': password,
                        'service': PRINT_CLOUD_SERVICE_ID,
                        'source': SOURCE,
                    },
                    'application/x-www-form-urlencoded')
                xmpp_response = r.post(CLIENT_LOGIN_URL,
                    {
                        'accountType': 'GOOGLE',
                        'Email': username,
                        'Passwd': password,
                        'service': 'mail',
                        'source': SOURCE,
                    },
                    'application/x-www-form-urlencoded')
                jid = username if '@' in username else username + '@gmail.com'
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
            self.auth = auth_file.read()
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
            PRINT_CLOUD_URL + 'control',
            {
                'output' : 'json',
                'jobid': job_id,
                'status': 'DONE',
            },
            'application/x-www-form-urlencoded',
            { 'X-CloudPrint-Proxy' : 'ArmoooIsAnOEM' },
            )

    def fail_job(self, job_id):
        r = self.get_rest()
        r.post(
            PRINT_CLOUD_URL + 'control',
            {
                'output' : 'json',
                'jobid': job_id,
                'status': 'ERROR',
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

class App(object):
    def __init__(self, cups_connection=None, cpp=None, printers=None, pidfile_path=None):
        self.cups_connection = cups_connection
        self.cpp = cpp
        self.printers = printers
        self.pidfile_path = pidfile_path
        self.stdin_path = '/dev/null'
        self.stdout_path = '/dev/tty'
        self.stderr_path = '/dev/tty'
        self.pidfile_timeout = 5

    def run(self):
        process_jobs(self.cups_connection, self.cpp, self.printers)


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
            ppd = ppd.decode('utf-8')
            description = cups_connection.getPrinterAttributes(printer_name)['printer-info']
            cpp.add_printer(printer_name, description, ppd)
        except (cups.IPPError, UnicodeDecodeError):
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

    try:
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
        print "SUCCESS ",job['title'].encode('unicode-escape')

    except:
        cpp.fail_job(job['id'])
        print "ERROR",job['title'].encode('unicode-escape')

def process_jobs(cups_connection, cpp, printers):
    while True:
        try:
            for printer in printers:
                for job in printer.get_jobs():
                    process_job(cups_connection, cpp, printer, job)
            wait_for_new_job(file(cpp.xmpp_auth_path).read())
        except Exception, e:
            print e
            print "ERROR: Couldn't Connect to Cloud Service. Will Try again in 60 Seconds";
            time.sleep(60)

def wait_for_new_job(sasl_token):
    # https://developers.google.com/cloud-print/docs/rawxmpp
    import ssl, socket
    xmpp = ssl.wrap_socket(socket.socket())
    xmpp.connect(('talk.google.com', 5223))
    def msg(msg=' '):
        xmpp.write(msg)
        while 1:
            response = xmpp.read()
            if response.strip():
                return response
    def start_stream():
        response = msg('<stream:stream to="gmail.com" version="1.0" xmlns:stream="http://etherx.jabber.org/streams" xmlns="jabber:client">')
        while '</stream:features>' not in response:
            response += msg()
    start_stream()
    response = msg('<auth xmlns="urn:ietf:params:xml:ns:xmpp-sasl" mechanism="X-GOOGLE-TOKEN">%s</auth>' % sasl_token)
    assert 'success' in response, response
    start_stream()
    response = msg('<iq type="set"><bind xmlns="urn:ietf:params:xml:ns:xmpp-bind"><resource>%s</resource></bind></iq>' % 'ArmoooIsAnOEM')
    assert 'result' in response, response
    full_jid = response.split('<jid>')[1].split('</jid>')[0]
    bare_jid = full_jid.split('/')[0]
    response = msg('<iq type="set"><session xmlns="urn:ietf:params:xml:ns:xmpp-session"/></iq>')
    assert 'result' in response, response
    response = msg('<iq type="set" to="%s"><subscribe xmlns="google:push"><item channel="cloudprint.google.com" from="cloudprint.google.com"/></subscribe></iq>' % bare_jid)
    assert 'result' in response, response
    while 'message' not in response:
        response = msg()
    return response

def usage():
    print sys.argv[0] + ' [-d][-l][-h] [-p pid_file]'
    print '-d\t\t: enable daemon mode (requires the daemon module)'
    print '-l\t\t: logout of the google account'
    print '-p pid_file\t: path to write the pid to (default cloudprint.pid)'
    print '-h\t\t: display this help'

def main():
    opts, args = getopt.getopt(sys.argv[1:], 'dlhp:')
    daemon = False
    logout = False
    pidfile = None
    for o, a in opts:
        if o == '-d':
            daemon = True
        elif o == '-l':
            logout = True
        elif o == '-p':
            pidfile = a
        elif o =='-h':
            usage()
            sys.exit()
    if not pidfile:
        pidfile = 'cloudprint.pid'

    cups_connection = cups.Connection()
    cpp = CloudPrintProxy()

    if logout:
        cpp.del_saved_auth()
        print 'logged out'
        return

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
            from daemon import runner
        except ImportError:
            print 'daemon module required for -d'
            print '\tyum install python-daemon, or apt-get install python-daemon, or pip install python-daemon'
            sys.exit(1)
        
        app = App(cups_connection=cups_connection,
                  cpp=cpp, printers=printers,
                  pidfile_path=os.path.abspath(pidfile))
        sys.argv=[sys.argv[0], 'start']
        daemon_runner = runner.DaemonRunner(app)
        daemon_runner.do_action()
    else:
        process_jobs(cups_connection, cpp, printers)

if __name__ == '__main__':
    main()
