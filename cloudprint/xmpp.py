import ssl
import socket
import select
import time

from collections import deque
from xml.etree.ElementTree import XMLParser, TreeBuilder

# frequency with which to send keepalives
KEEPALIVE_PERIOD=60.0

class XmppXmlHandler(object):
    STREAM_TAG='{http://etherx.jabber.org/streams}stream'

    def __init__(self):
        self._stack = 0
        self._builder = TreeBuilder()
        self._results = deque()

    def data(self,data):
        self._builder.data(data)

    def start(self, tag, attrib):
        if tag == self.STREAM_TAG:
            return

        self._builder.start(tag, attrib)
        self._stack += 1

    def end(self, tag):
        self._stack -= 1
        elem = self._builder.end(tag)

        if self._stack == 0:
            self._results.append(elem)

    """If a top-level XML element has been completed since the last call to
    getElem, return it; else return None."""
    def getElem(self):
        try:
            return self._results.popleft()
        except IndexError:
            return None

class XmppConnection(object):
    def __init__(self, LOGGER):
        self._connected = False
        self._wrappedsock = None
        self._LOGGER = LOGGER

    """read pending data from the socket, and send it to the XML parser.

    return False if the socket is closed, True if it is ok"""
    def _readSocket(self):
        try:
            data = self._wrappedsock.recv(1024)
            if data is None or len(data) == 0:
                # socket closed
                raise Exception("xmpp socket closed")
        except Exception:
            self._conected = False
            raise

        self._LOGGER.debug('<<< %s' % data)
        self._nextkeepalive = time.time() + KEEPALIVE_PERIOD
        self._xmlparser.feed(data)

    """write a message to the XMPP server"""
    def _writeSocket(self,msg):
        self._LOGGER.debug('>>> %s' % msg)
        try:
            self._wrappedsock.sendall(msg)
            self._nextkeepalive = time.time() + KEEPALIVE_PERIOD
        except Exception:
            self._conected = False
            raise

    """send a message to the XMPP server, and wait for a response

    returns the XML element tree of the response"""
    def _msg(self,msg=None):
        if msg is not None:
            self._writeSocket(msg)

        while True:
            elem = self._handler.getElem()

            if elem is not None:
                assert not elem.tag.endswith('failure') and not elem.tag.endswith('error')
                return elem

            # need more data; block until it becomes available
            self._readSocket()


    """Check for any notifications which have already been received"""
    def _checkForNotification(self):
        return self._handler.getElem() is not None

    def _sendKeepAlive(self):
        self._LOGGER.info("Sending XMPP keepalive")
        self._writeSocket(" ")


    """Establish a new connection to the XMPP server"""
    def connect(self,host,port,use_ssl,sasl_token):
        # first close any existing socket
        self.close()

        self._LOGGER.info("Establishing connection to xmpp server %s:%i" % 
                    (host, port))
        self._xmppsock = socket.socket()
        self._wrappedsock = self._xmppsock

        try:
            if use_ssl:
                self._wrappedsock = ssl.wrap_socket(self._xmppsock)
            self._wrappedsock.connect((host, port))

            self._handler = XmppXmlHandler()
            self._xmlparser = XMLParser(target=self._handler)

            # https://developers.google.com/cloud-print/docs/rawxmpp
            self._msg('<stream to="gmail.com" version="1.0" xmlns="http://etherx.jabber.org/streams">')
            self._msg('<auth xmlns="urn:ietf:params:xml:ns:xmpp-sasl" mechanism="X-GOOGLE-TOKEN">%s</auth>' % sasl_token)
            self._msg('<s:stream to="gmail.com" version="1.0" xmlns:s="http://etherx.jabber.org/streams" xmlns="jabber:client">')
            iq = self._msg('<iq type="set"><bind xmlns="urn:ietf:params:xml:ns:xmpp-bind"><resource>Armooo</resource></bind></iq>')
            bare_jid = iq[0][0].text.split('/')[0]
            self._msg('<iq type="set" to="%s"><subscribe xmlns="google:push"><item channel="cloudprint.google.com" from="cloudprint.google.com"/></subscribe></iq>' % bare_jid)
        except Exception:
            self.close()
            raise

        self._LOGGER.info("xmpp connection established")
        self._connected = True


    """Close the connection to the XMPP server"""
    def close(self):
        if self._wrappedsock is not None:
            self._wrappedsock.close()
            self._wrappedsock = None
        self._connected = False
        self._nextkeepalive = None


    """Check if we are connected to the XMPP server

    returns true if the connection is active; false otherwise"""
    def isConnected(self):
        return self._connected


    """wait for a timeout or event notification"""
    def awaitNotification(self, timeout):
        now = time.time()

        timeoutend = None
        if timeout is not None:
            timeoutend = now + timeout

        while True:
            if self._checkForNotification():
                return True

            if timeoutend is not None and timeoutend - now <= 0:
                # timeout
                return False

            waittime = self._nextkeepalive - now
            self._LOGGER.debug("%f seconds until next keepalive" % waittime)

            if timeoutend is not None:
                remaining = timeoutend - now
                if remaining < waittime:
                    waittime = remaining
                    self._LOGGER.debug("%f seconds until timeout" % waittime)

            if waittime < 0:
                waittime = 0
                    
            sock = self._xmppsock
            (r, w, e) = select.select([sock], [], [sock], waittime)

            now = time.time()

            try:
                if self._nextkeepalive - now <= 0:
                    self._sendKeepAlive()

                if sock in r:
                    self._readSocket()

                if sock in e:
                    self._LOGGER.warn("Error in xmpp connection")
                    raise Exception("xmpp connection errror")

            except Exception:
                self.close()
                raise

