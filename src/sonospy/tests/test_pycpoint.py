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
import mock

from sonospy.pycpoint import ControlPointWeb
from sonospy.proxy import ProxyError
from optparse import Values

class TestControlPointWeb(unittest.TestCase):
    def setUp(self):
        self.config = ConfigParser.ConfigParser()
        self.config.optionxform = str
        ini = ''
        self.inifile = os.path.dirname(__file__) + '/../pycpoint.ini'
        f = codecs.open(self.inifile, encoding=sys.getfilesystemencoding())
        for line in f:
            ini += line
        self.config.readfp(StringIO.StringIO(ini))

    def test_missing_db(self):
        options = Values()
        options.proxyonly = False
        options.wmpproxy = ['Sonospy=Henkelis,missing.db']
        self.assertRaises(ProxyError, ControlPointWeb, options, self.inifile)
        #reactor.main_loop_iterate()

    def test_valid_db(self):
        options = Values()
        options.proxyonly = False
        dbname = os.path.dirname(__file__) + '/../Sonospy.db'
        options.wmpproxy = ['Sonospy=Henkelis,%s' % dbname]  # Fixme create this db for the test
        options.proxyonly = True
        cp = ControlPointWeb(options, self.inifile)
        #reactor.main_loop_iterate()

if __name__ == "__main__":
    unittest.main()
