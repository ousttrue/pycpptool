import sys
import os
import platform
import pathlib
import uuid
from typing import Dict, List, Optional, Any, Set, Tuple, TextIO
from jinja2 import Template
from clang import cindex


HERE = pathlib.Path(__file__).absolute().parent

DEFAULT_CLANG_DLL = pathlib.Path(
    "C:/Program Files (x86)/LLVM/bin/libclang.dll")

extract_cache_map: Dict[pathlib.Path, bytes] = {}


def extract(x: cindex.Cursor) -> str:
    start = x.extent.start
    p = pathlib.Path(start.file.name)
    b = extract_cache_map.get(p)
    if not b:
        b = p.read_bytes()
        extract_cache_map[p] = b

    end = x.extent.end
    text = b[start.offset:end.offset]
    return text.decode('ascii')


class ItemBase:
    def __init__(self, name: str) -> None:
        self.name = name

    def __str__(self) -> str:
        return f'{self.__class__}: {self.name}'


class Item_TypeDef(ItemBase):
    def __init__(self, name: str, value: Any) -> None:
        super().__init__(name)
        self.value = value

    def __str__(self) -> str:
        return f'typedef {self.name} = {self.value}'


class Item_Field(ItemBase):
    def __init__(self, name: str, field_type: Any) -> None:
        super().__init__(name)
        self.type = field_type

    def __str__(self) -> str:
        return str(self.type)


class Item_Struct(ItemBase):
    def __init__(self, tag: str) -> None:
        super().__init__(tag)
        self.fields: List[Item_Field] = []
        self.struct = 'struct'
        self.iid: Optional[uuid.UUID] = None

    def __str__(self) -> str:
        template = Template('''{{ struct }} {{ tag }} {
{% for f in values -%}
    {{ f.type }} {{ f.name }};
{% endfor -%}
}
''')

        return template.render(struct=self.struct,
                               tag=self.name,
                               values=self.fields)


class Item_Union(Item_Struct):
    def __init__(self, tag: str) -> None:
        super().__init__(tag)
        self.struct = 'union'


class Item_MacroDefine(ItemBase):
    def __init__(self, name: str, value: str) -> None:
        super().__init__(name)
        self.value = value

    def __str__(self) -> str:
        return f'#define {self.name} = {self.value}'


class Item_ComIID(ItemBase):
    def __init__(self, iid: uuid.UUID) -> None:
        super().__init__(str(iid))
        self.iid = iid


class Item_Include(ItemBase):
    def __init__(self, include: str) -> None:
        super().__init__('#include')
        self.include = include

    def __str__(self) -> str:
        return f'#include {self.include}'


class ParsedItem:
    def __init__(self, key: int, path: str, line: int) -> None:
        if platform.system() == 'Windows':
            path = path.lower()

        self.key = key
        self.path = path
        self.filename = os.path.basename(self.path)
        self.line = line
        self.content: Optional[ItemBase] = None

    def __str__(self) -> str:
        if self.content:
            return f'{self.key}: {self.filename}:{self.line}: {self.content}'
        else:
            return f'{self.key}: {self.filename}:{self.line}'


