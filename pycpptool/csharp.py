import pathlib
import contextlib
import shutil
import time
import re
from typing import TextIO, Set
from .cindex_parser import EnumNode, TypedefNode, FunctionNode, StructNode, Header

# https://docs.microsoft.com/en-us/windows/desktop/winprog/windows-data-types
type_map = {
    'BYTE': 'Byte',
    'UINT8': 'Byte',
    'INT': 'Int32',
    'BOOL': 'Int32',
    'HRESULT': 'Int32',
    'LARGE_INTEGER': 'Int64',
    'USHORT': 'UInt16',
    'UINT': 'UInt32',
    'DWORD': 'UInt32',
    'UINT64': 'UInt64',
    'ULONGLONG': 'UInt64',
    'FLOAT': 'Single',
    'HANDLE': 'IntPtr',
    'HMODULE': 'IntPtr',
    'HWND': 'IntPtr',
    'HMONITOR': 'IntPtr',
    'HDC': 'IntPtr',
    'LPCSTR': 'IntPtr',
    'LPSTR': 'IntPtr',
    'LPVOID': 'IntPtr',
    'LPCVOID': 'IntPtr',
    'SIZE_T': 'UIntPtr',
    'GUID': 'Guid',
    'LUID': 'Guid',
    'IID': 'Guid',
}


def replace_type(m):
    return type_map.get(m[0], m[0])


def cs_type(src):
    if 'FLOAT [4]' in src:
        return 'ref Vector4'
    return re.sub(r'\w+', replace_type, src)


dll_map = {
    'CreateDXGIFactory': 'DXGI.dll',
    'CreateDXGIFactory1': 'DXGI.dll',
    'D3D11CalcSubresource': 'D3D11.dll',
    'D3D11CreateDevice': 'D3D11.dll',
    'D3D11CreateDeviceAndSwapChain': 'D3D11.dll',
}


def write_enum(d: TextIO, node: EnumNode) -> None:
    d.write(f'public enum {node.name} {{\n')
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


def write_alias(d: TextIO, node: TypedefNode) -> None:
    if node.name.startswith('PFN_'):
        # function pointer workaround
        d.write(f'public struct {node.name}{{\n')
        d.write('    public IntPtr Value;\n')
        d.write('}\n')
    else:
        typedef_type = node.typedef_type
        if typedef_type.startswith('struct '):
            typedef_type = typedef_type[7:]
        typedef_type = cs_type(typedef_type)
        d.write(f'public struct {node.name}{{\n')
        d.write(f'    public {typedef_type} Value;\n')
        d.write('}\n')


def reduce_asta(m):
    return m[0][1:]


def before_after(f):
    def inner(before):
        after = f(before)
        # if 'IUnknown' in before:
        #     print(f'{before} => {after}')
        return after

    return inner


@before_after
def to_cs(param_type: str) -> str:
    '''
    c type to cs type
    '''
    param_type = cs_type(param_type)
    param_type = param_type.replace('&', '*').replace('const', '').strip()
    if param_type[0] == 'I':  # is_instance
        param_type = re.sub(r'\*+', reduce_asta,
                            param_type).strip()  # reduce *

    count = param_type.count('*')
    if count == 0:
        if param_type == 'IUnknown':
            param_type = '/* IUnknown* */IntPtr'

    elif count == 1:
        if 'void' in param_type:
            ref = 'IntPtr'
        else:
            ref = 'ref ' + param_type.replace('*', '').strip()
            if ref == 'ref IUnknown':
                ref = '/* IUnknown** */ref IntPtr'
        #print(f'{param_type} => "{ref}"')
        param_type = ref

    elif count == 2:
        if 'void' in param_type:
            ref = 'ref IntPtr'
        else:
            ref = 'ref IntPtr'
        #print(f'{param_type} => "{ref}"')
        param_type = ref

    return param_type


def write_function(d: TextIO, m: FunctionNode, indent='', extern='') -> None:
    ret = cs_type(m.ret) if m.ret else 'void'
    params = ', '.join(f'{to_cs(p.param_type)} {p.param_name}'
                       for p in m.params)

    if extern:
        pass
        d.write(f'[DllImport("{extern}")]\n')
        d.write(f'{indent}public static extern {ret} {m.name}({params});\n')
    else:
        d.write(f'{indent}{ret} {m.name}({params});\n')


