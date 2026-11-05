"""Publish the tested build using this repository's short-lived Actions token."""
from pathlib import Path
import json,os,re,subprocess,urllib.request
root=Path(__file__).resolve().parents[1]
repo=os.environ['GITHUB_REPOSITORY']
token=os.environ['GH_TOKEN']
base='https://api.github.com/repos/'+repo
def api(path,data=None,method=None):
    request=urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','Content-Type':'application/json'},method=method)
    with urllib.request.urlopen(request,timeout=60) as response:return json.load(response)
body=(root/'release/NOTES.md').read_text(encoding='utf-8')
version=(root/'VERSION').read_text().strip()
if not re.fullmatch(r'\d+\.\d+\.\d+',version):raise ValueError('Invalid release version')
tag='v'+version
if api('/commits/main')['sha'] != os.environ['GITHUB_SHA']:
    raise RuntimeError('A newer source revision exists; refusing to publish a superseded build')
payload=dict(tag_name=tag,target_commitish=os.environ['GITHUB_SHA'],name='Excitement Finder '+tag+' — Windows',body=body,draft=True,prerelease=False)
existing=next((r for r in api('/releases') if r['tag_name']==tag),None)
if existing and not existing['draft']:raise RuntimeError('This version is already published; increment VERSION')
release=api('/releases/'+str(existing['id']),payload,'PATCH') if existing else api('/releases',payload,'POST')
subprocess.run(['gh','release','upload',tag,*[str(p) for p in sorted((root/'release-artifacts').iterdir())],'--repo',repo,'--clobber'],check=True)
api('/releases/'+str(release['id']),{'draft':False,'make_latest':'true'},'PATCH')
print('Published '+release['html_url'])
