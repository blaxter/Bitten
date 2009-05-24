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

def find_file_inside(basedir, file):
    """Given a filename, search inside a directory and return the relative
    path starting in basedir.

    E.g.
      basedir is /tmp/foo, file is a/b/foo.py but directory a/ is in
      /tmp/foo/bar, so returns bar/a/b/foo.py
    TODO this method should be move into Context object
    """
    basename = os.path.basename(file)
    file_basedir = file[0:-1-len(basename)]
    for dir, subdirs, files in os.walk(basedir):
        if dir.endswith(file_basedir):
            if basename in files:
                return os.path.join(dir[len(basedir)+1:], basename)
    return file

def find_test_class(name, is_rspec):
    """Given a class name camelized, returns it descamelized and with
    a directory prefix according to its name.

    :param name Camelized name of a test file
    :param is_rspec whether is an rspec test or a Test::Unit
    :type is_rspec: Boolean

    Examples:
      UserControllerTest will be functional/user_controller_test.rb
      if is_rspec is false
      User will be unit/user.rb if is_rspec is false and model/user_spec.rb
      if is_rspec is true
    """
    test_filename = reduce(
        lambda t,c: t + '_' + c if c.isupper() else t + c, name
    ).lower()
    test_path = []
    if is_rspec:
        test_path.append('spec')
        if test_filename.find('_helper') != -1:
            test_path.append('helpers')
        elif test_filename.find('_controller') != -1:
            test_path.append('controllers')
        elif test_filename.find('_view') != -1:
            test_path.append('views')
        else:
            test_path.append('models')
        test_filename += '_spec.rb'
    else:
        test_path.append('test')
        if test_filename.find('_controller') != -1:
            test_path.append('functional')
        elif test_filename.find('_integration') != -1:
            test_path.append('integration')
        else:
            test_path.append('unit')
        test_filename += '.rb'
    test_path.append(test_filename)
    return reduce(os.path.join, test_path)

def unit(ctxt, dir_=None):
    """Extract test results from a ci reporter report, see
    http://caldersphere.rubyforge.org/ci_reporter/

    A typical use could be:
        $ rake ci:setup:testunit test CI_REPORTS=results

    :param ctxt: the build context
    :type ctxt: `Context`
    :param dir\_: path to the directory with the XML test results
    """
    assert dir_, 'Missing required attribute "dir"'
    try:
        total, failed = 0, 0
        results = xmlio.Fragment()
        files = glob(ctxt.resolve(os.path.join(dir_, 'SPEC-*.xml')))
        if len(files) > 0:
            is_rspec = True
        else:
            # asume Test::Unit
            is_rspec = False
            files = glob(ctxt.resolve(os.path.join(dir_, 'TEST-*.xml')))
        for path in files:
            fileobj = file(path, 'r')
            try:
                # path is either /something/end/with/TEST-nameWanted.xml or
                # /something/end/with/SPEC-nameWanter-foo-bar.xml
                test_filename = path.split(os.sep)[-1].split('-')[1]
                if test_filename.find('.xml') != -1: test_filename = test_filename[0:-4]

                # FIXME only works with Rails projects
                filename = find_test_class(test_filename, is_rspec)
                filename = find_file_inside(ctxt.basedir, filename)

                testsuit = xmlio.parse(fileobj)
                fetch_attr = lambda what : int(testsuit.attr[what])
                total  += fetch_attr('tests')
                failed += fetch_attr('failures') + fetch_attr('errors')

                for testcase in testsuit.children('testcase'):
                    test = xmlio.Element('test')

                    test.attr['fixture']  = test_filename
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
                file       = find_file_inside(ctxt.basedir, filename.replace(os.sep, '/')),
                percentage = percentage,
                lines      = total_lines
            )
            coverage.append(module)

        ctxt.report('coverage', coverage)
    except IOError, e:
        log.warning('Error opening rcov summary file (%s)', e)

