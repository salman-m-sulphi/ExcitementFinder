"""Build a portable Windows folder, including Python, decoder, model and Node."""
from pathlib import Path
import shutil
import subprocess
import sys
import os
import urllib.request

root = Path(__file__).resolve().parent
workspace = root
dist = Path(os.environ.get('EXCITEMENT_BUILD_DIST', str(root / 'dist')))
work = workspace / 'work' / 'desktop-build'
work.mkdir(parents=True, exist_ok=True)
if not work.resolve().is_relative_to(workspace.resolve()):
    raise RuntimeError('Build intermediates must stay inside the workspace')
staging = work / 'staging'
args = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir', '--windowed',
        '--icon', str(root / 'app.ico'),
        '--name', 'ExcitementFinder', '--distpath', str(staging), '--workpath', str(work / 'build'),
        '--specpath', str(work), '--add-data', str(root / 'static') + ';static',
        '--collect-all', 'faster_whisper', '--collect-all', 'ctranslate2',
        '--collect-all', 'onnxruntime', '--collect-all', 'av', '--collect-all', 'imageio_ffmpeg',
        '--collect-all', 'yt_dlp_ejs', '--collect-submodules', 'yt_dlp',
        '--collect-all', 'sherpa_onnx', '--collect-all', 'sherpa_onnx_core',
        '--collect-all', 'webview', '--collect-all', 'pythonnet', '--collect-all', 'clr_loader',
        '--collect-submodules', 'uvicorn', '--copy-metadata', 'tqdm',
        '--exclude-module', 'matplotlib', '--exclude-module', 'tkinter', '--exclude-module', 'PyQt5',
        '--exclude-module', 'PyQt6', '--exclude-module', 'PySide6', str(root / 'desktop.py')]
vulkan = root / 'whisper_vulkan'
if os.environ.get('GITHUB_ACTIONS') == 'true' and not vulkan.is_dir():
    subprocess.run([sys.executable, str(root / 'release' / 'fetch_vulkan.py')], check=True)
if vulkan.is_dir():
    args[-1:-1] = ['--add-data', str(vulkan) + ';whisper_vulkan']
subprocess.run(args, cwd=root, check=True)
app = dist / 'ExcitementFinder'
# Copy the staged program over the existing installation without deleting its
# library. Never let PyInstaller's --noconfirm remove a user's portable data.
shutil.copytree(staging / 'ExcitementFinder', app, dirs_exist_ok=True)
(app / 'runtime').mkdir(exist_ok=True)
node = shutil.which('node')
if not node:
    raise RuntimeError('Node.js is required when building the bundled YouTube importer')
shutil.copy2(node, app / 'runtime' / 'node.exe')
node_license = Path(node).with_name('LICENSE')
if node_license.exists():
    shutil.copy2(node_license, app / 'runtime' / 'NODE-LICENSE.txt')
else:
    node_version = subprocess.check_output([node, '--version'], text=True).strip()
    with urllib.request.urlopen('https://raw.githubusercontent.com/nodejs/node/' + node_version + '/LICENSE', timeout=30) as response:
        (app / 'runtime' / 'NODE-LICENSE.txt').write_bytes(response.read())
def skip_optional_models(directory, names):
    if Path(directory) == root / 'models':
        return [name for name in names if name in ('.locks', 'vulkan') or
                (name.startswith('models--') and name != 'models--Systran--faster-whisper-tiny')]
    return []

shutil.copytree(root / 'models', app / 'library' / 'models', dirs_exist_ok=True, ignore=skip_optional_models)
for name in ['LICENSE','NOTICE','THIRD_PARTY_NOTICES.txt','README.md','DOWNLOADS.md','PLAYER.md','GPU.md','VERSION']:
    shutil.copy2(root/name,app/name)
print('Built:', app / 'ExcitementFinder.exe')
