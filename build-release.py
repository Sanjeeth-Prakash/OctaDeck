"""Build the x64 Model Relay setup executable in a user-selected work directory."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.request import urlopen
import zipfile

SOURCE = Path(__file__).resolve().parent
PYTHON_VERSION = "3.13.17"
PYTHON_HASH = "9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38"
WEBVIEW_VERSION = "1.0.4370.26"
APP_FILES = (
    "app.py", "storage.py", "analytics.py", "routing.py", "playground.py", "voice.py",
    "health.py", "local_models.py", "speech.ps1", "index.html", "analytics.js",
    "providers.js", "studio.js", "voice.js",
)


def download(url, path, expected=None):
    if not path.exists():
        temporary = path.with_suffix(".download")
        with urlopen(url, timeout=60) as source, temporary.open("wb") as output:
            shutil.copyfileobj(source, output)
        if expected and hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
            temporary.unlink()
            raise ValueError("Downloaded runtime checksum mismatch.")
        temporary.replace(path)
    elif expected and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("Cached runtime checksum mismatch: " + str(path))
    return path


def package(root, staging):
    env = dict(os.environ, TEMP=str(staging), TMP=str(staging),
               PIP_CACHE_DIR=str(root/"pip-cache"))
    payload = staging/"payload"
    runtime, desktop, app = (payload/name for name in ("runtime","desktop","app"))
    for folder in (runtime,desktop,app):
        folder.mkdir(parents=True)
    archive = "python-" + PYTHON_VERSION + "-embed-amd64.zip"
    runtime_zip = download("https://www.python.org/ftp/python/"+PYTHON_VERSION+"/"+archive,
                           root/archive, PYTHON_HASH)
    with zipfile.ZipFile(runtime_zip) as source:
        source.extractall(runtime)
    (runtime/"python313._pth").write_text("python313.zip\n.\nLib\\site-packages\nimport site\n", encoding="ascii")
    subprocess.run([sys.executable,"-m","pip","install","--disable-pip-version-check",
                    "--only-binary=:all:","--platform","win_amd64","--python-version","3.13",
                    "--implementation","cp","--abi","cp313","--target",str(runtime/"Lib/site-packages"),
                    "-r",str(SOURCE/"requirements.txt")], env=env, check=True)
    for name in APP_FILES:
        shutil.copy2(SOURCE/name,app/name)
    shutil.copytree(SOURCE/"assets",app/"assets")
    sdk_name = "microsoft.web.webview2."+WEBVIEW_VERSION+".nupkg"
    sdk = download("https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/"+
                   WEBVIEW_VERSION+"/"+sdk_name, root/sdk_name)
    with zipfile.ZipFile(sdk) as source:
        for name in ("lib/net462/Microsoft.Web.WebView2.Core.dll","lib/net462/Microsoft.Web.WebView2.WinForms.dll",
                     "runtimes/win-x64/native/WebView2Loader.dll","LICENSE.txt"):
            (desktop/Path(name).name).write_bytes(source.read(name))
    compiler = Path(os.environ["WINDIR"])/"Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    flags = [str(compiler),"/nologo","/target:winexe","/platform:x64","/optimize+"]
    forms = "/reference:System.Windows.Forms.dll"
    refs = ["/reference:"+str(dll) for dll in sorted(desktop.glob("Microsoft.*.dll"))]
    subprocess.run([*flags,forms,"/reference:System.Drawing.dll",*refs,
                    "/out:"+str(desktop/"ModelRelay.exe"),str(SOURCE/"desktop.cs")],env=env,check=True)
    archive_path = staging/"payload.zip"
    with zipfile.ZipFile(archive_path,"w",zipfile.ZIP_DEFLATED) as output:
        for file in payload.rglob("*"):
            if file.is_file() and "__pycache__" not in file.parts:
                output.write(file,file.relative_to(payload).as_posix())
    setup = staging/"ModelRelay-Setup-x64.exe"
    subprocess.run([*flags,forms,"/reference:Microsoft.CSharp.dll",
                    "/reference:System.IO.Compression.dll","/reference:System.IO.Compression.FileSystem.dll",
                    "/resource:"+str(archive_path)+",payload.zip","/out:"+str(setup),
                    str(SOURCE/"setup-desktop.cs")],env=env,check=True)
    destination = root/setup.name
    setup.replace(destination)
    print(destination, hashlib.sha256(destination.read_bytes()).hexdigest())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True,type=Path)
    root = parser.parse_args().output.resolve()
    root.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix="build-",dir=root) as name:
        package(root,Path(name))
