import pathlib
import uuid
import io
from typing import Optional, List, NamedTuple, TextIO, Dict
from clang import cindex
from . import cdeclare

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


class Node:
    def __init__(self, path: pathlib.Path, c: cindex.Cursor) -> None:
        self.name = c.spelling
        self.path = path
        self.hash = c.hash
        self.is_forward = False
        self.value = f'{c.kind}: {c.spelling}'
        self.typedef_list: List[Node] = []

        self.canonical: Optional[int] = None
        if c.hash != c.canonical.hash:
            self.canonical = c.canonical.hash

    def __str__(self) -> str:
        return self.value


class MethodParam(NamedTuple):
    param_name: str
    param_type: cdeclare.Declare

    def __str__(self) -> str:
        return f'{self.param_name}: {self.param_type}'


class FunctionNode(Node):
    def __init__(self, path: pathlib.Path, c: cindex.Cursor) -> None:
        super().__init__(path, c)
        self.ret = cdeclare.Void()
        self.params: List[MethodParam] = []
        self.has_body = False
        for child in c.get_children():
            if child.kind == cindex.CursorKind.TYPE_REF:
                self.ret = cdeclare.parse_declare(child.spelling)
            elif child.kind == cindex.CursorKind.PARM_DECL:
                declare = cdeclare.parse_declare(child.type.spelling)
                param = MethodParam(child.spelling, declare)
                self.params.append(param)
            elif child.kind == cindex.CursorKind.COMPOUND_STMT:
                # function body
                self.has_body = True
            elif child.kind == cindex.CursorKind.UNEXPOSED_ATTR:
                # tokens = [t.spelling for t in child.get_tokens()]
                # print(tokens)
                # raise(Exception(child.kind))
                pass
            else:
                raise (Exception(child.kind))

    def __str__(self) -> str:
        return f'{self.name}({", ".join(str(p) for p in self.params)})->{self.ret};'


class StructNode(Node):
    '''
    struct or struct field. can nested.

    field_type: struct, union, int, char, int[] etc...
    '''

    def __init__(self, path: pathlib.Path, c: cindex.Cursor,
                 is_root=True) -> None:
        super().__init__(path, c)
        self.field_type = 'struct'
        if c.kind == cindex.CursorKind.UNION_DECL:
            self.field_type = 'union'
        self.fields: List['StructNode'] = []
        self.iid: Optional[uuid.UUID] = None
        self.base = ''
        self.methods: List[FunctionNode] = []
        if is_root:
            self._parse(c)

    def _parse(self, c: cindex.Cursor) -> None:
        for child in c.get_children():
            if child.kind == cindex.CursorKind.FIELD_DECL:
                field = StructNode(self.path, child, False)
                if child.type == cindex.TypeKind.TYPEDEF:
                    field_type = cdeclare.parse_declare(
                        get_typedef_type(child).spelling)
                else:
                    field_type = cdeclare.parse_declare(child.type.spelling)
                field.field_type = field_type
                self.fields.append(field)
            elif child.kind == cindex.CursorKind.STRUCT_DECL:
                struct = StructNode(self.path, child)
                struct.field_type = 'struct'
                self.fields.append(struct)
            elif child.kind == cindex.CursorKind.UNION_DECL:
                union = StructNode(self.path, child)
                union.field_type = 'union'
                self.fields.append(union)
            elif child.kind == cindex.CursorKind.UNEXPOSED_ATTR:
                value = extract(child)
                d3d11_key = 'MIDL_INTERFACE("'
                d2d1_key = 'DX_DECLARE_INTERFACE("'
                if value.startswith(d3d11_key):
                    self.iid = uuid.UUID(value[len(d3d11_key):-2])
                elif value.startswith(d2d1_key):
                    self.iid = uuid.UUID(value[len(d2d1_key):-2])
                else:
                    print(value)
            elif child.kind == cindex.CursorKind.CXX_BASE_SPECIFIER:
                if child.type == cindex.TypeKind.TYPEDEF:
                    self.base = get_typedef_type(child).spelling
                else:
                    self.base = child.type.spelling
            elif child.kind == cindex.CursorKind.CXX_METHOD:
                method = FunctionNode(self.path, child)
                if not method.has_body:
                    self.methods.append(method)
            elif child.kind == cindex.CursorKind.CONSTRUCTOR:
                pass
            elif child.kind == cindex.CursorKind.DESTRUCTOR:
                pass
            elif child.kind == cindex.CursorKind.CONVERSION_FUNCTION:
                pass
            elif child.kind == cindex.CursorKind.CXX_ACCESS_SPEC_DECL:
                pass
            else:
                raise Exception(child.kind)

    def __str__(self) -> str:
        with io.StringIO() as f:
            self._write_to(f)
            return f.getvalue()

    def _write_to(self, f: TextIO, indent='') -> None:
        if self.field_type in ['struct', 'union']:
            if self.base:
                name = f'{self.name}: {self.base}'
            else:
                name = self.name

            if self.iid:
                f.write(f'{indent}interface {name}[{self.iid}]{{\n')
            else:
                f.write(f'{indent}{self.field_type} {name}{{\n')

            child_indent = indent + '  '
            for field in self.fields:
                field._write_to(f, child_indent)
                f.write('\n')

            for method in self.methods:
                f.write(f'{child_indent}{method}\n')

            f.write(indent + '}')

        else:
            field_type = self.field_type
            f.write(f'{indent}{field_type} {self.name};')


