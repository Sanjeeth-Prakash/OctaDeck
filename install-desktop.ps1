param([string]$InstallRoot = 'G:\softwares\Models\OctaDeck')

$ErrorActionPreference = 'Stop'
$source = $PSScriptRoot
$runtime = Join-Path ${env:ProgramFiles(x86)} 'Microsoft\EdgeWebView\Application'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $compiler) -or -not (Test-Path -LiteralPath $runtime)) {
    throw 'Install the x64 .NET Framework and Microsoft Edge WebView2 Runtime first.'
}

$desktop = New-Item -ItemType Directory -Force -Path (Join-Path $InstallRoot 'desktop')
$env:TEMP = (New-Item -ItemType Directory -Force -Path (Join-Path $InstallRoot 'temp')).FullName
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = (New-Item -ItemType Directory -Force -Path (Join-Path $InstallRoot 'pip-cache')).FullName
$python = Join-Path $InstallRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    & python -m venv (Join-Path $InstallRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed.' }
}
& $python -m pip install --disable-pip-version-check -r (Join-Path $source 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }

$version = '1.0.4370.26'
$package = "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/$version/microsoft.web.webview2.$version.nupkg"
$core = Join-Path $desktop.FullName 'Microsoft.Web.WebView2.Core.dll'
$forms = Join-Path $desktop.FullName 'Microsoft.Web.WebView2.WinForms.dll'
$loader = Join-Path $desktop.FullName 'WebView2Loader.dll'
if (-not ((Test-Path -LiteralPath $core) -and (Test-Path -LiteralPath $forms) -and (Test-Path -LiteralPath $loader))) {
    $download = Join-Path $env:TEMP "webview2-$version.zip"
    Invoke-WebRequest -UseBasicParsing -Uri $package -OutFile $download
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($download)
    try {
        foreach ($entry in @('lib/net462/Microsoft.Web.WebView2.Core.dll','lib/net462/Microsoft.Web.WebView2.WinForms.dll','runtimes/win-x64/native/WebView2Loader.dll','LICENSE.txt')) {
            [IO.Compression.ZipFileExtensions]::ExtractToFile($archive.GetEntry($entry), (Join-Path $desktop.FullName ([IO.Path]::GetFileName($entry))), $true)
        }
    } finally { $archive.Dispose() }
}

$exe = Join-Path $desktop.FullName 'OctaDeck.exe'
$icon = Join-Path $source 'assets\octadeck.ico'
& $compiler /nologo /target:winexe /platform:x64 /optimize+ "/out:$exe" "/win32icon:$icon" "/reference:$core" "/reference:$forms" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll (Join-Path $source 'desktop.cs')
if ($LASTEXITCODE -ne 0) { throw 'Desktop host compilation failed.' }

$linkPath = Join-Path $InstallRoot 'OctaDeck.lnk'
$link = (New-Object -ComObject WScript.Shell).CreateShortcut($linkPath)
$link.TargetPath = $exe
$link.Arguments = '"' + $source + '"'
$link.WorkingDirectory = $desktop.FullName
$link.IconLocation = "$exe,0"
$link.Description = 'Open OctaDeck'
$link.Save()
Write-Host $linkPath
