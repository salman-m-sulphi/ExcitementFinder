"""Opt-in functional checks inside the real Windows WebView (no user data edits)."""
import json
import os
import time
import traceback


def run(window, players, logs):
    report = {'passed': False}
    def wait_for(check, description, seconds=25):
        report['stage']=description
        (logs/'player-self-test-progress.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            try:
                value=check()
                if value:return value
            except Exception:
                pass
            time.sleep(.15)
        raise AssertionError(description)
    try:
        job=os.environ['EXCITEMENT_TEST_JOB']
        window.evaluate_js('openResult('+json.dumps(job)+')')
        wait_for(lambda:window.evaluate_js('typeof data!=="undefined" && data && document.querySelector("#video").readyState>=1 && ranked().length>=28'),'Loaded recording and numbered moments')
        target=window.evaluate_js('ranked()[24]')
        report['target']=target
        window.evaluate_js('document.querySelectorAll(".moment")[24].click()')
        wait_for(lambda:window.evaluate_js('!document.querySelector("#video").paused'),'Clicking a moment plays the recording')
        # Lead-in can be in another event, but must not prematurely label #24.
        report['lead_in_label']=window.evaluate_js('document.querySelector("#currentMoment").textContent')
        assert 'Selected moment #25' in report['lead_in_label'],report['lead_in_label']
        window.evaluate_js('document.querySelector("#video").currentTime='+str(target['start']+.25))
        wait_for(lambda:window.evaluate_js('document.querySelector("#currentMoment").textContent.includes("Moment #25 ·")'),'Selected event number follows the playhead')
        report['detected_label']=window.evaluate_js('document.querySelector("#currentMoment").textContent')
        window.evaluate_js('document.querySelector("#video").currentTime='+str(target['end']+.1))
        wait_for(lambda:window.evaluate_js('!document.querySelector("#currentMoment").textContent.includes("Moment #25 ·")'),'Number clears at the detected out point')
        assert window.evaluate_js('!document.querySelector("#video").paused'),'Playback must continue beyond the detected event'
        window.evaluate_js('document.querySelector("#video").currentTime='+str(target['start']+.25)+';window.scrollTo(0,document.body.scrollHeight)')
        wait_for(lambda:window.evaluate_js('document.querySelector("#playerDock").classList.contains("floating")'),'Corner player follows scrolling')
        report['corner_player']=True
        # Keep a stable playhead while testing window handoff, then resume there.
        window.evaluate_js('document.querySelector("#video").pause();document.querySelector("#video").currentTime='+str(target['start']+.3))
        time.sleep(.2)
        window.evaluate_js('document.querySelector("#playerPopout").click()')
        child=wait_for(lambda:players._child,'Separate native player window opens')
        wait_for(lambda:window.evaluate_js('!document.querySelector("#externalCover").hidden'),'Playback ownership transfers to floating window')
        wait_for(lambda:child.evaluate_js('document.querySelector("#currentMoment").textContent.includes("Moment #25 ·")'),'Floating window retains the moment number')
        assert child.on_top,'Floating window stays on top'
        assert window.evaluate_js('document.querySelector("#video").paused'),'Main player stays silent'
        child.evaluate_js('document.querySelector("#video").play()')
        wait_for(lambda:child.evaluate_js('!document.querySelector("#video").paused'),'Floating window can play')
        report['native_floating_window']=True
        window.evaluate_js('document.querySelectorAll(".moment")[27].click()')
        wait_for(lambda:child.evaluate_js('document.querySelector("#currentMoment").textContent.includes("Selected moment #28")'),'A new selection replaces the old floating-window number during lead-in')
        window.evaluate_js('document.querySelectorAll(".moment")[24].click()')
        wait_for(lambda:child.evaluate_js('document.querySelector("#currentMoment").textContent.includes("Selected moment #25")'),'Rapid reselection keeps the latest clicked number')
        child.evaluate_js('document.querySelector("#video").currentTime='+str(target['start']+.3))
        wait_for(lambda:child.evaluate_js('document.querySelector("#currentMoment").textContent.includes("Moment #25 ·")'),'Floating window enters the selected detected event')
        report['floating_reselection']=True
        child.evaluate_js('document.querySelector("#playerFullscreen").click()')
        wait_for(lambda:child.evaluate_js('document.body.classList.contains("native-player-fullscreen")'),'Floating window enters native fullscreen')
        report['fullscreen_size']=[child.width,child.height]
        child.evaluate_js('document.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape"}))')
        wait_for(lambda:not child.evaluate_js('document.body.classList.contains("native-player-fullscreen")'),'Escape exits fullscreen')
        return_at=child.evaluate_js('document.querySelector("#video").currentTime')
        child.evaluate_js('document.querySelector("#playerPopout").click()')
        wait_for(lambda:players._child is None,'Returning closes only the child window')
        wait_for(lambda:window.evaluate_js('document.querySelector("#externalCover").hidden && !document.querySelector("#video").paused'),'Main player resumes after return')
        resumed=window.evaluate_js('document.querySelector("#video").currentTime')
        assert abs(resumed-return_at)<2, (resumed,return_at)
        report['returned_playhead_delta']=round(resumed-return_at,3)
        window.evaluate_js('document.querySelector("#playerPopout").click()')
        child=wait_for(lambda:players._child,'Reopen floating player')
        wait_for(lambda:window.evaluate_js('!document.querySelector("#externalCover").hidden'),'Second window handoff completes')
        child.destroy()  # Same native closing path as the window's X control.
        wait_for(lambda:players._child is None,'OS window close completes without blocking the UI')
        wait_for(lambda:window.evaluate_js('document.querySelector("#externalCover").hidden'),'OS close returns playback to the app')
        report['os_close_returns_player']=True
        window.evaluate_js('document.querySelector("#video").pause()')
        report['passed']=True
    except Exception:
        report['error']=traceback.format_exc()
    finally:
        (logs/'player-self-test.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        players.close_all()
        window.destroy()