class Parser:
    def __init__(self, dll: pathlib.Path = None) -> None:
        if not dll:
            if platform.architecture()[0] == '32bit':
                dll = DEFAULT_CLANG_DLL
        self.dll = dll
        self.item_map: Dict[int, ParsedItem] = {}
        self.parsed_items: List[ParsedItem] = []
        self.include_headers: Set[str] = set()

    def add_include_header(self, path: pathlib.Path) -> None:
        name = path.name
        if platform.system() == 'Windows':
            name = name.lower()
        self.include_headers.add(name)

    def _is_target(self, file: str) -> bool:
        name = pathlib.Path(file).name
        if platform.system() == 'Windows':
            name = name.lower()
        return name in self.include_headers

    def _process_item(self,
                      cursor) -> Tuple[bool, Optional[ItemBase]]:
        tokens = [x.spelling for x in cursor.get_tokens()]
        if cursor.kind == cindex.CursorKind.INCLUSION_DIRECTIVE:
            if '<' in tokens:
                open = tokens.index('<')
                return False, Item_Include(''.join(tokens[open+1:-1]))
            else:
                return False, Item_Include(tokens[-1][1:-1])

        elif cursor.kind == cindex.CursorKind.MACRO_DEFINITION:
            if len(tokens) == 1:
                # ex. #define __header__
                return False, None
            else:
                return False, Item_MacroDefine(
                    cursor.spelling, ' '.join(x for x in tokens[1:]))

        elif cursor.kind == cindex.CursorKind.MACRO_INSTANTIATION:
            if tokens[0] == 'MIDL_INTERFACE':
                # return True, Item_ComIID(uuid.UUID(tokens[2][1:-1]))
                return False, None
            if len(tokens) == 1:
                return False, None
            # print(tokens)
            # sys.exit(1)
            return False, None

        elif cursor.kind == cindex.CursorKind.TYPEDEF_DECL:
            if len(tokens) == 3:
                # ex. typedef float FLOAT
                return False, Item_TypeDef(tokens[2], tokens[1])
            elif len(tokens) < 3:
                raise Exception(str(tokens))
            else:
                children = [x for x in cursor.get_children()]
                count = len(children)
                if count != 1:
                    raise Exception(str(children))
                if children[0].kind == cindex.CursorKind.TYPE_REF:
                    return False, Item_TypeDef(
                        tokens[-1], children[0].referenced.hash)
                elif children[0].kind in [
                    cindex.CursorKind.STRUCT_DECL,
                    cindex.CursorKind.ENUM_DECL,
                ]:
                    return False, Item_TypeDef(
                        tokens[-1], children[0].hash)
                else:
                    print(children[0].kind)
                    raise Exception(str(children))

        elif cursor.kind == cindex.CursorKind.STRUCT_DECL:
            return False, self._process_struct(cursor)

        elif cursor.kind == cindex.CursorKind.ENUM_DECL:
            # todo
            return False, None

        elif cursor.kind == cindex.CursorKind.FUNCTION_DECL:
            # todo
            return False, None

        elif cursor.kind == cindex.CursorKind.VAR_DECL:
            if tokens[0] == 'extern':
                return False, None
            print(cursor.kind, tokens)
            sys.exit(1)
            return False, None

        elif cursor.kind == cindex.CursorKind.UNEXPOSED_DECL:
            if not tokens:
                return False, None
            if tokens[0] == 'extern':
                return True, None
            print(cursor.kind, tokens)
            sys.exit(1)
            return False, None

        print(cursor.kind, tokens)
        sys.exit(1)
        return False, None

    def _process_struct(self,
                        cursor: cindex.Cursor,
                        level=0) -> Item_Struct:
        if cursor.kind == cindex.CursorKind.STRUCT_DECL:
            struct = Item_Struct(cursor.spelling)
        elif cursor.kind == cindex.CursorKind.UNION_DECL:
            struct = Item_Union(cursor.spelling)
        else:
            print(cursor.kind)
            raise Exception()

        # fields
        for f in cursor.get_children():
            # tokens = [x for x in f.get_tokens()]
            field = None
            if (f.kind == cindex.CursorKind.UNION_DECL
                    or f.kind == cindex.CursorKind.STRUCT_DECL):
                field = Item_Field(
                    f.spelling, self._process_struct(f, level+1))
            elif f.kind == cindex.CursorKind.FIELD_DECL:
                field = Item_Field(f.spelling, f.type.spelling)
            elif f.kind == cindex.CursorKind.UNEXPOSED_ATTR:
                attr = extract(f)
                if attr.startswith('MIDL_INTERFACE("'):
                    struct.iid = uuid.UUID(attr[16:-2])
                    struct.struct = 'interface'
            elif f.kind == cindex.CursorKind.CXX_BASE_SPECIFIER:
                # todo
                continue
            elif f.kind == cindex.CursorKind.CXX_ACCESS_SPEC_DECL:
                continue
            elif f.kind == cindex.CursorKind.CXX_METHOD:
                # todo
                continue
            else:
                print(f.kind)
                raise Exception()

            if field:
                struct.fields.append(field)
        return struct

    def _traverse(self,
                  cursor: cindex.Cursor,
                  level: int = 0) -> Optional[ParsedItem]:
        used = self.item_map.get(cursor.hash)
        if used:
            # already processed. skip
            return used

        if not cursor.location.file:
            # skip
            return None

        if not self._is_target(cursor.location.file.name):
            # skip
            return None

        # new item
        item = ParsedItem(
            cursor.hash, cursor.location.file.name, cursor.location.line)
        self.item_map[cursor.hash] = item
        self.parsed_items.append(item)

        # process
        next_child, content = self._process_item(cursor)
        if content:
            item.content = content
            if isinstance(item.content, (Item_Include, Item_MacroDefine)):
                pass
            else:
                print(f'{"  "*level}{item}')

        if next_child:
            for child in cursor.get_children():
                self._traverse(child, level+1)

        return item

    def get_tu(self, path: pathlib.Path) -> cindex.TranslationUnit:
        if not path.exists():
            raise FileNotFoundError(str(path))

        if self.dll:
            cindex.Config.set_library_file(str(self.dll))
        index = cindex.Index.create()
        return index.parse(
            str(path),
            ['-x', 'c++']
            # , options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
        )


