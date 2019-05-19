import pathlib
import contextlib
import shutil
import time
import re
from typing import TextIO, Set
from .cindex_parser import EnumNode, TypedefNode, FunctionNode, StructNode, Header
from .cdeclare import Declare, BaseType, Pointer, Array, Void

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

struct_map = {
    'D3D11_AUTHENTICATED_PROTECTION_FLAGS':
    '''
[StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
struct __MIDL___MIDL_itf_d3d11_0000_0034_0001{
    UInt32 ProtectionEnabled;
    UInt32 OverlayOrFullscreenRequired;
    UInt32 Reserved;
}
[StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
public struct D3D11_AUTHENTICATED_PROTECTION_FLAGS{
    /* (struct __MIDL___MIDL_itf_d3d11_0000_0034_0001) */__MIDL___MIDL_itf_d3d11_0000_0034_0001 Flags;
    /* (UINT) */UInt32 Value;
}
'''
}


def is_interface(src: str) -> bool:
    if src.isupper():
        return False
    return src[0] == 'I'


def replace_type(m):
    return type_map.get(m[0], m[0])


def cs_type(d: Declare, is_param, level=0) -> str:
    if isinstance(d, Pointer):
        if level == 0:
            if isinstance(d.target, Pointer):
                if isinstance(d.target.target, Pointer):
                    raise NotImplementedError('triple pointer')
                # double pointer
                if isinstance(d.target.target, BaseType) and is_interface(
                        d.target.target.type):
                    # **Interface
                    if d.target.target.type == 'IUnknown':
                        return 'IntPtr'
                    else:
                        if is_param:
                            return f'ref {d.target.target.type}'
                        else:
                            # member
                            return 'IntPtr'

            elif isinstance(d.target, BaseType) and is_interface(
                    d.target.type):
                # *Interface
                if d.target.type == 'IUnknown':
                    return 'IntPtr'
                else:
                    return d.target.type

        if isinstance(d.target, Void):
            return 'IntPtr'

        elif is_param:

            target = cs_type(d.target, False, level + 1)
            return f'ref {target}'

        else:

            return f'IntPtr'

    elif isinstance(d, Array):
        target = cs_type(d.target, False, level + 1)

        if level == 0:
            if is_param:
                if level == 0 and isinstance(
                        d.target, BaseType) and d.target.type == 'FLOAT':
                    return 'ref Vector4'
                # array to pointer
                return f'{target}[]'
            else:
                # ByVal
                if isinstance(d.target, Array):
                    # 多次元配列
                    return f'[MarshalAs(UnmanagedType.ByValArray, SizeConst={d.target.length} * {d.length})]', f'{cs_type(d.target.target, False, level+1)}[]'
                else:
                    if target == 'WCHAR':
                        return f'[MarshalAs(UnmanagedType.ByValTStr, SizeConst={d.length})]', 'string'
                    else:
                        return f'[MarshalAs(UnmanagedType.ByValArray, SizeConst={d.length})]', f'{cs_type(d.target, False, level+1)}[]'
        else:
            return f'{target}[{d.length}]'

    elif isinstance(d, Void):
        return 'void'

    elif isinstance(d, BaseType):
        return type_map.get(d.type, d.type)

    else:
        raise RuntimeError('arienai')


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
        typedef_type = cs_type(node.typedef_type, False)
        d.write(f'public struct {node.name}{{\n')
        d.write(f'    public {typedef_type} Value;\n')
        d.write('}\n')


def write_function(d: TextIO, m: FunctionNode, indent='', extern='') -> None:
    ret = cs_type(m.ret, False) if m.ret else 'void'
    params = [
        f'{cs_type(p.param_type, True)} {p.param_name}' for p in m.params
    ]

    if extern:
        pass
        d.write(f'[DllImport("{extern}")]\n')
        d.write(f'{indent}public static extern {ret} {m.name}(\n')
    else:
        d.write(f'{indent}{ret} {m.name}(\n')

    for i, p in enumerate(params):
        comma = ',' if i != len(params) - 1 else ''
        d.write(f'{indent}    /// {m.params[i]}\n')
        d.write(f'{indent}    {p}{comma}\n')
    d.write(f'{indent});\n')


ARRAY_PATTERN = re.compile(r'\s*(\w+)\s*\[\s*(\d+)\s*\]')


def write_field(d: TextIO, f: StructNode, indent='') -> None:
    field_type = cs_type(f.field_type, False)

    d.write(f'{indent}/// {f.field_type}\n')
    if isinstance(field_type, tuple):
        d.write(f'{indent}{field_type[0]}\n')
        d.write(f'{indent}public {field_type[1]} {f.name};\n')
    else:
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

        if any(x.field_type == 'union' for x in node.fields):
            # include union
            d.write(
                '[StructLayout(LayoutKind.Explicit, CharSet = CharSet.Unicode)]\n'
            )
            d.write(f'public struct {node.name}{{\n')
            offset = 0
            indent = '    '
            indent2 = indent + '    '
            for f in node.fields:
                if f.field_type == 'union':
                    d.write(f'{indent}#region union\n')
                    for x in f.fields:
                        d.write(f'{indent2}[FieldOffset({offset})]\n')
                        write_field(d, x, indent2)
                        d.write('\n')
                    d.write(f'{indent}#endregion\n')
                else:
                    d.write(f'{indent}[FieldOffset({offset})]\n')
                    write_field(d, f, indent)
                d.write('\n')
                offset += 4
            d.write(f'}}\n')

        else:

            d.write(
                '[StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]\n'
            )
            d.write(f'public struct {node.name}{{\n')
            for f in node.fields:
                write_field(d, f, '    ')
                d.write('\n')
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

                        snippet = struct_map.get(node.name)
                        if snippet:
                            # replace
                            d.write(snippet)
                        else:
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
