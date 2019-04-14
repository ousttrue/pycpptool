import argparse
import shutil
import datetime
import sys
import re
import platform
import pathlib
import uuid
import io
from typing import Dict, List, Optional, Set, TextIO, NamedTuple
from clang import cindex


HERE = pathlib.Path(__file__).resolve().parent

DEFAULT_CLANG_DLL = pathlib.Path(
    "C:/Program Files (x86)/LLVM/bin/libclang.dll")

SET_DLL = False

# helper {{{
def get_tu(path: pathlib.Path,
           use_macro: bool = False,
           dll: Optional[pathlib.Path] = None) -> cindex.TranslationUnit:
    '''
    parse cpp source
    '''
    global SET_DLL

    if not path.exists():
        raise FileNotFoundError(str(path))

    if not dll and DEFAULT_CLANG_DLL.exists():
        dll = DEFAULT_CLANG_DLL
    if not SET_DLL and dll:
        cindex.Config.set_library_file(str(dll))
        SET_DLL=True

    index = cindex.Index.create()

    kw = {
    }
    if use_macro:
        kw['options'] = cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD

    return index.parse(
        str(path),
        ['-x', 'c++'], **kw)


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

# }}}

# Node {{{
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
                raise(Exception(child.kind))
            elif child.kind == cindex.CursorKind.UNEXPOSED_ATTR:
                #tokens = [t.spelling for t in child.get_tokens()]
                #print(tokens)
                #raise(Exception(child.kind))
                continue
            else:
                raise(Exception(child.kind))

    def __str__(self) -> str:
        return f'{self.name}({", ".join(str(p) for p in self.params)})->{self.ret};'


class StructNode(Node):
    def __init__(self, path: pathlib.Path, c: cindex.Cursor, is_root=True) -> None:
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
                if value.startswith('MIDL_INTERFACE("'):
                    self.iid = uuid.UUID(value[16:-2])
            elif child.kind == cindex.CursorKind.CXX_BASE_SPECIFIER:
                if child.type == cindex.TypeKind.TYPEDEF:
                    self.base = get_typedef_type(child).spelling
                else:
                    self.base = child.type.spelling
            elif child.kind == cindex.CursorKind.CXX_METHOD:
                self.methods.append(FunctionNode(self.path, child))
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
        return StructNode(current, c)
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


def parse(root_path: pathlib.Path, include: List[str]) -> Dict[str, Header]:

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

        current = get_or_create_header(pathlib.Path(c.location.file.name).resolve())
        if current.path == root_path:
            pass
        elif current.name in include:
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
    tu = get_tu(root_path)
    for c in tu.cursor.get_children():
        traverse(c)

    # modify
    for k, v in used.items():
        if v.canonical and v.canonical in used:
            # mark forward declaration
            used[v.canonical].is_forward = True

    return path_map

def parse_macro(path_map: Dict[pathlib.Path, Header], root_path: pathlib.Path, include: List[str]) -> None:

    name_map = {normalize(pathlib.Path(k).name): v for k, v in path_map.items()}

    name_map = {k: v for k, v in name_map.items() if k in include}

    kinds = [
            cindex.CursorKind.UNEXPOSED_DECL,
            cindex.CursorKind.INCLUSION_DIRECTIVE,
            cindex.CursorKind.MACRO_DEFINITION,
    ]

    def traverse(c: cindex.Cursor) -> None:
        if not c.location.file:
            return

        current = path_map.get(pathlib.Path(c.location.file.name).resolve())
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
                header_name = ''.join(tokens[carret+1:-1])
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

            if tokens == ['IID_ID3DBlob', 'IID_ID3D10Blob']:
                #define IID_ID3DBlob IID_ID3D10Blob
                return

            if tokens == ['INTERFACE', 'ID3DInclude']:
                #define INTERFACE ID3DInclude
                return

            if len(tokens)>=3 and tokens[1]=='(' and tokens[2][0].isalpha():
                 # maybe macro function
                return

            return current.macro_defnitions.append(
                    MacroDefinition(
                        c.spelling, 
                        ' '.join(x for x in tokens[1:])))


    # parse
    tu = get_tu(root_path, True)
    for c in tu.cursor.get_children():
        traverse(c)



