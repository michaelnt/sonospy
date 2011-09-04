from brisa.core.reactors import install_default_reactor
reactor = install_default_reactor()

import unittest
import uuid
import ConfigParser
import StringIO
import codecs
import sys
import tempfile
import os

from sonospy.proxy import Proxy, ProxyError


class TestProxy(unittest.TestCase):
    def setUp(self):
        self.config = ConfigParser.ConfigParser()
        self.config.optionxform = str
        ini = ''
        f = codecs.open(os.path.dirname(__file__) + '/../pycpoint.ini', encoding=sys.getfilesystemencoding())
        for line in f:
            ini += line
        self.config.readfp(StringIO.StringIO(ini))

    def test_missing_db(self):
        """
        A missing sqlite db should cause a ProxyError to be raised
        """
        proxyuuid = 'uuid:' + str(uuid.uuid4())
        self.assertRaises(ProxyError, Proxy, "Proxy Name", "WMP", 'Sonospy', 
                          proxyuuid, self.config, None,createwebserver=True, 
                          webserverurl="http://127.0.0.1:8888", 
                          wmpurl="http://127.0.0.1:8888", startwmp=None, 
                          dbname="missing.sqlite", wmpudn=None, 
                          wmpcontroller=None, wmpcontroller2=None)

    def test_db_corrupted(self):
        """
        A corrupted sqlite db should cause a ProxyError to be raised
        """
        proxyuuid = 'uuid:' + str(uuid.uuid4())
        fh = tempfile.NamedTemporaryFile()
        fh.write("asd\n")
        dbname = fh.name
        self.assertTrue(os.access(dbname, os.R_OK))
        self.assertRaises(ProxyError, Proxy, "Proxy Name", "WMP", 'Sonospy', 
                          proxyuuid, self.config, None,createwebserver=True, 
                          webserverurl="http://127.0.0.1:8888", 
                          wmpurl="http://127.0.0.1:8888", startwmp=None, 
                          dbname=dbname, wmpudn=None, 
                          wmpcontroller=None, wmpcontroller2=None)

if __name__ == "__main__":
    unittest.main()
