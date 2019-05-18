# pycpptool

A tool for cpp source manipulation 🐲

Parse cpp header and...

* Generate dlang source for D3D11
* Generate csharp source for D3D11

## dependencies

* install llvm(LLVM-8.0.0-win64.exe)
* pip install clang

## sample

### for csharp

```
python pycpptool/run.py gen 'C:/Program Files (x86)/Windows Kits/10/Include/10.0.17763.0/shared/dxgi.h' '-i' 'dxgicommon.h' '-i' 'dxgiformat.h' '-i' 'dxgitype.h' '-o' '../windowskits/source' '-g' 'csharp'
```

generated

```csharp
[ComImport, Guid("aec22fb8-76f3-4639-9be0-28eb43a67a2e")]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)] // <- Required for com interface that directly inherited from IUnknown  
public interface IDXGIObject{
}

// Do no attach InterfaceType or cause corrupted vtable.
[ComImport, Guid("7b7166ec-21c7-44ae-b21a-c9ae321ae369")]
public interface IDXGIFactory: IDXGIObject {
}
```

use sample

```csharp
        static Guid uuidof<T>()
        {
            var attr = typeof(T).GetCustomAttributes(true).Select(x => x as GuidAttribute).First(x => x != null);
            return new Guid(attr.Value);
        }

        [STAThread]
        static void Main(string[] args)
        {
            var p0 = IntPtr.Zero;
            var uuid = uuidof<IDXGIFactory>();
            var ret = dxgi.CreateDXGIFactory(ref uuid, ref p0); // <- Get IDXGIFactory as IntPtr
            var o = Marshal.GetObjectForIUnknown(p0); // <- IntPtr to RCW
            var i = (IDXGIFactory)o; // <- cast interface

            IDXGIAdapter a = null;
            i.EnumAdapters(0, ref a); // <- Get interface
            var desc = default(DXGI_ADAPTER_DESC);
            a.GetDesc(ref desc);

            Console.WriteLine(desc.Description);
        }
```

### for dlang

```
python pycpptool/run.py gen 'C:/Program Files (x86)/Windows Kits/10/Include/10.0.17763.0/shared/dxgi.h' '-i' 'dxgicommon.h' '-i' 'dxgiformat.h' '-i' 'dxgitype.h' '-o' '../windowskits/source' '-g' 'dlang'
```
