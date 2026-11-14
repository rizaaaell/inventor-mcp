param([string]$Pdf, [string]$OutDir, [int]$Width = 2000, [int]$MaxPages = 3)
# Render PDF pages to PNG with the Windows built-in PDF engine (Windows.Data.Pdf).
# StorageFile only takes absolute Windows paths.
$Pdf = (Resolve-Path $Pdf).Path
$OutDir = [IO.Path]::GetFullPath($OutDir)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [type]$t) {
    $task = $asTaskGeneric.MakeGenericMethod($t).Invoke($null, @($op))
    $task.Wait() | Out-Null
    $task.Result
}
function AwaitAction($op) {
    $m = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
    $m.Invoke($null, @($op)).Wait() | Out-Null
}

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Pdf)) ([Windows.Storage.StorageFile])
$doc = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
New-Item -ItemType Directory -Force $OutDir | Out-Null
$base = [IO.Path]::GetFileNameWithoutExtension($Pdf)
$n = [Math]::Min($doc.PageCount, $MaxPages)
"pages {0} (rendering {1})" -f $doc.PageCount, $n
for ($i = 0; $i -lt $n; $i++) {
    $page = $doc.GetPage($i)
    $opts = New-Object Windows.Data.Pdf.PdfPageRenderOptions
    $opts.DestinationWidth = $Width
    $stream = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
    AwaitAction ($page.RenderToStreamAsync($stream, $opts))
    $out = Join-Path $OutDir ("{0}_p{1}.png" -f $base, ($i + 1))
    $net = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream.GetInputStreamAt(0))
    $fs = [IO.File]::Create($out); $net.CopyTo($fs); $fs.Close()
    "{0}  {1:N0} x {2:N0} pt" -f $out, $page.Size.Width, $page.Size.Height
}
