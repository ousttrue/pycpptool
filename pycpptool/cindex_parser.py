import uuid
import pathlib
import platform
import io
from typing import NamedTuple, TextIO, Set, Optional, List, Dict
from clang import cindex
from .cindex_node import *


def normalize(src: str) -> str:
    if platform.system() == 'Windows':
        return src.lower()
    return src


class MacroDefinition(NamedTuple):
    name: str
    value: str


class Header:
    def __init__(self, path: pathlib.Path, hash: int) -> None:
        self.path = path
        self.hash = hash
        self.includes: List[Header] = []
        self.nodes: List[Node] = []
        self.name = normalize(self.path.name)
        self.macro_defnitions: List[MacroDefinition] = []

    def __str__(self) -> str:
        return f'<Header: {self.hash}: {self.path}>'

    def print_nodes(self, used: Set[pathlib.Path] = None) -> None:
        if not used:
            used = set()
        if self.path in used:
            return
        used.add(self.path)

        for include in self.includes:
            include.print_nodes(used)

        print(f'#### {self.path} ####')
        for node in self.nodes:
            if node.is_forward:
                continue
            print(f'{node}')
        print()


def get_node(current: pathlib.Path, c: cindex.Cursor) -> Optional[Node]:
    if (c.kind == cindex.CursorKind.STRUCT_DECL
            or c.kind == cindex.CursorKind.UNION_DECL):
        struct = StructNode(current, c)
        return struct
    if c.kind == cindex.CursorKind.ENUM_DECL:
        return EnumNode(current, c)
    if c.kind == cindex.CursorKind.FUNCTION_DECL:
        if c.spelling.startswith('operator'):
            return None
        try:
            return FunctionNode(current, c)
        except Exception as ex:
            print(ex)
            return None
    if c.kind == cindex.CursorKind.TYPEDEF_DECL:
        node = TypedefNode(current, c)
        if not node.is_valid():
            return None
        return node

    raise Exception(f'unknown: {c.kind}')
    #return Node(current, c)


def parse(tu: cindex.TranslationUnit,
          include: List[str] = None) -> Dict[str, Header]:
    if include is None:
        include = []

    path_map: Dict[pathlib.Path, Header] = {}

    def get_or_create_header(c) -> Header:
        path = pathlib.Path(c.location.file.name).resolve()
        header = path_map.get(path)
        if not header:
            header = Header(path, c.hash)
            path_map[path] = header
        return header

    used: Dict[int, Node] = {}

    kinds = [
        cindex.CursorKind.UNEXPOSED_DECL,
        cindex.CursorKind.STRUCT_DECL,
        cindex.CursorKind.UNION_DECL,
        cindex.CursorKind.ENUM_DECL,
        cindex.CursorKind.FUNCTION_DECL,
        cindex.CursorKind.TYPEDEF_DECL,
    ]

    def traverse(c: cindex.Cursor) -> None:
        if not c.location.file:
            return

        current = get_or_create_header(c)
        if current.name in include:
            pass
        else:
            return

        if c.hash in used:
            # already processed
            return

        if c.kind not in kinds:
            # skip
            return

        if c.kind == cindex.CursorKind.UNEXPOSED_DECL:
            for child in c.get_children():
                traverse(child)
            return

        node = get_node(current, c)
        if not node:
            return

        used[c.hash] = node
        current.nodes.append(node)

    # parse
    for c in tu.cursor.get_children():
        traverse(c)

    # modify
    for _, v in used.items():
        if v.canonical and v.canonical in used:
            # mark forward declaration
            used[v.canonical].is_forward = True

    return path_map


def parse_macro(path_map: Dict[pathlib.Path, Header],
                tu: cindex.TranslationUnit, include: List[str]) -> None:

    name_map = {
        normalize(pathlib.Path(k).name): v
        for k, v in path_map.items()
    }

    name_map = {k: v for k, v in name_map.items() if k in include}

    kinds = [
        cindex.CursorKind.UNEXPOSED_DECL,
        cindex.CursorKind.INCLUSION_DIRECTIVE,
        cindex.CursorKind.MACRO_DEFINITION,
        #cindex.CursorKind.MACRO_INSTANTIATION,
    ]

    def get_or_create_header(c) -> Header:
        path = pathlib.Path(c.location.file.name).resolve()
        header = path_map.get(path)
        if not header:
            header = Header(path, c.hash)
            path_map[path] = header
        return header

    def traverse(c: cindex.Cursor) -> None:
        if not c.location.file:
            return

        current = get_or_create_header(c)
        if not current:
            return

        if current.name in include:
            pass
        else:
            return

        if c.kind not in kinds:
            # skip
            return

        if c.kind == cindex.CursorKind.UNEXPOSED_DECL:
            tokens = [t for t in c.get_tokens()]
            if tokens and tokens[0].spelling == 'extern':
                for child in c.get_children():
                    traverse(child)
            return

        if c.kind == cindex.CursorKind.INCLUSION_DIRECTIVE:
            tokens = [t.spelling for t in c.get_tokens()]
            if '<' in tokens:
                carret = tokens.index('<')
                header_name = ''.join(tokens[carret + 1:-1])
            else:
                header_name = tokens[-1][1:-1]

            header_name = normalize(header_name)

            included_header = name_map.get(header_name)
            if included_header:
                current.includes.append(included_header)
            return

        if c.kind == cindex.CursorKind.MACRO_DEFINITION:
            tokens = [t.spelling for t in c.get_tokens()]
            if len(tokens) == 1:
                # ex. #define __header__
                return

            if tokens in [
                ['IID_ID3DBlob', 'IID_ID3D10Blob'],
                ['INTERFACE', 'ID3DInclude'],
                ['D2D1_INVALID_TAG', 'ULONGLONG_MAX'],
                ['D2D1FORCEINLINE', 'FORCEINLINE'],
            ]:
                #define IID_ID3DBlob IID_ID3D10Blob
                #define INTERFACE ID3DInclude
                #define D2D1_INVALID_TAG ULONGLONG_MAX
                #define D2D1FORCEINLINE FORCEINLINE
                return

            if len(tokens) >= 3 and tokens[1] == '(' and tokens[2][0].isalpha(
            ):
                # maybe macro function
                return

            return current.macro_defnitions.append(
                MacroDefinition(c.spelling, ' '.join(x for x in tokens[1:])))

    # parse
    for c in tu.cursor.get_children():
        traverse(c)
