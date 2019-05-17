import uuid
import pathlib
import platform
import io
from typing import NamedTuple, TextIO, Set, Optional, List, Dict
from clang import cindex

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
    param_type: str

    def __str__(self) -> str:
        return f'{self.param_name}: {self.param_type}'


class FunctionNode(Node):
    def __init__(self, path: pathlib.Path, c: cindex.Cursor) -> None:
        super().__init__(path, c)
        self.ret = ''
        self.params: List[MethodParam] = []
        self.has_body = False
        for child in c.get_children():
            if child.kind == cindex.CursorKind.TYPE_REF:
                if self.ret:
                    raise Exception('dup ret')
                self.ret = child.spelling
            elif child.kind == cindex.CursorKind.PARM_DECL:
                param = MethodParam(child.spelling, child.type.spelling)
                self.params.append(param)
            elif child.kind == cindex.CursorKind.COMPOUND_STMT:
                # function body
                self.has_body = True
            elif child.kind == cindex.CursorKind.UNEXPOSED_ATTR:
                #tokens = [t.spelling for t in child.get_tokens()]
                #print(tokens)
                #raise(Exception(child.kind))
                pass
            else:
                raise (Exception(child.kind))

    def __str__(self) -> str:
        return f'{self.name}({", ".join(str(p) for p in self.params)})->{self.ret};'


class StructNode(Node):
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
                    field.field_type = get_typedef_type(child).spelling
                else:
                    field.field_type = child.type.spelling
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
            if field_type.startswith('struct '):
                field_type = field_type[7:]
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
        #tokens = [t.spelling for t in c.get_tokens()]
        #print(tokens)
        return None
        #raise Exception('not 1')
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
            self.typedef_type = typedef_type.spelling
        else:
            tokens = [t.spelling for t in c.get_tokens()]
            #print(tokens)
            if len(tokens) == 3:
                self.typedef_type = tokens[1]
                #raise Exception()
            else:
                self.typedef_type = None

    def is_valid(self) -> bool:
        if not self.typedef_type:
            return False
        if self.name == self.typedef_type:
            return False
        if 'struct ' + self.name == self.typedef_type:
            return False
        return True

    def __str__(self) -> str:
        return f'{self.name} = {self.typedef_type}'


def normalize(src: str) -> str:
    if platform.system() == 'Windows':
        return src.lower()
    return src


class MacroDefinition(NamedTuple):
    name: str
    value: str


class Header(Node):
    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.includes: List[Header] = []
        self.nodes: List[Node] = []
        self.name = normalize(self.path.name)
        self.macro_defnitions: List[MacroDefinition] = []

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
        except:
            return None
    if c.kind == cindex.CursorKind.TYPEDEF_DECL:
        node = TypedefNode(current, c)
        if not node.is_valid():
            return None
        return node

    raise Exception(f'unknown: {c.kind}')
    #return Node(current, c)


def parse(tu: cindex.TranslationUnit, include: List[str]) -> Dict[str, Header]:

    path_map: Dict[pathlib.Path, Header] = {}

    def get_or_create_header(path: pathlib.Path) -> Header:
        header = path_map.get(path)
        if not header:
            header = Header(path)
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

        current = get_or_create_header(
            pathlib.Path(c.location.file.name).resolve())
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
            tokens = [t for t in c.get_tokens()]
            if tokens and tokens[0].spelling == 'extern':
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
    for k, v in used.items():
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
        cindex.CursorKind.MACRO_INSTANTIATION,
    ]

    def get_or_create_header(path: pathlib.Path) -> Header:
        header = path_map.get(path)
        if not header:
            header = Header(path)
            path_map[path] = header
        return header

    used: Dict[int, Node] = {}

    def traverse(c: cindex.Cursor) -> None:
        if not c.location.file:
            return

        if c.hash in used:
            # already processed
            return
        used[c.hash] = True

        current = get_or_create_header(

            pathlib.Path(c.location.file.name).resolve())
        if not current:
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

        if c.kind == cindex.CursorKind.MACRO_INSTANTIATION:
            pass

    # parse
    for c in tu.cursor.get_children():
        traverse(c)