# }}}

# dlang {{{
IMPORT = '''
import core.sys.windows.windef;
import core.sys.windows.com;
'''

HEAD = '''
extern(Windows){

alias IID = GUID;

'''


TAIL = '''
}
'''

def dlang_enum(d: TextIO, node: EnumNode) -> None:
    d.write(f'enum {node.name} {{\n')
    for v in node.values:
        name = v.name
        if name.startswith(node.name):
            # invalid: DXGI_FORMAT_420_OPAQUE
            if name[len(node.name)+1].isnumeric():
                name = name[len(node.name)+0:]
            else:
                name = name[len(node.name)+1:]
        else:
            for suffix in ['_FLAG', '_MODE']:
                suffix_len = len(suffix)
                if node.name.endswith(suffix) and name.startswith(node.name[:-suffix_len]):
                    if name[len(node.name)-suffix_len+1].isnumeric():
                        name = name[len(node.name)-suffix_len:]
                    else:
                        name = name[len(node.name)-suffix_len+1:]
                    break

        value = v.value
        if isinstance(value, int):
            value = f'{value:#010x}'

        d.write(f'    {name} = {value},\n')
    d.write(f'}}\n')

def dlang_alias(d: TextIO, node: TypedefNode) -> None:
    if node.name.startswith('PFN_'):
        # function pointer workaround
        d.write(f'alias {node.name} = void *;\n')
    else:
        typedef_type = node.typedef_type
        if typedef_type.startswith('struct '):
            typedef_type = typedef_type[7:]
        d.write(f'alias {node.name} = {typedef_type};\n')

def repl(m):
    return m[0][1:]
def to_d(param_type: str)->str:
    param_type = (param_type
            .replace('&', '*')
            .replace('*const *', '**'))
    if param_type[0] == 'I': # is_instance
        param_type = re.sub(r'\*+', repl, param_type) # reduce *
    return param_type

def dlang_function(d: TextIO, m: FunctionNode, indent = '') -> None:
    ret = m.ret if m.ret else 'void'
    params = ', '.join(f'{to_d(p.param_type)} {p.param_name}' for p in m.params)
    d.write(f'{indent}{ret} {m.name}({params});\n');

def dlang_struct(d: TextIO, node: StructNode) -> None:
    if node.name[0]=='I':
        # com interface
        base = node.base
        if not base:
            base = 'IUnknown'
        d.write(f'interface {node.name}: {base} {{\n')
        if node.iid:
            h = node.iid.hex
            iid = f'0x{h[0:8]}, 0x{h[8:12]}, 0x{h[12:16]}, [0x{h[16:18]}, 0x{h[18:20]}, 0x{h[20:22]}, 0x{h[22:24]}, 0x{h[24:26]}, 0x{h[26:28]}, 0x{h[28:30]}, 0x{h[30:32]}]'
            d.write(f'    static immutable iidof = GUID({iid});\n')
        for m in node.methods:
            dlang_function(d, m, '    ')
        d.write(f'}}\n')
    else:
        d.write(f'{node}\n')


class DlangGenerator:
    def __init__(self) -> None:
        self.used: Set[str] = set()

    def generate(self, header: Header,
            dlang_root: pathlib.Path,
            kit_name: str
            ) -> None:
        package_name = f'build_{kit_name.replace(".", "_")}'
        root = dlang_root / 'windowskits' / package_name

        if root.exists():
            shutil.rmtree(root)
        root.mkdir(parents=True, exist_ok=True)

        self._generate_header(header, root, package_name)

    def _generate_header(self, header: Header, 
            root: pathlib.Path, package_name: str):

        module_name = header.name[:-2]

        if module_name in self.used:
            return
        self.used.add(module_name)

        dst = root / f'{module_name}.d'
        print(dst)

        with dst.open('w') as d:
            d.write(f'// pycpptool generated: {datetime.datetime.today()}\n')
            d.write(f'module windowskits.{package_name}.{module_name};\n')

            d.write(IMPORT)
            for include in header.includes:
                d.write(f'public import windowskits.{package_name}.{include.name[:-2]};\n')
            d.write(HEAD)

            for m in header.macro_defnitions:
                d.write(f'enum {m.name} = {m.value};\n')

            for node in header.nodes:

                '''
                snippet = snippet_map.get(module_name)
                if snippet:
                    d.write(snippet)
                '''

                if isinstance(node, EnumNode):
                    dlang_enum(d, node)
                    d.write('\n')
                elif isinstance(node, TypedefNode):
                    dlang_alias(d, node)
                    d.write('\n')
                elif isinstance(node, StructNode):
                    if node.is_forward:
                        continue
                    if node.name[0] == 'C': # class
                        continue
                    dlang_struct(d, node)
                    d.write('\n')
                elif isinstance(node, FunctionNode):
                    dlang_function(d, node)
                    d.write('\n')
                else:
                    #raise Exception(type(node))
                    pass

                '''
                # constant
                const(d, v.const_list)
                '''
            d.write(TAIL)


        for include in header.includes:
            self._generate_header(include, root, package_name)

