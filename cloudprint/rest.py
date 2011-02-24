import httplib
import json
import urllib
import urlparse
import UserDict
import UserList
import UserString

class REST:
    class RESTException(Exception):
        def __init__(self, name, code, msg):
            self.name = name
            self.code = code
            self.msg = msg

        def __str__(self):
            return '%s:%s\nMessage: %s' % (self.name, self.code, self.msg)

        def __repr__(self):
            return '%s:%s\nMessage: %s' % (self.name, self.code, self.msg)

    CONTENT_ENCODE = {
        'text/json' : lambda x: json.dumps(x, encoding='UTF-8'),
        'application/json' : lambda x: json.dumps(x, encoding='UTF-8'),
        'application/x-www-form-urlencoded' : urllib.urlencode,
    }

    CONTENT_DECODE = {
        'text/json' : json.loads,
        'application/json' : json.loads,
        'application/x-www-form-urlencoded' : lambda x : dict( (k, v[0] ) for k, v in [urlparse.parse_qs(x).items()]),
        'text/plain' : lambda x : dict( l.split('=') for l in x.strip().split('\n') ),
    }

    RESULT_WRAPTERS = {
        type({}) : UserDict.UserDict,
        type([]) : UserList.UserList,
        type('') : UserString.UserString,
        type(u'') : UserString.UserString,
    }

    def __init__(self, host, auth=None, debug=False):
        proto, host = host.split('://')
        if proto == 'https':
            self._conn = httplib.HTTPSConnection(host)
        else:
            self._conn = httplib.HTTPConnection(host)
        self.debug = debug
        if debug:
            self._conn.set_debuglevel(10)
        else:
            self._conn.set_debuglevel(0)

        self.auth = auth

    def rest_call(self, verb, path, data, content_type, headers={}, response_type=None):

        data = self.CONTENT_ENCODE[content_type](data)

        headers['Content-Type'] = content_type + '; charset=UTF-8'
        headers['Accept-Charset'] = 'UTF-8'
        if self.auth:
            headers['Authorization'] = 'GoogleLogin auth=%s' % self.auth

        self._conn.request(verb, path, data, headers)

        try:
            resp = self._conn.getresponse()
            if response_type:
                content_type = response_type
            else:
                content_type = resp.getheader('Content-Type')
        except httplib.BadStatusLine, e:
            if not e.line:
                self._conn.close()
                return self.rest_call(verb, path, data)
            else:
                raise

        data = resp.read()
        if self.debug:
            print data
        if resp.status != 200:
            try:
                error = self.CONTENT_DECODE[content_type](data)
                raise REST.RESTException(error['Name'], error['Code'], error['Message'])
            except (ValueError, KeyError):
                raise REST.RESTException('REST Error', resp.status, data)

        decoded_data = self.CONTENT_DECODE[content_type](data)
        try:
            decoded_data = self.RESULT_WRAPTERS[type(decoded_data)](decoded_data)
        except KeyError:
            pass
        decoded_data.headers = dict(resp.getheaders())
        return decoded_data

    def get(self, path, content_type='text/json', headers={}, response_type=None):
        return self.rest_call('GET', path, '', content_type, headers, response_type)

    def put(self, path, data, content_type='text/json', headers={}, response_type=None):
        return self.rest_call('PUT', path, data, content_type, headers, response_type)

    def post(self, path, data, content_type='text/json', headers={}, response_type=None):
        return self.rest_call('POST', path, data, content_type, headers, response_type)

    def delete(self, path, data, content_type='text/json', headers={}, response_type=None):
        return self.rest_call('DELETE', path, data, content_type, headers, response_type)


