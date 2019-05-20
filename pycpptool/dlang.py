import datetime
import pathlib
import time
import shutil
import re
from typing import TextIO, Set
from .cindex_parser import EnumNode, TypedefNode, FunctionNode, StructNode, Header

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

D3D11_SNIPPET = '''

'''

D2D1_SNIPPET = '''

enum D2DERR_RECREATE_TARGET = 0x8899000CL;

'''

D2D_BASETYPES = '''

struct D3DCOLORVALUE
{
    float r;
    float g;
    float b;
    float a;
}

'''

snippet_map = {
    'd3d11': D3D11_SNIPPET,
    'd2d1': D2D1_SNIPPET,
    'd2dbasetypes': D2D_BASETYPES,
}


def dlang_enum(d: TextIO, node: EnumNode) -> None:
    d.write(f'enum {node.name} {{\n')
    for v in node.values:
        name = v.name
        if name.startswith(node.name):
            # invalid: DXGI_FORMAT_420_OPAQUE
            if name[len(node.name) + 1].isnumeric():
                name = name[len(node.name) + 0:]
            else:
                name = name[len(node.name) + 1:]
        else:
            for suffix in ['_FLAG', '_MODE']:
                suffix_len = len(suffix)
                if node.name.endswith(suffix) and name.startswith(
                        node.name[:-suffix_len]):
                    if name[len(node.name) - suffix_len + 1].isnumeric():
                        name = name[len(node.name) - suffix_len:]
                    else:
                        name = name[len(node.name) - suffix_len + 1:]
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


def to_d(param_type: str) -> str:
    param_type = (param_type.replace('&', '*').replace('*const *', '**'))
    if param_type[0] == 'I':  # is_instance
        param_type = re.sub(r'\*+', repl, param_type)  # reduce *
    return param_type


def dlang_function(d: TextIO, m: FunctionNode, indent='') -> None:
    ret = m.ret if m.ret else 'void'
    params = ', '.join(f'{to_d(p.param_type)} {p.param_name}'
                       for p in m.params)
    d.write(f'{indent}{ret} {m.name}({params});\n')


def dlang_struct(d: TextIO, node: StructNode) -> None:
    if node.name[0] == 'I':
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


def generate(header: Header, dlang_root: pathlib.Path, kit_name: str,
             multi_header: bool) -> None:
    package_name = f'build_{kit_name.replace(".", "_")}'
    root = dlang_root / 'windowskits' / package_name

    if root.exists():
        shutil.rmtree(root)
        time.sleep(0.1)
    root.mkdir(parents=True, exist_ok=True)

    gen = DlangGenerator()
    gen.generate_header(header, root, package_name, multi_header)


class DlangGenerator:
    def __init__(self) -> None:
        self.used: Set[str] = set()

    def generate_header(self, header: Header, root: pathlib.Path,
                        package_name: str, skip: bool):

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
                d.write(
                    f'public import windowskits.{package_name}.{include.name[:-2]};\n'
                )
            d.write(HEAD)

            snippet = snippet_map.get(module_name)
            if snippet:
                d.write(snippet)

            for m in header.macro_defnitions:
                d.write(f'enum {m.name} = {m.value};\n')

            for node in header.nodes:

                if isinstance(node, EnumNode):
                    dlang_enum(d, node)
                    d.write('\n')
                elif isinstance(node, TypedefNode):
                    dlang_alias(d, node)
                    d.write('\n')
                elif isinstance(node, StructNode):
                    if node.is_forward:
                        continue
                    if node.name[0] == 'C':  # class
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
            self.generate_header(include, root, package_name)


# }}}
