# -*- coding: utf-8 -*-

"""Recipe commands for tools commonly used in ruby projects."""

from glob import glob
import logging
import os
import posixpath
import shlex
import tempfile

from bitten.build import CommandLine
from bitten.util import xmlio

from lxml import etree

log = logging.getLogger('bitten.build.rubytools')

__docformat__ = 'restructuredtext en'

def find_test_class(name):
    """Given a class name camelized, returns it descamelized and with
    a directory prefix according to its name.

    :param name Camelized name of a test file

    Examples:
      UserControllerTest will be functional/user_controller_test.rb
      User will be unit/user.rb
    """
    class_name = ''
    for i in range(len(name)):
        if name[i].isupper():
            class_name += '_'
        class_name += name[i].lower()
    class_name = class_name[1:]
    ret = 'test/'
    if class_name.find('_controller_') != -1:
        ret += 'functional/'
    elif class_name.find('_integration_') != -1:
        ret += 'integration/'
    else:
        ret += 'unit/'
    return ret + class_name + '.rb'

def unit(ctxt, file_=None):
    """Extract test results from a ci reporter report, see
    http://caldersphere.rubyforge.org/ci_reporter/

    A typical use could be:
        $ rake ci:setup:testunit test CI_REPORTS=results

    :param ctxt: the build context
    :type ctxt: `Context`
    :param file\_: path to the XML test results; may contain globbing
                  wildcards for matching multiple results files
    """
    assert file_, 'Missing required attribute "file"'
    try:
        total, failed = 0, 0
        results = xmlio.Fragment()
        for path in glob(ctxt.resolve(file_)):
            fileobj = file(path, 'r')
            try:
                # path is /something/end/with/TEST-nameWanted.xml
                class_name = path.split(os.sep)[-1].split('-')[-1][0:-4]

                # FIXME only works with Rails projects
                filename = find_test_class(class_name)

                testsuit = xmlio.parse(fileobj)
                fetch_attr = lambda what : int(testsuit.attr[what])
                total  += fetch_attr('tests')
                failed += fetch_attr('failures') + fetch_attr('errors')

                for testcase in testsuit.children('testcase'):
                    test = xmlio.Element('test')

                    test.attr['fixture']  = class_name
                    test.attr['name']     = testcase.attr['name']
                    test.attr['duration'] = testcase.attr['time']

                    if os.path.exists(ctxt.resolve(filename)):
                        test.attr['file'] = filename

                    result = list(testcase.children())
                    if result:
                        test.attr['status'] = result[0].name
                        test.append(xmlio.Element('traceback')[
                            result[0].gettext()
                        ])
                    else:
                        test.attr['status'] = 'success'
                    results.append(test)
            finally:
                fileobj.close()
        if failed:
            ctxt.error('%d of %d test%s failed' % (failed, total,
                       total != 1 and 's' or ''))
        ctxt.report('test', results)
    except IOError, e:
        log.warning('Error opening ci:unit results file (%s)', e)
    except xmlio.ParseError, e:
        log.warning('Error parsing ci:unit results file (%s)', e)

def rcov(ctxt, file_=None):
    """Extract data from a ``rake test:xxx:rcov`` run, which generates html
    output with the coverage information

    :param ctxt: the build context
    :type ctxt: `Context`
    :param file_: html file with the output of rcov
    """
    assert file_, 'Missing required attribute "file"'

    xpath_for = { 'each_file'  : '/html/body/table/tbody/tr',
                  'filename'   : './td[1]/a/text()',
                  'total_lines': './td[2]/tt/text()',
                  'percentage' : './td[5]/table/tr/td/tt/text()'}

    try:
        tree = etree.parse(ctxt.resolve(file_), etree.HTMLParser())
        coverage = xmlio.Fragment()
        for item in tree.xpath(xpath_for['each_file'])[1:]:
            get_value   = lambda key: item.xpath(xpath_for[key])[0].strip()

            filename    = get_value('filename')
            total_lines = get_value('total_lines')
            percentage  = float(get_value('percentage').strip('%'))

            module = xmlio.Element('coverage',
                                   name       = filename,
                                   file       = filename.replace(os.sep, '/'),
                                   percentage = percentage,
                                   lines      = total_lines)
            coverage.append(module)

        ctxt.report('coverage', coverage)
    except IOError, e:
        log.warning('Error opening rcov summary file (%s)', e)

