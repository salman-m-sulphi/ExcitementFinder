"""Prepare a clean, self-contained release on Windows."""
from pathlib import Path
import hashlib, shutil, subprocess, zipfile

root = Path(__file__).resolve().parents[1]
app = root / 'dist/ExcitementFinder'
out = root / 'release-artifacts'
out.mkdir(exist_ok=True)
for name in ['LICENSE','NOTICE','THIRD_PARTY_NOTICES.txt','README.md','DOWNLOADS.md','CHANGELOG.md','VERIFICATION.md','PLAYER.md','VERSION']:
    shutil.copy2(root/name,app/name)
archive = out/'ExcitementFinder-Windows.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=5) as z:
    for p in app.rglob('*'):
        if not p.is_file():continue
        relative=p.relative_to(app)
        if relative.name=='storage-location.txt' or relative.parts[:2] in [('library','data'),('library','logs'),('library','webview')]:continue
        z.write(p,Path('ExcitementFinder')/relative)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for name in ['ExcitementFinder.exe','LICENSE','library/models/speakers/embedding.onnx','library/models/speakers/segmentation.onnx']:
        assert 'ExcitementFinder/'+name in z.namelist(),name
source=out/'ExcitementFinder-Source.zip'
paths=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
with zipfile.ZipFile(source,'w',zipfile.ZIP_DEFLATED) as z:
    for name in paths:
        if name:z.write(root/name,'ExcitementFinder/'+name)
(out/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in [archive,source]))
print('Prepared and validated release archives')
