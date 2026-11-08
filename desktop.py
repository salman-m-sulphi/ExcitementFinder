"""Native Windows window with a managed local analysis process."""
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import uuid

FROZEN = getattr(sys, 'frozen', False)
BASE = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
ASSETS = Path(__file__).resolve().parent


def storage_home():
    override = os.environ.get('EXCITEMENT_HOME')
    if override:
        return Path(override)
    location = BASE / 'storage-location.txt'
    if location.exists():
        saved = Path(location.read_text(encoding='utf-8').strip())
        if saved.is_dir():
            return saved
    return BASE / 'library' if FROZEN else BASE


def backend(state_file):
    import uvicorn
    from app import app
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    Path(state_file).write_text(json.dumps({'url': f'http://127.0.0.1:{port}', 'pid': os.getpid()}), encoding='utf-8')
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_config=None, access_log=False, ws='none'))
    server.run(sockets=[sock])


def message(text, title='Excitement Finder'):
    ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)


def main():
    import webview
    home = storage_home()
    home.mkdir(parents=True, exist_ok=True)
    logs = home / 'logs'
    logs.mkdir(exist_ok=True)
    state_file = logs / ('session-' + uuid.uuid4().hex + '.json')
    env = dict(os.environ, EXCITEMENT_HOME=str(home), HF_HUB_DISABLE_SYMLINKS_WARNING='1')
    bundled_models = BASE / 'library' / 'models'
    if not (home / 'models').exists() and bundled_models.exists():
        env['EXCITEMENT_MODELS'] = str(bundled_models)
    node = BASE / 'runtime' / 'node.exe'
    if node.exists():
        env['EXCITEMENT_NODE'] = str(node)
    command = [sys.executable, '--backend', str(state_file)] if FROZEN else [sys.executable, str(Path(__file__)), '--backend', str(state_file)]
    log_file = (logs / 'desktop.log').open('a', encoding='utf-8')
    child = subprocess.Popen(command, env=env, cwd=BASE, stdout=log_file, stderr=log_file, creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        url = None
        for _ in range(600):
            if child.poll() is not None:
                raise RuntimeError('The analysis engine did not start. See ' + str(logs / 'desktop.log'))
            if state_file.exists():
                try:
                    url = json.loads(state_file.read_text(encoding='utf-8'))['url']
                    urllib.request.urlopen(url + '/api/jobs', timeout=1).close()
                    break
                except (OSError, ValueError):
                    pass
            time.sleep(.1)
        else:
            raise RuntimeError('The analysis engine took too long to start. See ' + str(logs / 'desktop.log'))
        webview.settings['ALLOW_DOWNLOADS'] = True
        webview.settings['ALLOW_FILE_URLS'] = False
        from player_window import PlayerAPI, PlayerWindows
        players = PlayerWindows(url)
        main_api = PlayerAPI(players)
        window = webview.create_window('Excitement Finder v1.4.0', url, js_api=main_api, width=1320, height=900,
            min_size=(800, 650), background_color='#101413', text_select=True)
        main_api._window = window
        players.main = window
        window.events.closed += players.close_all

        def closing():
            try:
                result = json.load(urllib.request.urlopen(url + '/api/activity', timeout=2))
                busy = result['busy']
                if busy and not window.create_confirmation_dialog('Processing is running', 'Closing the application will stop the current analysis or clip export. Close anyway? You can retry it later.'):
                    return False
            except OSError:
                pass
            return True
        window.events.closing += closing

        if '--player-self-test' in sys.argv:
            import faulthandler
            (logs / 'player-test-pid.txt').write_text(str(os.getpid()))
            trace_file = (logs / 'player-thread-dump.log').open('w', encoding='utf-8')
            faulthandler.dump_traceback_later(25, repeat=True, file=trace_file)
            from player_self_test import run as player_test
            window.events.loaded += lambda: threading.Thread(target=player_test, args=(window,players,logs), daemon=True).start()

        # Opt-in end-to-end self-test of the built executable's actual WebView.
        if '--self-test' in sys.argv:
            def self_test():
                report = {'passed': False}
                try:
                    for _ in range(200):
                        if window.evaluate_js("document.querySelector('#history')?.textContent.includes('Open')"):
                            break
                        time.sleep(.1)
                    job = os.environ.get('EXCITEMENT_TEST_JOB')
                    if job:
                        window.evaluate_js(f'openResult({json.dumps(job)})')
                        for _ in range(300):
                            if window.evaluate_js('typeof data !== "undefined" && data !== null && document.querySelector("#video").readyState >= 1'):
                                break
                            time.sleep(.1)
                        report.update(window.evaluate_js('({title:data.title,words:data.words.length,bins:data.bins.length,language:data.language,mediaReady:document.querySelector("#video").readyState})'))
                        for _ in range(300):
                            if window.evaluate_js('typeof qualitiesReady !== "undefined" && qualitiesReady'):
                                break
                            time.sleep(.1)
                        report.update(window.evaluate_js('({sourceQuality:document.querySelector("#exportQuality").value,manualControlsReady:!!document.querySelector("#rangeIn")&&!!document.querySelector("#rangeOut"),manualRangeValid:readRange()!==null})'))
                        assert report['manualControlsReady'] and report['manualRangeValid'], report
                        window.evaluate_js('document.querySelector("#lead").value="0"; document.querySelector(".moment").click()')
                        time.sleep(1)
                        report['playback'] = window.evaluate_js('({time:document.querySelector("#video").currentTime,paused:document.querySelector("#video").paused,error:document.querySelector("#video").error?.message || null})')
                        assert not report['playback']['paused'] and not report['playback'].get('error'), report
                        window.evaluate_js('document.querySelector("#video").pause();document.querySelector("#workspace").scrollIntoView()')
                        report['passed'] = report['words'] > 0 and report['mediaReady'] >= 1
                    else:
                        report['passed'] = window.evaluate_js('document.title === "Excitement Finder"')
                except Exception:
                    report['error'] = traceback.format_exc()
                (logs / 'desktop-self-test.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
                if '--keep-open' not in sys.argv:
                    window.destroy()
            window.events.loaded += lambda: threading.Thread(target=self_test, daemon=True).start()
        webview.start(gui='edgechromium', storage_path=str(home / 'webview'), private_mode=False)
    finally:
        if child.poll() is None:
            subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
        state_file.unlink(missing_ok=True)
        log_file.close()


if __name__ == '__main__':
    try:
        if sys.stdout is None or sys.stderr is None:
            log_home = storage_home() / 'logs'
            log_home.mkdir(parents=True, exist_ok=True)
            stream = (log_home / 'runtime.log').open('a', encoding='utf-8', buffering=1)
            sys.stdout = sys.stdout or stream
            sys.stderr = sys.stderr or stream
        if (BASE / 'runtime' / 'node.exe').exists():
            os.environ.setdefault('EXCITEMENT_NODE', str(BASE / 'runtime' / 'node.exe'))
        if '--verify-youtube' in sys.argv:
            from yt_dlp import YoutubeDL
            pos = sys.argv.index('--verify-youtube')
            with YoutubeDL(dict(quiet=True, skip_download=True, noplaylist=True,
                js_runtimes={'node': {'path': os.environ['EXCITEMENT_NODE']}},
                format='bv*[height<=720][vcodec^=avc1]+ba[ext=m4a]/b')) as ydl:
                info = ydl.extract_info(sys.argv[pos + 1], download=False)
            Path(sys.argv[pos + 2]).write_text(json.dumps(dict(passed=True, title=info['title'], duration=info['duration'], formats=len(info['formats']))), encoding='utf-8')
        elif '--backend' in sys.argv:
            backend(sys.argv[sys.argv.index('--backend') + 1])
        else:
            main()
    except Exception:
        if '--backend' in sys.argv:
            traceback.print_exc()
        else:
            message(traceback.format_exc() + '\n\nRequires the Microsoft Edge WebView2 Runtime. Download: https://developer.microsoft.com/microsoft-edge/webview2/')
        sys.exit(1)