# }}}

def show(f: TextIO, path: pathlib.Path) -> None:

    used: Set[int] = set()

    def traverse(c: cindex.Cursor, indent='') -> None:
        # skip
        if c.location.file.name != str(path):
            # exclude included file
            return
        if c.hash in used:
            # avoid show twice
            return
        used.add(c.hash)

        ref = ''
        if c.referenced and c.referenced.hash != c.hash:
            ref = f' => {c.referenced.hash:#010x}'

        canonical = ''
        if c.canonical and c.canonical.hash != c.hash:
            canonical = f' => {c.canonical.hash:#010x} (forward decl)'

        value = f'{c.hash:#010x}:{indent} {c.kind}: {c.spelling}{ref}{canonical}'
        print(value)

        if c.kind == cindex.CursorKind.UNEXPOSED_DECL:
            tokens = [t for t in c.get_tokens()]
            if tokens and tokens[0].spelling == 'extern':
                # extern "C" block
                for child in c.get_children():
                    traverse(child)
                return

        for child in c.get_children():
            traverse(child, indent + '  ')

    tu = get_tu(path)
    for c in tu.cursor.get_children():
        traverse(c)


def main()->None:
    parser = argparse.ArgumentParser(description='Process cpp header.')

    sub = parser.add_subparsers()

    # debug
    sub_debug = sub.add_parser('debug')
    sub_debug.set_defaults(action='debug')
    sub_debug.add_argument(
        'entrypoint', help='parse target')
    sub_debug.add_argument(
        '-i', '--include', action='append')

    # parse
    sub_parse = sub.add_parser('parse')
    sub_parse.set_defaults(action='parse')
    sub_parse.add_argument(
        'entrypoint', help='parse target')
    sub_parse.add_argument(
        '-i', '--include', action='append')

    # generator
    sub_gen = sub.add_parser('gen')
    sub_gen.set_defaults(action='gen')
    sub_gen.add_argument(
        'entrypoint', help='parse target')
    sub_gen.add_argument(
        '-o', '--outfolder', required=True)
    sub_gen.add_argument(
        '-i', '--include', action='append')
    sub_gen.add_argument(
        '-g', '--generator', help='code generator', choices=['dlang'],
        required=True)

    # execute
    args = parser.parse_args()

    path = (HERE / args.entrypoint).resolve()

    include = args.include
    if include:
        include = [normalize(x) for x in include]
    else:
        include = []

    if args.action == 'debug':
        show(sys.stdout, path)
    elif args.action == 'parse':
        headers = parse(path, include)
        parse_macro(headers, path, include)
        headers[path].print_nodes()
    elif args.action == 'gen':
        headers = parse(path, include)
        #for k, v in headers.items():
        #    print(k, len(v.nodes))
        parse_macro(headers, path, include)
        kit_name = path.parent.parent.name

        if args.generator == 'dlang':
            gen = DlangGenerator()
            dlang_root = pathlib.Path(str(args.outfolder)).resolve()

            gen.generate(
                    headers[path],
                    dlang_root,
                    kit_name
                    )

    else:
        raise Exception()


if __name__ == '__main__':
    main()
