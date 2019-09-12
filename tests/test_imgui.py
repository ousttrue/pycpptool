import unittest
import tempfile
import os
import sys
import pathlib
import contextlib

HERE = pathlib.Path(__file__).absolute().parent
# print(HERE.parent)
sys.path.insert(0, str(HERE.parent))

IMGUI_H = HERE.parent / 'libs/imgui/imgui.h'

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


class StructDecl:
    def __init__(self, name, *fields):
        self.name = name
        self.fields = fields

    def __eq__(self, rhs) -> bool:
        return (self.name == rhs.name and len(self.fields) == len(rhs.fields))

    def __repr__(self) -> str:
        return f'struct {self.name}{{}}'

    @classmethod
    def parse(cls, c: cindex.Cursor) -> 'StructDecl':
        fields = []
        for child in c.get_children():
            fields.append(child)
        # if len(fields) == 0. forward decl
        return StructDecl(c.spelling, *fields)


class TypedefDecl:
    def __init__(self, name: str, src: str):
        self.name = name
        self.src = src

    def __repr__(self) -> str:
        return f'typedef {self.name} = {self.src}'

    @classmethod
    def parse(cls, c: cindex.Cursor) -> 'TypedefDecl':
        children = [child for child in c.get_children()]
        assert (len(children) == 0)
        # tokens = [token.spelling for token in c.get_tokens()]
        return TypedefDecl(c.spelling, c.underlying_typedef_type)


EXPECTS = {
    'ImDrawChannel': StructDecl('ImDrawChannel'),
    'ImDrawCmd': StructDecl('ImDrawCmd'),
    'ImDrawData': StructDecl('ImDrawData'),
    'ImDrawList': StructDecl('ImDrawList'),
    'ImDrawListSharedData': StructDecl('ImDrawListSharedData'),
    'ImDrawListSplitter': StructDecl('ImDrawListSplitter'),
    'ImDrawVert': StructDecl('ImDrawVert'),
    'ImFont': StructDecl('ImFont'),
    'ImFontAtlas': StructDecl('ImFontAtlas'),
    'ImFontConfig': StructDecl('ImFontConfig'),
    'ImFontGlyph': StructDecl('ImFontGlyph'),
    'ImFontGlyphRangesBuilder': StructDecl('ImFontGlyphRangesBuilder'),
    'ImColor': StructDecl('ImColor'),
    'ImGuiContext': StructDecl('ImGuiContext'),
    'ImGuiIO': StructDecl('ImGuiIO'),
    'ImGuiInputTextCallbackData': StructDecl('ImGuiInputTextCallbackData'),
    'ImGuiListClipper': StructDecl('ImGuiListClipper'),
    'ImGuiOnceUponAFrame': StructDecl('ImGuiOnceUponAFrame'),
    'ImGuiPayload': StructDecl('ImGuiPayload'),
    'ImGuiSizeCallbackData': StructDecl('ImGuiSizeCallbackData'),
    'ImGuiStorage': StructDecl('ImGuiStorage'),
    'ImGuiStyle': StructDecl('ImGuiStyle'),
    'ImGuiTextBuffer': StructDecl('ImGuiTextBuffer'),
    'ImGuiTextFilter': StructDecl('ImGuiTextFilter'),
}


def parse(c: cindex.Cursor):
    if c.kind == cindex.CursorKind.UNEXPOSED_DECL:
        tokens = [t.spelling for t in c.get_tokens()]
    elif c.kind == cindex.CursorKind.STRUCT_DECL:
        return StructDecl.parse(c)
    elif c.kind == cindex.CursorKind.TYPEDEF_DECL:
        return TypedefDecl.parse(c)
    else:
        print(c.kind)


class ImGuiTest(unittest.TestCase):
    def test_int(self) -> None:
        tu = get_tu(IMGUI_H)
        self.assertIsInstance(tu, cindex.TranslationUnit)

        # TRANSLATION_UNIT
        c: cindex.Cursor = tu.cursor
        self.assertIsInstance(c, cindex.Cursor)
        self.assertEqual(cindex.CursorKind.TRANSLATION_UNIT, c.kind)
        self.assertIsNone(c.location.file)

        count = 0
        for i, c in enumerate(c.get_children()):
            if c.location.file.name != str(IMGUI_H):
                continue
            count += 1
            with self.subTest(i=i, spelling=c.spelling):
                self.assertEqual(EXPECTS.get(c.spelling), parse(c))
            if count > len(EXPECTS):
                break


if __name__ == '__main__':
    unittest.main()