class EnumValue(NamedTuple):
    name: str
    value: int


class EnumNode(Node):
    def __init__(self, path: pathlib.Path, c: cindex.Cursor) -> None:
        super().__init__(path, c)
        self.values: List[EnumValue] = []
        for child in c.get_children():
            if child.kind == cindex.CursorKind.ENUM_CONSTANT_DECL:
                self.values.append(EnumValue(child.spelling, child.enum_value))
            else:
                raise Exception(child.kind)

    def __str__(self) -> str:
        with io.StringIO() as f:
            f.write(f'enum {self.name} {{\n')
            for value in self.values:
                f.write(f'    {value.name} = {value.value:#010x}\n')
            f.write(f'}}')
            return f.getvalue()


def get_typedef_type(c: cindex.Cursor) -> cindex.Cursor:
    if c.type.kind != cindex.TypeKind.TYPEDEF:
        raise Exception('not TYPEDEF')
    children = [child for child in c.get_children()]
    if not children:
        return None
    if len(children) != 1:
        # tokens = [t.spelling for t in c.get_tokens()]
        # print(tokens)
        return None
        # raise Exception('not 1')
    typeref = children[0]
    if typeref.kind not in [
            cindex.CursorKind.TYPE_REF,
            cindex.CursorKind.STRUCT_DECL,  # maybe forward decl
            cindex.CursorKind.UNION_DECL,
            cindex.CursorKind.ENUM_DECL,
            cindex.CursorKind.TYPE_REF,
            cindex.CursorKind.PARM_DECL,
    ]:
        raise Exception(f'not TYPE_REF: {typeref.kind}')
    return typeref


class TypedefNode(Node):
    def __init__(self, path: pathlib.Path, c: cindex.Cursor) -> None:
        super().__init__(path, c)
        typedef_type = get_typedef_type(c)
        if typedef_type:
            self.typedef_type = cdeclare.parse_declare(typedef_type.spelling)
        else:
            tokens = [t.spelling for t in c.get_tokens()]
            # print(tokens)
            if len(tokens) == 3:
                self.typedef_type = cdeclare.parse_declare(tokens[1])
                # raise Exception()
            else:
                self.typedef_type = None

    def is_valid(self) -> bool:
        if not self.typedef_type:
            return False
        if self.name == self.typedef_type.type:
            return False
        if isinstance(self.typedef_type,
                      cdeclare.BaseType) and self.typedef_type.struct:
            return False
        return True

    def __str__(self) -> str:
        return f'{self.name} = {self.typedef_type}'
