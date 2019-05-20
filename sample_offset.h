struct DXGI_RATIONAL
{
    float x;
    float y;
};
struct DXGI_MODE_DESC
{
    int Width;
    int Height;
    DXGI_RATIONAL RefreshRate;
    int Format;
    int ScanlineOrdering;
    int Scaling;
};
struct DXGI_SAMPLE_DESC
{
    int Count;
    int Quality;
};
struct DXGI_SWAP_CHAIN_DESC
{
    DXGI_MODE_DESC BufferDesc;
    DXGI_SAMPLE_DESC SampleDesc;
    int BufferUsage;
    int BufferCount;
    void *OutputWindow;
    int Windowed;
    int SwapEffect;
    int Flags;
};