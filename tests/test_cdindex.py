import unittest
import tempfile
import os
import sys
import pathlib
import contextlib

HERE = pathlib.Path(__file__).absolute().parent
# print(HERE.parent)
sys.path.insert(0, str(HERE.parent))

from pycpptool.get_tu import get_tu
from clang import cindex


@contextlib.contextmanager
def tmp(src):
    fd, tmp_name = tempfile.mkstemp(prefix='tmpheader_', suffix='.h')
    os.close(fd)
    f = open(tmp_name, 'w', encoding='utf-8')
    try:
        yield pathlib.Path(tmp_name)
    finally:
        f.close()
        os.unlink(tmp_name)


class CIndexTest(unittest.TestCase):
    def test_int(self) -> None:
        with tmp('int x = 0;') as path:
            tu = get_tu(path)
            self.assertIsInstance(tu, cindex.TranslationUnit)
            c = tu.cursor
            self.assertIsInstance(c, cindex.Cursor)
            print(c)


if __name__ == '__main__':
    unittest.main()