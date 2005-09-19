# -*- coding: iso8859-1 -*-
#
# Copyright (C) 2005 Christopher Lenz <cmlenz@gmx.de>
# All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution. The terms
# are also available at http://bitten.cmlenz.net/wiki/License.

import os
import re
try:
    from cStringIO import StringIO
except:
    from StringIO import StringIO
import sys
import time
from distutils.core import Command
from distutils.errors import DistutilsExecError, DistutilsOptionError
from unittest import _TextTestResult, TextTestRunner

from bitten.util.xmlio import Element, SubElement


class XMLTestResult(_TextTestResult):

    def __init__(self, stream, descriptions, verbosity):
        _TextTestResult.__init__(self, stream, descriptions, verbosity)
        self.tests = []
        self.orig_stdout = self.orig_stderr = None
        self.buf_stdout = self.buf_stderr = None

    def startTest(self, test):
        _TextTestResult.startTest(self, test)
        filename = sys.modules[test.__module__].__file__
        if filename.endswith('.pyc') or filename.endswith('.pyo'):
            filename = filename[:-1]
        self.tests.append([test, filename, time.time(), None, None])

        # Record output by the test to stdout and stderr
        self.old_stdout, self.buf_stdout = sys.stdout, StringIO()
        self.old_stderr, self.buf_stderr = sys.stderr, StringIO()
        sys.stdout, sys.stderr = self.buf_stdout, self.buf_stderr

    def stopTest(self, test):
        self.tests[-1][2] = time.time() - self.tests[-1][2]
        self.tests[-1][3] = self.buf_stdout.getvalue()
        self.tests[-1][4] = self.buf_stderr.getvalue()
        sys.stdout, sys.stderr = self.orig_stdout, self.orig_stderr

        _TextTestResult.stopTest(self, test)


class XMLTestRunner(TextTestRunner):

    def __init__(self, stream=sys.stdout, xml_stream=None):
        TextTestRunner.__init__(self, stream, descriptions=0, verbosity=2)
        self.xml_stream = xml_stream

    def _makeResult(self):
        return XMLTestResult(self.stream, self.descriptions, self.verbosity)

    def run(self, test):
        result = TextTestRunner.run(self, test)
        if not self.xml_stream:
            return result

        root = Element('unittest-results')
        for testcase, filename, timetaken, stdout, stderr in result.tests:
            status = 'success'
            tb = None

            if testcase in [e[0] for e in result.errors]:
                status = 'error'
                tb = [e[1] for e in result.errors if e[0] is testcase][0]
            elif testcase in [f[0] for f in result.failures]:
                status = 'failure'
                tb = [f[1] for f in result.failures if f[0] is testcase][0]

            name = str(testcase)
            fixture = None
            description = testcase.shortDescription() or ''
            if description.startswith('doctest of '):
                name = 'doctest'
                fixture = description[11:]
                description = None
            else:
                match = re.match('(\w+)\s+\(([\w.]+)\)', name)
                if match:
                    name = match.group(1)
                    fixture = match.group(2)

            test_elem = SubElement(root, 'test', file=filename, name=name,
                                   fixture=fixture, status=status,
                                   duration=timetaken)
            if description:
                SubElement(test_elem, 'description')[description]
            if stdout:
                SubElement(test_elem, 'stdout')[stdout]
            if stderr:
                SubElement(test_elem, 'stdout')[stderr]
            if tb:
                SubElement(test_elem, 'traceback')[tb]

        root.write(self.xml_stream, newlines=True)
        return result


class unittest(Command):
    description = "Runs the unit tests, and optionally records code coverage"
    user_options = [('test-suite=', 's',
                     'Name of the unittest suite to run'),
                    ('xml-output=', None,
                     'Path of the XML file where test results are written to'),
                    ('coverage-dir=', None,
                     'Directory where coverage files are to be stored'),
                     ('coverage-results=', None,
                     'Name of the file where the coverage summary should be stored')]

    def initialize_options(self):
        self.test_suite = None
        self.xml_results = None
        self.coverage_results = None
        self.coverage_dir = None

    def finalize_options(self):
        if not self.test_suite:
            raise DistutilsOptionError, 'Missing required attribute test-suite'
        if self.xml_results is not None:
            if not os.path.exists(os.path.dirname(self.xml_results)):
                os.makedirs(os.path.dirname(self.xml_results))
            self.xml_results = open(self.xml_results, 'w')

    def run(self):
        if self.coverage_dir:
            from trace import Trace
            trace = Trace(ignoredirs=[sys.prefix, sys.exec_prefix],
                          trace=False, count=True)
            try:
                trace.runfunc(self._run_tests)
            finally:
                results = trace.results()
                real_stdout = sys.stdout
                sys.stdout = open(self.coverage_results, 'w')
                try:
                    results.write_results(show_missing=True, summary=True,
                                          coverdir=self.coverage_dir)
                finally:
                    sys.stdout.close()
                    sys.stdout = real_stdout
        else:
            self._run_tests()

    def _run_tests(self):
        import unittest
        suite = __import__(self.test_suite)
        for comp in self.test_suite.split('.')[1:]:
            suite = getattr(suite, comp)
        runner = XMLTestRunner(stream=sys.stdout, xml_stream=self.xml_results)
        result = runner.run(suite.suite())
        if result.failures or result.errors:
            raise DistutilsExecError, 'unit tests failed'
