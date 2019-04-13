import sys
import os
import platform
import pathlib
import uuid
import io
from typing import Dict, List, Optional, Any, Set, Tuple, TextIO, Iterable
from jinja2 import Template
from clang import cindex


HERE = pathlib.Path(__file__).absolute().parent

DEFAULT_CLANG_DLL = pathlib.Path(
    "C:/Program Files (x86)/LLVM/bin/libclang.dll")


def get_tu(path: pathlib.Path,
           dll: Optional[pathlib.Path] = None) -> cindex.TranslationUnit:
    '''
    parse cpp source
    '''
    if not path.exists():
        raise FileNotFoundError(str(path))

    if not dll and DEFAULT_CLANG_DLL.exists():
        dll = DEFAULT_CLANG_DLL
    if dll:
        cindex.Config.set_library_file(str(dll))

    index = cindex.Index.create()
    return index.parse(
        str(path),
        ['-x', 'c++']
        # , options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD
    )


extract_bytes_cache: Dict[pathlib.Path, bytes] = {}


def extract(x: cindex.Cursor) -> str:
    '''
    get str for cursor
    '''
    start = x.extent.start
    p = pathlib.Path(start.file.name)
    b = extract_bytes_cache.get(p)
    if not b:
        b = p.read_bytes()
        extract_bytes_cache[p] = b

    end = x.extent.end
    text = b[start.offset:end.offset]
    return text.decode('ascii')


def get_token(cursor: cindex.Cursor) -> int:
    if cursor.kind != cindex.CursorKind.INTEGER_LITERAL:
        raise Exception('not int')
    tokens = [x.spelling for x in cursor.get_tokens()]
    if len(tokens) != 1:
        raise Exception('not 1')
    return int(tokens[0])


def get_typeref(cursor: cindex.Cursor) -> Tuple[cindex.Cursor, List[cindex.Cursor]]:
    children = [child for child in cursor.get_children()]
    if children[0].kind != cindex.CursorKind.TYPE_REF:
        raise Exception("not TYPE_REF")
    if len(children) == 1:
        return (children[0], [])
    elif len(children) >= 2:
        return (children[0], [get_token(x) for x in children[1:]])
    else:
        raise Exception("no children")


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

##############################################################################


class Node:
    def __init__(self, path: pathlib.Path, c: cindex.Cursor) -> None:
        self.path = path
        self.hash = c.hash
        self.type_reference: Optional[int] = None
        self.is_typedef = False
        self.canonical: Optional[int] = None
        self.is_forward = False
        self.value = ''
        self.typedef_list: List[Node] = []

    def __str__(self) -> str:
        return self.value


class StructMethod:
    def __init__(self, name) -> None:
        self.name = name

    def __str__(self) -> str:
        return f'{self.name}();'


class StructField:
    def __init__(self, field_name: str, field_type='') -> None:
        self.field_name = field_name
        self.field_type = field_type
        self.fields: List[StructField] = []
        self.iid: Optional[uuid.UUID] = None
        self.base = ''
        self.methods: List[StructMethod] = []

    def __str__(self) -> str:
        with io.StringIO() as f:
            self.write_to(f)
            return f.getvalue()

    def write_to(self, f: TextIO, indent='') -> None:
        if self.field_type in ['struct', 'union']:
            if self.base:
                name = f'{self.field_name}: {self.base}'
            else:
                name = self.field_name

            if self.iid:
                f.write(f'{indent}interface {name}[{self.iid}]{{\n')
            else:
                f.write(f'{indent}{self.field_type} {name}{{\n')

            child_indent = indent + '  '
            for field in self.fields:
                field.write_to(f, child_indent)
                f.write('\n')

            for method in self.methods:
                f.write(f'{child_indent}{method}\n')

            f.write(f'{indent}}}')

        else:
            f.write(f'{indent}{self.field_type} {self.field_name};')

    def parse(self, c: cindex.Cursor) -> None:
        for child in c.get_children():
            if child.kind == cindex.CursorKind.FIELD_DECL:
                typeref, literal = get_typeref(child)
                field = StructField(
                    child.spelling, typeref.spelling + ''.join(f'[{n}]' for n in literal))
                self.fields.append(field)
            elif child.kind == cindex.CursorKind.STRUCT_DECL:
                union = StructField(child.spelling, 'struct')
                union.parse(child)
                self.fields.append(union)
            elif child.kind == cindex.CursorKind.UNION_DECL:
                union = StructField(child.spelling, 'union')
                union.parse(child)
                self.fields.append(union)
            elif child.kind == cindex.CursorKind.UNEXPOSED_ATTR:
                value = extract(child)
                if value.startswith('MIDL_INTERFACE("'):
                    self.iid = uuid.UUID(value[16:-2])
            elif child.kind == cindex.CursorKind.CXX_BASE_SPECIFIER:
                typeref, literal = get_typeref(child)
                if literal:
                    raise Exception()
                self.base = typeref.referenced.spelling
            elif child.kind == cindex.CursorKind.CXX_METHOD:
                self.methods.append(StructMethod(child.spelling))
            elif child.kind == cindex.CursorKind.CXX_ACCESS_SPEC_DECL:
                pass
            else:
                raise Exception(child.kind)


class StructNode(Node):
    def __init__(self, path: pathlib.Path, c: cindex.Cursor) -> None:
        self.root = StructField(c.spelling, 'struct')
        self.root.parse(c)
        super().__init__(path, c)

    def __str__(self) -> str:
        return f'{self.root}'


def parse(ins: TextIO, path: pathlib.Path) -> None:
    tu = get_tu(path)

    path_map: Dict[str, pathlib.Path] = {}

    used: Dict[int, Node] = {}

    def traverse(c: cindex.Cursor, level=0) -> None:
        if not c.location.file:
            return

        current = path_map.get(c.location.file.name)
        if not current:
            current = pathlib.Path(c.location.file.name)
            path_map[c.location.file.name] = current
            # print(path)
        if current != path:
            return

        if c.hash in used:
            # already processed
            return

        if c.kind in [
            cindex.CursorKind.TYPEDEF_DECL,
            cindex.CursorKind.VAR_DECL,
            cindex.CursorKind.FUNCTION_TEMPLATE,
            cindex.CursorKind.CLASS_TEMPLATE,
            cindex.CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION,
            cindex.CursorKind.CLASS_DECL,
        ]:
            # skip
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

        if c.kind == cindex.CursorKind.STRUCT_DECL:
            node = StructNode(current, c)
        else:
            node = Node(current, c)
        if c.hash != c.canonical.hash:
            node.canonical = c.canonical.hash
        if c.referenced and c.hash != c.referenced.hash:
            node.type_reference = c.referenced.hash

        used[c.hash] = node

        node.value = f'{c.hash:#010x}: {"  "*level}{c.kind}: {value}'

        if c.kind not in [
            cindex.CursorKind.STRUCT_DECL,
            cindex.CursorKind.UNION_DECL,
            cindex.CursorKind.ENUM_DECL,
            cindex.CursorKind.FUNCTION_DECL,
        ]:
            raise Exception(f'unknown kind: {c.kind}')

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
    parse(sys.stdout, path)

    # parser.add_include_header(path)
    # parser.parse(path)


if __name__ == '__main__':
    main()
