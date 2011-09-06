import unittest
import os
import sys

from sonospy.pycpoint import parseOptions

class TestParseOptions(unittest.TestCase):
    def test_wmpproxy(self):
        args = ['-p', '-wSonospy=Henkelis,Sonospy.db']
        options = parseOptions(args)
        self.assertEquals(options.wmpproxy,['Sonospy=Henkelis,Sonospy.db']) 

if __name__ == "__main__":
    unittest.main()

