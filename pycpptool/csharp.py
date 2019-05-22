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
    'WCHAR': 'Char',
    'INT': 'Int32',
    'BOOL': 'Int32',
    'LARGE_INTEGER': 'Int64',
    'BYTE': 'Byte',
    'UINT8': 'Byte',
    'USHORT': 'UInt16',
    'UINT': 'UInt32',
    'ULONG': 'UInt32',
    'UINT32': 'UInt32',
    'UINT64': 'UInt64',
    'DWORD': 'UInt32',
    'UINT64': 'UInt64',
    'ULONGLONG': 'UInt64',
    'ULARGE_INTEGER': 'UInt64',
    'FLOAT': 'Single',
    'HANDLE': 'IntPtr',
    'HMODULE': 'IntPtr',
    'HWND': 'IntPtr',
    'HMONITOR': 'IntPtr',
    'HDC': 'IntPtr',
    'LPSTR': 'IntPtr',
    'LPCSTR': 'IntPtr',
    'LPWSTR': 'IntPtr',
    'PWSTR': 'IntPtr',
    'PCWSTR': 'IntPtr',
    'LPCWSTR': 'IntPtr',
    'LPVOID': 'IntPtr',
    'LPCVOID': 'IntPtr',
    'SIZE_T': 'UIntPtr',
    'GUID': 'Guid',
    'LUID': 'Guid',
    'IID': 'Guid',
    'CLSID': 'Guid',
    'PD2D1_EFFECT_FACTORY': 'IntPtr',
    #'D2D1_COLOR_F': 'D2D_COLOR_F',
    'D2D1_COLOR_F': 'Vector4',
    'D2D1_POINT_2F': 'D2D_POINT_2F',
    'D2D1_POINT_2U': 'D2D_POINT_2U',
    'D2D1_SIZE_F': 'D2D_SIZE_F',
    'D2D1_RECT_F': 'D2D_RECT_F',
    'D2D1_RECT_U': 'D2D_RECT_U',
    'D2D1_MATRIX_3X2_F': 'D2D_MATRIX_3X2_F',
    'D2D1_MATRIX_4X4_F': 'D2D_MATRIX_4X4_F',
    'D2D1_SIZE_U': 'D2D_SIZE_U',
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
''',
    'D2D_MATRIX_3X2_F':
    '''
[StructLayout(LayoutKind.Explicit, CharSet = CharSet.Unicode)]
public struct D2D_MATRIX_3X2_F {
  #region union
    [FieldOffset(0)]
    public Single m11;
    [FieldOffset(4)]
    public Single m12;
    [FieldOffset(8)]
    public Single m21;
    [FieldOffset(12)]
    public Single m22;
    [FieldOffset(16)]
    public Single dx;
    [FieldOffset(20)]
    public Single dy;

    [FieldOffset(0)]
    public Single _11;
    [FieldOffset(4)]
    public Single _12;
    [FieldOffset(8)]
    public Single _21;
    [FieldOffset(12)]
    public Single _22;
    [FieldOffset(16)]
    public Single _31;
    [FieldOffset(20)]
    public Single _32;
  #endregion
}
''',
    'D2D_MATRIX_4X3_F':
    '''
[StructLayout(LayoutKind.Explicit, CharSet = CharSet.Unicode)]
public struct D2D_MATRIX_4X3_F {
  #region union
    [FieldOffset(0)]
    public Single _11;
    [FieldOffset(4)]
    public Single _12;
    [FieldOffset(8)]
    public Single _13;
    [FieldOffset(12)]
    public Single _21;
    [FieldOffset(16)]
    public Single _22;
    [FieldOffset(20)]
    public Single _23;
    [FieldOffset(24)]
    public Single _31;
    [FieldOffset(28)]
    public Single _32;
    [FieldOffset(32)]
    public Single _33;
    [FieldOffset(36)]
    public Single _41;
    [FieldOffset(40)]
    public Single _42;
    [FieldOffset(44)]
    public Single _43;
  #endregion
}
''',
    'D2D_MATRIX_4X4_F':
    '''
[StructLayout(LayoutKind.Explicit, CharSet = CharSet.Unicode)]
public struct D2D_MATRIX_4X4_F {
  #region union
    [FieldOffset(0)]
    public Single _11;
    [FieldOffset(4)]
    public Single _12;
    [FieldOffset(8)]
    public Single _13;
    [FieldOffset(12)]
    public Single _14;
    [FieldOffset(16)]
    public Single _21;
    [FieldOffset(20)]
    public Single _22;
    [FieldOffset(24)]
    public Single _23;
    [FieldOffset(28)]
    public Single _24;
    [FieldOffset(32)]
    public Single _31;
    [FieldOffset(36)]
    public Single _32;
    [FieldOffset(40)]
    public Single _33;
    [FieldOffset(44)]
    public Single _34;
    [FieldOffset(48)]
    public Single _41;
    [FieldOffset(52)]
    public Single _42;
    [FieldOffset(56)]
    public Single _43;
    [FieldOffset(60)]
    public Single _44;
  #endregion
}
''',
    'D2D_MATRIX_5X4_F':
    '''
[StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
public struct D2D_MATRIX_5X4_F
{
    [MarshalAs(UnmanagedType.ByValArray, SizeConst=20)]
    public Single[] m;
}
'''
}

func_map = {
    'D3D11CreateDevice':
    '''
    [DllImport("D3D11.dll")]
    public static extern HRESULT D3D11CreateDevice(
        /// pAdapter: (*(IDXGIAdapter))
        IDXGIAdapter pAdapter,
        /// DriverType: (D3D_DRIVER_TYPE)
        D3D_DRIVER_TYPE DriverType,
        /// Software: (HMODULE)
        IntPtr Software,
        /// Flags: (UINT)
        UInt32 Flags,
        /// pFeatureLevels: (*(const D3D_FEATURE_LEVEL))
        ref D3D_FEATURE_LEVEL pFeatureLevels,
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
    public static extern HRESULT D3D11CreateDeviceAndSwapChain(
        /// pAdapter: (*(IDXGIAdapter))
        IDXGIAdapter pAdapter,
        /// DriverType: (D3D_DRIVER_TYPE)
        D3D_DRIVER_TYPE DriverType,
        /// Software: (HMODULE)
        IntPtr Software,
        /// Flags: (UINT)
        UInt32 Flags,
        /// pFeatureLevels: (*(const D3D_FEATURE_LEVEL))
        ref D3D_FEATURE_LEVEL pFeatureLevels,
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
public struct SECURITY_ATTRIBUTES {
    public UInt32 nLength;
    public IntPtr lpSecurityDescriptor;
    public Int32 bInheritHandle;
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
                #return f'{target}[]'
                # for Span<T>
                return f'ref {target}'
            else:
                # ByVal
                if isinstance(d.target, Array):
                    # 多次元配列
                    return f'[MarshalAs(UnmanagedType.ByValArray, SizeConst={d.target.length} * {d.length})]', f'{cs_type(d.target.target, False, level+1)}[]'
                else:
                    if target in ['WCHAR', 'Char']:
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
        print(d)
        #raise RuntimeError('arienai')
        return str(d)


dll_map = {
    'dxgi.h': 'DXGI.dll',
    'd3d11.h': 'D3D11.dll',
    'd2d1.h': 'D2D1.dll',
    'd2d1_1.h': 'D2D1.dll',
}


def write_const(d: TextIO, m) -> None:
    value = m.value
    if value == 'UINT_MAX':
        value = 'UInt32.MaxValue'
    d.write(f'public const int {m.name} = unchecked((int){value});\n')


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
        d.write(
            '[StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]\n')
        d.write(f'public struct {node.name}{{\n')
        d.write('    public IntPtr Value;\n')
        d.write('}\n')
    else:
        typedef_type = cs_type(node.typedef_type, False)
        if node.name == typedef_type:
            return
        if node.name.startswith('D2D1_') and typedef_type.startswith(
                'D2D_') and node.name[5:] == typedef_type[4:]:
            return
        d.write(
            '[StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]\n')
        d.write(f'public struct {node.name}{{\n')
        d.write(f'    public {typedef_type} Value;\n')
        d.write('}\n')


def name_filter(src) -> str:
    if src == 'string':
        return 'str'
    return src


def type_with_name(p):
    return f'{cs_type(p.param_type, True)} {name_filter(p.param_name)}'


def ref_with_name(p):
    cs = cs_type(p.param_type, True)
    name = name_filter(p.param_name)
    if cs.startswith('ref '):
        return 'ref ' + name
    else:
        return name


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
        # function body extends ComPtr(IUnknown represent)
        d.write('\n')
        d.write(f'''{indent}{{
{indent2}var fp = GetFunctionPointer(VTableIndexBase + {index});
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
            d.write(f'public class {node.name} : ComPtr{{\n')
        else:
            d.write(f'public class {node.name}: {base} {{\n')

        d.write(f'''
    static /*readonly*/ Guid s_uuid = new Guid("{node.iid}");
    public override ref /*readonly*/ Guid IID => ref s_uuid;
    static int MethodCount => {len(node.methods)};
    int VTableIndexBase => VTableIndexBase<{node.name}>.Value;
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
                if header.name == 'dcommon.h' and node.name == 'IDXGISurface':
                    # skip
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
                write_const(d, m)
            dll = dll_map.get(header.name)

            used_function = set()
            for f in functions:
                if f.name in used_function:
                    continue
                used_function.add(f.name)

                func = func_map.get(f.name)
                if func:
                    # replace
                    d.write(func)
                else:
                    write_function(d, f, '', extern=dll)
                d.write('\n')
            d.write('}\n')