class Node:
    def __init__(self, path: pathlib.Path, hash: int) -> None:
        self.path = path
        self.hash = hash
        self.type_reference: Optional[int] = None
        self.is_typedef = False
        self.canonical: Optional[int] = None
        self.is_forward = False
        self.value = ''
        self.typedef_list: List[Node] = []

    def __str__(self) -> str:
        return self.value


def show(ins: TextIO, path: pathlib.Path) -> None:
    parser = Parser()
    tu = parser.get_tu(path)

    path_map: Dict[str, pathlib.Path] = {}

    used: Dict[int, Node] = {}

    def traverse(c: cindex.Cursor, level=0) -> None:
        if not c.location.file:
            return

        path = path_map.get(c.location.file.name)
        if not path:
            path = pathlib.Path(c.location.file.name)
            path_map[c.location.file.name] = path
            # print(path)
        if path.name == 'winnt.h':  # very long
            return

        if c.hash in used:
            return

        if c.kind == cindex.CursorKind.TYPEDEF_DECL:
            return
        if c.kind == cindex.CursorKind.VAR_DECL:
            return
        if c.kind == cindex.CursorKind.FUNCTION_TEMPLATE:
            return
        if c.kind == cindex.CursorKind.UNEXPOSED_DECL:
            tokens = [t for t in c.get_tokens()]
            if tokens and tokens[0].spelling == 'extern':
                for child in c.get_children():
                    traverse(child, level)
            return

        value = c.spelling
        if not value:
            tokens = [t for t in c.get_tokens()]
            if tokens:
                value = tokens[0].spelling
        if not value:
            value = extract(c)

        node = Node(path, c.hash)
        if c.hash != c.canonical.hash:
            node.canonical = c.canonical.hash
        if c.referenced and c.hash != c.referenced.hash:
            node.type_reference = c.referenced.hash

        used[c.hash] = node

        node.value = f'{c.hash:#010x}: {"  "*level}{c.kind}: {value}'

        if c.kind in [
            cindex.CursorKind.STRUCT_DECL,
            cindex.CursorKind.UNION_DECL,
            cindex.CursorKind.ENUM_DECL,
            cindex.CursorKind.FUNCTION_DECL,
        ]:
            pass
        else:
            for child in c.get_children():
                traverse(child, level+1)

    for c in tu.cursor.get_children():
        traverse(c)

    for k, v in used.items():
        if v.canonical and v.canonical in used:
            used[v.canonical].is_forward = True

    for k, v in used.items():
        if v.path != path:
            continue
        if v.is_forward:
            continue
        if v.is_typedef:
            continue
        print(v)


def main() -> None:
    path = HERE / sys.argv[1]
    show(sys.stdout, path)

    # parser.add_include_header(path)
    # parser.parse(path)


if __name__ == '__main__':
    main()
