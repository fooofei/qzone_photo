# -*- coding: UTF-8 -*-


'''
输入输出函数

其他脚本中的进入的字符串参数和输出到屏幕的字符串参数都需要经过转换
进入的字符串需要转为 unicode （为了支持路径中的中文）
输出到屏幕的字符串需要从 unicode 转为 str （为了兼容重定向符号 > ,某些时候我们需要把脚本运行结果重定向到文件）
'''


import os
import sys

pyver = sys.version_info.major
if pyver >= 3:
    io_code = str
    io_raw_input = input
else:
    io_code = unicode
    io_raw_input = raw_input

def io_in_arg(arg):
    if isinstance(arg, unicode):
        return arg
    codes = ['utf-8', 'gbk']
    for c in codes:
        try:
            return arg.decode(c)
        except UnicodeDecodeError as er:
            pass
    else:
        raise er

def io_out_arg(arg):
    if isinstance(arg, unicode):
        return arg.encode('gbk')
    return arg


def io_iter_files_from_arg(args):
    for e in args:
        if os.path.isfile(e):
            yield io_in_arg(e)
        elif os.path.isdir(e):
            for root, sub, files in os.walk(e):
                for i in files:
                    yield io_in_arg(os.path.join(root, i))
        else:
            io_print(u'unaccept arg {0}'.format(e))
    raise StopIteration


def io_sys_stdout(arg):
    arg = io_out_arg(arg)
    if isinstance(arg, (tuple, list, dict)):
        x = map(lambda e:str(io_out_arg(e)), arg)
        arg = '\t'.join(x)
    return sys.stdout.write(arg)


def io_print(arg):
    io_sys_stdout(arg)
    print ('')

def io_files_from_arg(args):
    r = []
    for e in args:
        if os.path.isfile(e):
          r.append(io_in_arg(e))
        elif os.path.isdir(e):
            for root, sub, files in os.walk(e):
                for i in files:
                    x = os.path.join(root, i)
                    r.append(io_in_arg(x))
        else:
            io_print (u'unaccept arg {0}'.format(io_out_arg(e)))
    return r


def io_is_path_valid(pathname):
    '''
    路径是否有效
    http://stackoverflow.com/questions/9532499/check-whether-a-path-is-valid-in-python-without-creating-a-file-at-the-paths-ta
    :param pathname:
    :return: bool
    '''
    import errno
    ERROR_INVALID_NAME = 123
    try:
        if isinstance(pathname, unicode):
            pathname = pathname.encode('gbk')

        if not isinstance(pathname, str) or not pathname:
            return False
        _, pathname = os.path.splitdrive(pathname)
        root_dirname = os.environ.get('HOMEDRIVE', 'C:') if sys.platform == 'win32' else os.path.sep
        root_dirname = root_dirname.rstrip(os.path.sep) + os.path.sep

        for pathname_part in pathname.split(os.path.sep):
            try:
                os.lstat(root_dirname + pathname_part)
            except OSError as exc:
                if hasattr(exc, 'winerror'):
                    if exc.winerror == ERROR_INVALID_NAME:
                        return False
                elif exc.errno in {errno.ENAMETOOLONG, errno.ERANGE}:
                    return False
    except TypeError:
        return False
    else:
        return True





'''
end
'''


def test_unicode_list():
    arg = [u'你好',u"中国"]
    io_print(arg)

def test():
    test_unicode_list()


if __name__ == '__main__':
    test()