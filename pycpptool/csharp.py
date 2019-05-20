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
    'LPSTR': 'IntPtr',
    'LPCSTR': 'IntPtr',
    'LPWSTR': 'IntPtr',
    'LPCWSTR': 'IntPtr',
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

func_map = {
    'D3D11CreateDevice':
    '''
    [DllImport("D3D11.dll")]
    public static extern Int32 D3D11CreateDevice(
        /// pAdapter: (*(IDXGIAdapter))
        IDXGIAdapter pAdapter,
        /// DriverType: (D3D_DRIVER_TYPE)
        D3D_DRIVER_TYPE DriverType,
        /// Software: (HMODULE)
        IntPtr Software,
        /// Flags: (UINT)
        UInt32 Flags,
        /// pFeatureLevels: (*(const D3D_FEATURE_LEVEL))
        D3D_FEATURE_LEVEL[] pFeatureLevels,
        /// FeatureLevels: (UINT)
        UInt32 FeatureLevels,
        /// SDKVersion: (UINT)
        UInt32 SDKVersion,
        /// ppDevice: (*(*(ID3D11Device)))
        ref IntPtr ppDevice,
        /// pFeatureLevel: (*(D3D_FEATURE_LEVEL))
        ref D3D_FEATURE_LEVEL pFeatureLevel,
        /// ppImmediateContext: (*(*(ID3D11DeviceContext)))
        ref IntPtr ppImmediateContext
    );
    ''',
    'D3D11CreateDeviceAndSwapChain':
    '''
    [DllImport("D3D11.dll")]
    public static extern Int32 D3D11CreateDeviceAndSwapChain(
        /// pAdapter: (*(IDXGIAdapter))
        IDXGIAdapter pAdapter,
        /// DriverType: (D3D_DRIVER_TYPE)
        D3D_DRIVER_TYPE DriverType,
        /// Software: (HMODULE)
        IntPtr Software,
        /// Flags: (UINT)
        UInt32 Flags,
        /// pFeatureLevels: (*(const D3D_FEATURE_LEVEL))
        D3D_FEATURE_LEVEL[] pFeatureLevels,
        /// FeatureLevels: (UINT)
        UInt32 FeatureLevels,
        /// SDKVersion: (UINT)
        UInt32 SDKVersion,
        /// pSwapChainDesc: (*(const DXGI_SWAP_CHAIN_DESC))
        ref DXGI_SWAP_CHAIN_DESC pSwapChainDesc,
        /// ppSwapChain: (*(*(IDXGISwapChain)))
        ref IntPtr ppSwapChain,
        /// ppDevice: (*(*(ID3D11Device)))
        ref IntPtr ppDevice,
        /// pFeatureLevel: (*(D3D_FEATURE_LEVEL))
        ref D3D_FEATURE_LEVEL pFeatureLevel,
        /// ppImmediateContext: (*(*(ID3D11DeviceContext)))
        ref IntPtr ppImmediateContext
    );
    ''',
}

types = '''
[StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
struct SECURITY_ATTRIBUTES {
    DWORD nLength;
    LPVOID lpSecurityDescriptor;
    BOOL bInheritHandle;
}
'''


def is_interface(src: str) -> bool:
    if src.isupper():
        return False
    if src == 'IntPtr':
        return False
    return src.startswith('I')


def replace_type(m):
    return type_map.get(m[0], m[0])


def cs_type(d: Declare, is_param, level=0) -> str:
    if isinstance(d, Pointer):
        if level == 0:
            if isinstance(d.target, Pointer):
                # double pointer
                if isinstance(d.target.target, Pointer):
                    raise NotImplementedError('triple pointer')
                else:
                    if is_param:
                        return 'ref IntPtr'
                    else:
                        return 'IntPtr'

        if isinstance(d.target, Void):
            return 'IntPtr'

        if not is_param:
            return f'IntPtr'

        target = cs_type(d.target, False, level + 1)
        if is_interface(target):
            return 'IntPtr'

        return f'ref {target}'

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
    d.write('[StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]\n')
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


