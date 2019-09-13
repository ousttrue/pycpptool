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
    with open(tmp_name, 'w', encoding='utf-8') as f:
        f.write(src)
    try:
        yield pathlib.Path(tmp_name)
    finally:
        os.unlink(tmp_name)


class CIndexTest(unittest.TestCase):
    def test_int(self) -> None:
        with tmp('int x = 123;') as path:
            tu = get_tu(path)
            self.assertIsInstance(tu, cindex.TranslationUnit)

            # TRANSLATION_UNIT
            c: cindex.Cursor = tu.cursor
            self.assertIsInstance(c, cindex.Cursor)
            self.assertEqual(cindex.CursorKind.TRANSLATION_UNIT, c.kind)
            self.assertIsNone(c.location.file)
            children = [child for child in c.get_children()]
            self.assertEqual(1, len(children))

            # VAR_DECL: int x
            c = children[0]
            self.assertEqual(str(path), c.location.file.name)

            self.assertEqual(cindex.CursorKind.VAR_DECL, c.kind)
            self.assertEqual('x', c.spelling)
            self.assertEqual('x', c.displayname)
            children = [child for child in c.get_children()]
            self.assertEqual(1, len(children))

            # INTEGER_LITERAL: = 123
            c = children[0]

            self.assertEqual(cindex.CursorKind.INTEGER_LITERAL, c.kind)
            self.assertEqual(c.type.kind, cindex.TypeKind.INT)

            tokens = [t.spelling for t in c.get_tokens()]
            value = int(tokens[0])
            self.assertEqual(123, value)

            children = [child for child in c.get_children()]
            self.assertEqual(0, len(children))
            print()

    def test_void_ptr(self) -> None:
        #
        # tu
        #  VAR_DECL: x
        #    UNEXPOSED_EXPR: =
        #       CXX_NULL_PTR_LITERAL_EXPR: nullptr
        with tmp('void *x = nullptr;') as path:
            tu = get_tu(path)
            self.assertIsInstance(tu, cindex.TranslationUnit)

            # TRANSLATION_UNIT
            c: cindex.Cursor = tu.cursor
            self.assertIsInstance(c, cindex.Cursor)
            self.assertEqual(cindex.CursorKind.TRANSLATION_UNIT, c.kind)
            self.assertIsNone(c.location.file)
            children = [child for child in c.get_children()]
            self.assertEqual(1, len(children))

            # VAR_DECL: int x
            c = children[0]
            self.assertEqual(str(path), c.location.file.name)
            self.assertEqual(cindex.CursorKind.VAR_DECL, c.kind)
            self.assertEqual('x', c.spelling)
            self.assertEqual('x', c.displayname)
            self.assertEqual(c.type.kind, cindex.TypeKind.POINTER)
            self.assertEqual('void *', c.type.spelling)
            children = [child for child in c.get_children()]
            self.assertEqual(1, len(children))

            # POINTER: void* x = nullptr
            c = children[0]
            self.assertEqual(cindex.CursorKind.UNEXPOSED_EXPR, c.kind)
            self.assertEqual(c.type.kind, cindex.TypeKind.POINTER)
            self.assertEqual('void *', c.type.spelling)
            children = [child for child in c.get_children()]
            self.assertEqual(1, len(children))

            # nullptr
            c = children[0]

            self.assertEqual(cindex.CursorKind.CXX_NULL_PTR_LITERAL_EXPR,
                             c.kind)
            self.assertEqual(c.type.kind, cindex.TypeKind.NULLPTR)
            print()

    def test_int_ptr(self) -> None:
        #
        # tu
        #  VAR_DECL: x
        with tmp('int *x;') as path:
            tu = get_tu(path)
            self.assertIsInstance(tu, cindex.TranslationUnit)

            # TRANSLATION_UNIT
            c: cindex.Cursor = tu.cursor
            self.assertIsInstance(c, cindex.Cursor)
            self.assertEqual(cindex.CursorKind.TRANSLATION_UNIT, c.kind)
            self.assertIsNone(c.location.file)
            children = [child for child in c.get_children()]
            self.assertEqual(1, len(children))

            # VAR_DECL: int* x
            c = children[0]
            self.assertEqual(str(path), c.location.file.name)

            self.assertEqual(cindex.CursorKind.VAR_DECL, c.kind)
            self.assertEqual('x', c.spelling)
            self.assertEqual('x', c.displayname)
            self.assertEqual(c.type.kind, cindex.TypeKind.POINTER)
            self.assertEqual('int *', c.type.spelling)

            children = [child for child in c.get_children()]
            self.assertEqual(0, len(children))

            print()


if __name__ == '__main__':
    unittest.main()
