#!/usr/bin/env python
import rest
import os
import stat
import sys
import getopt

SOURCE = 'Armooo-PrintProxy-1'
PRINT_CLOUD_SERVICE_ID = 'cloudprint'
CLIENT_LOGIN_URL = '/accounts/ClientLogin'
PRINT_CLOUD_URL = '/cloudprint/'

class CloudPrintAuth(object):

    def __init__(self, verbose=True):
        self.verbose = verbose
        self.auth = None
	self.username = None
	self.password = None
        self.auth_path = os.path.expanduser('~/.cloudprintauth')
        self.xmpp_auth_path = os.path.expanduser('~/.cloudprintsaslauth')

    def get_auth(self):

        username = self.username
        password = self.password

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


def usage():
    print sys.argv[0] + ' [-u][-p][-r][-c][-h]'
    print '-u\t\t: google account username (overwrites current auth)'
    print '-p\t\t: google account password'
    print '-r\t\t: Reset the stored authentification and exit'
    print '-c\t\t: Check if already authentified and exit'
    print '-h\t\t: display this help'

def main():
    opts, args = getopt.getopt(sys.argv[1:], 'rchu:p:')
 
    username = None
    password = None
    resetauth = False
    checkauth = False
	
    for o, a in opts:
        if o == '-u':
            username = a
        elif o == '-p':
            password = a
        elif o == '-r':
            resetauth = True
        elif o == '-c':
            checkauth = True
        elif o =='-h':
            usage()
            sys.exit()

    cpp = CloudPrintAuth()

    if resetauth:
	cpp.del_saved_auth()
	print 'Authentification cleared'
	sys.exit()
    if checkauth:
        if os.path.exists(cpp.auth_path):
	    print 'Authentification ok'
            sys.exit()
	print 'Authentification missing'	
	sys.exit()

    if not username or not password:
	print 'You must specify username and password'
        usage()
	sys.exit()

    cpp.username = username
    cpp.password = password
    cpp.get_auth()


if __name__ == '__main__':
    main()