def type_with_name(p):
    return f'{cs_type(p.param_type, True)} {p.param_name}'


def ref_with_name(p):
    cs = cs_type(p.param_type, True)
    if cs.startswith('ref '):
        return 'ref ' + p.param_name
    else:
        return p.param_name


def write_function(d: TextIO, m: FunctionNode, indent='', extern='',
                   index=-1) -> None:
    ret = cs_type(m.ret, False) if m.ret else 'void'
    params = [(cs_type(p.param_type, True), p.param_name) for p in m.params]

    if extern:
        d.write(f'[DllImport("{extern}")]\n')
        d.write(f'{indent}public static extern {ret} {m.name}(\n')
    else:
        # for com interface
        d.write(f'{indent}public {ret} {m.name}(\n')

    # params
    indent2 = indent + '    '
    is_first = True
    for p in m.params:
        if is_first:
            is_first = False
            comma = ''
        else:
            comma = ', '
        d.write(f'{indent2}/// {p}\n')
        d.write(f'{indent2}{comma}{type_with_name(p)}\n')
    d.write(f'{indent})')

    if extern:
        d.write(';\n')
    else:
        # function body extends IUnknownImpl
        d.write('\n')
        d.write(f'''{indent}{{
{indent2}var fp = GetFunctionPointer({index});
{indent2}var callback = ({m.name}Func)Marshal.GetDelegateForFunctionPointer(fp, typeof({m.name}Func));
{indent2}{'return ' if ret!='void' else ''}callback(Self{''.join(', ' + ref_with_name(p) for p in m.params)});
{indent}}}
{indent}delegate {ret} {m.name}Func(IntPtr self{''.join(', ' + type_with_name(p) for p in m.params)});
''')


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

        if not base or base == 'IUnknown':
            # IUnknown
            d.write(f'public class {node.name} : IUnknownImpl{{\n')
        else:
            d.write(f'public class {node.name}: {base} {{\n')

        d.write(f'''
    static /*readonly*/ Guid s_uuid = new Guid("{node.iid}");
    public override ref /*readonly*/ Guid IID => ref s_uuid;
    static int MethodCount => {len(node.methods)};
''')

        for i, m in enumerate(node.methods):
            write_function(d, m, '    ', index=i)
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


def generate(header: Header, csharp_root: pathlib.Path, kit_name: str,
             multi_header: bool):
    package_name = f'build_{kit_name.replace(".", "_")}'
    root = csharp_root / 'WindowsKits' / package_name

    if root.exists():
        shutil.rmtree(root)
        time.sleep(0.1)
    root.mkdir(parents=True, exist_ok=True)

    gen = CSharpGenerator()
    gen.generate_header(header, root, package_name, multi_header)


class CSharpGenerator:
    def __init__(self):
        self.used: Set[str] = set()

    def generate_header(self,
                        header: Header,
                        root: pathlib.Path,
                        package_name: str,
                        skip=False):

        module_name = header.name[:-2]
        if module_name in self.used:
            return
        self.used.add(module_name)
        dst = root / f'{module_name}.cs'
        print(dst)

        if not skip:
            with dst.open('w') as d:

                d.write('''
    using System;
    using System.Runtime.InteropServices;
    using System.Numerics;

    ''')

                with namespace(d, f'{root.parent.name}.{root.name}'):
                    self._generate_header_body(header, module_name, d)

        for include in header.includes:
            self.generate_header(include, root, package_name)

    def _generate_header_body(self, header: Header, module_name: str,
                              d: TextIO) -> None:
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
            for m in header.macro_defnitions:
                d.write(
                    f'public const int {m.name} = unchecked((int){m.value});\n'
                )
            for f in functions:
                func = func_map.get(f.name)
                if func:
                    # replace
                    d.write(func)
                else:
                    write_function(d, f, '', extern=dll_map.get(f.name))
                d.write('\n')
            d.write('}\n')
