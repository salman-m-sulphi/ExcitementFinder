"""Exercise the actual frozen Windows engine, including local speaker inference."""
from pathlib import Path
import json,os,subprocess,tempfile,time
import httpx
root=Path(__file__).resolve().parents[1]
app=Path(os.environ.get('EXCITEMENT_SMOKE_APP',str(root/'dist/ExcitementFinder'))).resolve()
with tempfile.TemporaryDirectory() as temporary:
    home=Path(temporary)
    state=home/'session.json'
    env=dict(os.environ,EXCITEMENT_HOME=str(home),EXCITEMENT_MODELS=str(app/'library/models'))
    process=subprocess.Popen([str(app/'ExcitementFinder.exe'),'--backend',str(state)],env=env,cwd=app)
    try:
        for _ in range(300):
            if state.exists():break
            if process.poll() is not None:raise RuntimeError('Frozen engine exited early')
            time.sleep(.2)
        url=json.loads(state.read_text())['url']
        with httpx.Client(base_url=url,timeout=30) as client:
            for _ in range(100):
                try:
                    assert client.get('/api/activity').status_code==200
                    break
                except httpx.TransportError:time.sleep(.2)
            response=client.post('/api/jobs',files={'file':('speech.wav',(root/'tests/fixtures/synthetic-commentary.wav').read_bytes(),'audio/wav')},data={'model':'none'})
            response.raise_for_status();job=response.json()['id']
            for _ in range(600):
                status=client.get('/api/jobs/'+job).json()
                if status['status'] in ('done','error'):break
                time.sleep(.2)
            assert status['status']=='done',status
            result=client.get('/api/jobs/'+job+'/result').json()
            assert result['scoring_revision']==2,result
            assert result['speakers']['detected_speakers']>=1,result.get('warnings')
            assert result['speakers']['calibrated_speakers']>=1,result.get('warnings')
            assert 'events.js' in client.get('/').text
            print(json.dumps(dict(frozen_engine='passed',speakers=result['speakers']['detected_speakers'],calibrated=result['speakers']['calibrated_speakers'])))
    finally:
        process.terminate()
        process.wait(timeout=20)