ARRAY_PATTERN = re.compile(r'\s*(\w+)\s*\[\s*(\d+)\s*\]')


def write_field(d: TextIO, f: StructNode, indent='') -> None:
    #d.write(f'{indent}{f};\n')
    field_type = cs_type(f.field_type)
    if field_type.startswith('struct '):
        field_type = field_type[7:]

    if '*' in field_type:
        field_type = f'/* {field_type} */IntPtr'

    m = ARRAY_PATTERN.match(field_type)
    if m:
        # some[size]; sized array
        if m.group(1) == 'WCHAR':
            d.write(
                f'{indent}[MarshalAs(UnmanagedType.ByValTStr, SizeConst={int(m.group(2))})]\n'
            )
            field_type = f'string'
        else:
            d.write(
                f'{indent}[MarshalAs(UnmanagedType.ByValArray, SizeConst={int(m.group(2))})]\n'
            )
            field_type = f'{m.group(1)}[]'
        d.write(f'{indent}public {field_type} {f.name};\n')

    else:
        # other
        d.write(f'{indent}public {field_type} {f.name};\n')


def write_struct(d: TextIO, node: StructNode) -> None:
    if node.name[0] == 'I':
        # com interface
        base = node.base

        if node.iid:
            h = node.iid.hex
            iid = f'0x{h[0:8]}, 0x{h[8:12]}, 0x{h[12:16]}, [0x{h[16:18]}, 0x{h[18:20]}, 0x{h[20:22]}, 0x{h[22:24]}, 0x{h[24:26]}, 0x{h[26:28]}, 0x{h[28:30]}, 0x{h[30:32]}]'
            d.write(f'[ComImport, Guid("{node.iid}")]\n')

        if not base or base == 'IUnknown':
            # IUnknown
            d.write('[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]\n')
            d.write(f'public interface {node.name}{{\n')
        else:
            d.write(f'public interface {node.name}: {base} {{\n')

        for m in node.methods:
            write_function(d, m, '    ')
        d.write(f'}}\n')
    else:
        d.write(
            '[StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]\n')
        d.write(f'public struct {node.name}{{\n')
        for f in node.fields:
            write_field(d, f, '    ')
        d.write(f'}}\n')


@contextlib.contextmanager
def namespace(d, name):
    # Code to acquire resource, e.g.:
    d.write(f'namespace {name} {{\n')
    d.write('\n')
    try:
        yield None
    finally:
        # Code to release resource, e.g.:
        d.write('}\n')


class CSharpGenerator:
    def __init__(self):
        self.used: Set[str] = set()

    def generate(self, header: Header, csharp_root: pathlib.Path,
                 kit_name: str):
        package_name = f'build_{kit_name.replace(".", "_")}'
        root = csharp_root / 'WindowsKits' / package_name

        if root.exists():
            shutil.rmtree(root)
            time.sleep(0.1)
        root.mkdir(parents=True, exist_ok=True)

        self._generate_header(header, root, package_name)

    def _generate_header(self, header: Header, root: pathlib.Path,
                         package_name: str):

        module_name = header.name[:-2]

        if module_name in self.used:
            return
        self.used.add(module_name)

        dst = root / f'{module_name}.cs'
        print(dst)

        with dst.open('w') as d:

            d.write('''
using System;
using System.Runtime.InteropServices;
using System.Numerics;

''')

            with namespace(d, f'{root.parent.name}.{root.name}'):

                functions = []

                for node in header.nodes:

                    if isinstance(node, EnumNode):
                        write_enum(d, node)
                        d.write('\n')
                    elif isinstance(node, TypedefNode):
                        write_alias(d, node)
                        d.write('\n')
                    elif isinstance(node, StructNode):
                        if node.is_forward:
                            continue
                        if node.name[0] == 'C':  # class
                            continue
                        write_struct(d, node)
                        d.write('\n')
                    elif isinstance(node, FunctionNode):
                        functions.append(node)

                if functions:
                    d.write(f'public static class {module_name}{{\n')
                    for f in functions:
                        write_function(d, f, '', dll_map.get(f.name))
                        d.write('\n')
                    d.write('}\n')

        for include in header.includes:
            self._generate_header(include, root, package_name)
