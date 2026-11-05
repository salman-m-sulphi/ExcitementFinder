/* One playback owner, whether the player is inline, docked, or in a window. */
(function(root){
  function momentAt(events, seconds, preferred){
    if(!Number.isFinite(seconds))return null;
    const inside=e=>seconds>=e.start&&seconds<e.end;
    return events.find(e=>e.key===preferred&&inside(e))||events.find(inside)||null;
  }
  function displayAt(events,seconds,selection){
    const selected=events.find(e=>e.key===selection?.key);
    if(selected&&Number.isFinite(seconds)&&Number.isFinite(selection?.leadStart)&&seconds>=selection.leadStart&&seconds<selected.start){
      return {mode:'lead-in',moment:selected,remaining:Math.ceil(selected.start-seconds)};
    }
    const active=momentAt(events,seconds,selection?.key);
    return {mode:active?'event':'none',moment:active};
  }
  if(typeof module!=='undefined'&&module.exports){module.exports={momentAt,displayAt};return}
  const video=document.querySelector('#video'),dock=document.querySelector('#playerDock'),anchor=document.querySelector('#playerAnchor');
  const badge=document.querySelector('#currentMoment'),status=document.querySelector('#playerStatus');
  const params=new URLSearchParams(location.search),popout=params.get('player')==='window';
  let events=[],preferred=null,job=null,channel=null,token=null,remoteTime=0,external=false,pending=false;
  let popup=null,clock=()=>{},dismissed=false,returning=false,nativeFullscreen=false,ownerEvents=false,returned=false;
  let remoteState={};
  let selectionLeadStart=null,seekRevision=0;
  let raf=0,handshakeTimer=null,lastState=0;
  if(popout){document.documentElement.classList.add('popout-mode');document.body.append(dock)}
  function native(){return root.pywebview?.api}
  function report(message){status.textContent=message;status.hidden=!message}
  function send(message){channel?.postMessage({...message,job})}
  function currentTime(){return external?remoteTime:video.currentTime}
  function update(){
    const t=currentTime(),display=displayAt(events,t,{key:preferred,leadStart:selectionLeadStart});
    const active=display.mode==='event'?display.moment:null;
    const chosen=events.find(e=>e.key===preferred);
    if(!chosen||t>=chosen.start)selectionLeadStart=null;
    const text=display.mode==='lead-in'?`Selected moment #${display.moment.number} · starts in ${display.remaining}s (lead-in)`:active?`Moment #${active.number} · ${format(active.start)}–${format(active.end)}`:'';
    if(badge.textContent!==text)badge.textContent=text;
    badge.hidden=display.mode==='none';badge.classList.toggle('lead-in',display.mode==='lead-in');
    for(const row of document.querySelectorAll('.moment')){
      const playing=!!active&&row.dataset.momentKey===active.key;
      row.classList.toggle('playing',playing);
      row.classList.toggle('pending-moment',display.mode==='lead-in'&&row.dataset.momentKey===display.moment.key);
      if(playing)row.setAttribute('aria-current','true');else row.removeAttribute('aria-current');
    }
    if(popout&&active)document.title=`Moment #${active.number} — Excitement Finder`;
    else if(popout)document.title='Floating player — Excitement Finder';
  }
  function format(s){const total=Math.floor(s);return total>=3600?`${Math.floor(total/3600)}:${String(Math.floor(total/60)%60).padStart(2,'0')}:${String(total%60).padStart(2,'0')}`:`${Math.floor(total/60)}:${String(total%60).padStart(2,'0')}`}
  function setEvents(picks,fromOwner=false){
    if(popout&&ownerEvents&&!fromOwner)return;
    if(fromOwner)ownerEvents=true;
    events=picks.map((p,i)=>({start:p.start,end:p.end,number:p.number||i+1,key:`${p.start}:${p.end}`}));
    update();
    if(!popout&&(external||pending))send({type:'events',events,preferred,leadStart:selectionLeadStart});
  }
  function setContext(id,onClock){
    if(id===job){clock=onClock;return}
    if(channel){send({type:'shutdown'});channel.close()}
    clearTimeout(handshakeTimer);events=[];preferred=null;selectionLeadStart=null;seekRevision=0;job=id;clock=onClock;external=false;pending=false;ownerEvents=false;returned=false;dismissed=false;
    document.querySelector('#externalCover').hidden=true;
    token=popout?params.get('channel'):crypto.randomUUID();
    if(!/^[a-f0-9-]{36}$/.test(token||'')){report('This floating-player link is invalid. Open the player from the main app.');return}
    channel=new BroadcastChannel(`excitement-player-${token}`);
    channel.onmessage=receive;
    update();position();
  }
  function playFrom(seconds,key){
    preferred=key||null;dismissed=false;
    const chosen=events.find(e=>e.key===preferred);selectionLeadStart=chosen&&seconds<chosen.start?seconds:null;seekRevision++;
    if(external){remoteTime=seconds;send({type:'command',command:'seek',time:seconds,play:true,preferred,leadStart:selectionLeadStart,revision:seekRevision})}
    else {video.currentTime=seconds;video.play().catch(()=>{})}
    update();position();
  }
  function seekTo(seconds){
    preferred=null;selectionLeadStart=null;seekRevision++;
    if(external){remoteTime=seconds;send({type:'command',command:'seek',time:seconds,preferred,leadStart:null,revision:seekRevision})}
    else video.currentTime=seconds;
    update();clock();
  }
  function pause(){if(external)send({type:'command',command:'pause'});else video.pause()}
  function clear(){
    send({type:'shutdown'});channel?.close();channel=null;job=null;events=[];external=false;pending=false;preferred=null;selectionLeadStart=null;
    clearTimeout(handshakeTimer);video.pause();document.querySelector('#externalCover').hidden=true;report('');update();position();
  }
  function receive({data:message}){
    if(!message||message.job!==job)return;
    if(popout){
      if(message.type==='state'){
        preferred=message.preferred;selectionLeadStart=message.leadStart??null;seekRevision=message.revision;setEvents(message.events,true);
        video.currentTime=Math.max(0,Math.min(video.duration||Infinity,message.time));
        video.volume=message.volume;video.muted=message.muted;video.playbackRate=message.rate;
        if(message.paused)video.pause();else video.play().catch(()=>report('Press Play to continue in this window.'));
        update();
      }else if(message.type==='events'){preferred=message.preferred;selectionLeadStart=message.leadStart??null;setEvents(message.events,true)}
      else if(message.type==='command'){
        if(message.command==='seek'){preferred=message.preferred;selectionLeadStart=message.leadStart??null;seekRevision=message.revision;video.currentTime=message.time;if(message.play)video.play().catch(()=>{})}
        if(message.command==='return')closeWindow();
        if(message.command==='pause')video.pause();
        if(message.command==='fullscreen')fullscreen();
      }else if(message.type==='shutdown'){returned=true;video.pause();if(native()?.close_player_window)native().close_player_window();else root.close()}
    }else if(message.type==='ready'&&pending){
      clearTimeout(handshakeTimer);const paused=video.paused;
      remoteTime=video.currentTime;remoteState={time:remoteTime,paused,volume:video.volume,muted:video.muted,rate:video.playbackRate};video.pause();external=true;pending=false;
      document.querySelector('#externalCover').hidden=false;
      send({type:'state',time:remoteTime,paused,volume:video.volume,muted:video.muted,rate:video.playbackRate,events,preferred,leadStart:selectionLeadStart,revision:seekRevision});
      report('Playback is in the floating window.');position();update();
    }else if(message.type==='tick'&&external&&message.revision===seekRevision){remoteTime=message.time;remoteState=message;update();clock()}
    else if(message.type==='return'&&(external||pending)){
      clearTimeout(handshakeTimer);external=false;pending=false;remoteTime=message.time;
      document.querySelector('#externalCover').hidden=true;video.currentTime=message.time;
      video.volume=message.volume;video.muted=message.muted;video.playbackRate=message.rate;
      if(!message.paused)video.play().catch(()=>{});else video.pause();
      popup=null;report('');position();update();clock();
    }
  }
  function returnToApp(){
    if(!popout||returned)return;
    returned=true;const paused=video.paused;
    send({type:'return',time:video.currentTime,paused,volume:video.volume,muted:video.muted,rate:video.playbackRate});
    video.pause();
  }
  function windowClosed(closedJob,closedToken){
    if(!popout&&job===closedJob&&token===closedToken&&external)receive({data:{...remoteState,type:'return',job}});
  }
  function closeWindow(){returnToApp();if(native()?.close_player_window)native().close_player_window();else root.close()}
  async function openWindow(){
    if(popout){closeWindow();return}
    if(!job||pending)return;
    if(external){if(native()?.open_player_window)await native().open_player_window(job,token);else popup?.focus();return}
    // A fresh channel per window prevents a delayed close notification from
    // an older pop-out from taking ownership away from a newly opened one.
    send({type:'shutdown'});channel?.close();token=crypto.randomUUID();
    channel=new BroadcastChannel(`excitement-player-${token}`);channel.onmessage=receive;
    pending=true;report('Opening floating window…');
    try{
      const url=new URL(location.href);url.search=`?player=window&channel=${token}`;url.hash=job;
      if(native()?.open_player_window)await native().open_player_window(job,token);
      else {popup=root.open(url.href,'_blank','popup,width=660,height=480');if(!popup)throw Error('Your browser blocked the window. Allow pop-ups for this local app and try again.')}
      handshakeTimer=setTimeout(()=>{if(pending){pending=false;report('The floating window did not connect. Playback remains in this player.')}},20000);
    }catch(error){pending=false;report(error.message||'Could not open a floating window.')}
  }
  function position(){
    if(popout)return;
    const rect=anchor.getBoundingClientRect(),visible=rect.bottom>90&&rect.top<innerHeight;
    if(visible){dismissed=false;returning=false}
    const floating=!!job&&!external&&!dismissed&&!returning&&!nativeFullscreen&&!document.fullscreenElement&&rect.bottom<=90;
    if(floating&&!dock.classList.contains('floating'))anchor.style.minHeight=`${dock.getBoundingClientRect().height+22}px`;
    dock.classList.toggle('floating',floating);
    if(!floating&&!nativeFullscreen&&!document.fullscreenElement)anchor.style.minHeight='';
  }
  function back(){dismissed=false;returning=true;dock.classList.remove('floating');anchor.style.minHeight='';anchor.scrollIntoView({behavior:'smooth',block:'center'})}
  async function fullscreen(){
    if(external){send({type:'command',command:'fullscreen'});return}
    try{
      if(native()?.set_player_fullscreen){nativeFullscreen=await native().set_player_fullscreen(!nativeFullscreen);document.body.classList.toggle('native-player-fullscreen',nativeFullscreen)}
      else if(document.fullscreenElement)await document.exitFullscreen();else await dock.requestFullscreen();
      syncFullscreen();position();
    }catch(error){report('Fullscreen is unavailable in this window. '+error.message)}
  }
  function syncFullscreen(){document.querySelector('#playerFullscreen').textContent=(nativeFullscreen||document.fullscreenElement)?'Exit fullscreen':'Fullscreen'}
  document.querySelector('#playerPopout').onclick=openWindow;
  document.querySelector('#playerFullscreen').onclick=fullscreen;
  document.querySelector('#playerReturn').onclick=back;
  document.querySelector('#playerClose').onclick=()=>{dismissed=true;dock.classList.remove('floating');anchor.style.minHeight=''};
  document.querySelector('#externalReturn').onclick=()=>send({type:'command',command:'return'});
  if(popout){document.querySelector('#playerPopout').textContent='Return to app';document.querySelector('#playerPopout').title='Continue in the main app'}
  video.addEventListener('loadedmetadata',()=>{if(popout)send({type:'ready'});position()});
  for(const event of ['timeupdate','seeked','play','pause','ended','volumechange','ratechange'])video.addEventListener(event,()=>{
    update();
    if(popout&&(event!=='timeupdate'||performance.now()-lastState>150)){lastState=performance.now();send({type:'tick',time:video.currentTime,paused:video.paused,volume:video.volume,muted:video.muted,rate:video.playbackRate,revision:seekRevision})}
  });
  video.addEventListener('dblclick',fullscreen);
  document.addEventListener('fullscreenchange',()=>{syncFullscreen();position()});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&nativeFullscreen){event.preventDefault();fullscreen()}});
  root.addEventListener('scroll',()=>{if(!raf)raf=requestAnimationFrame(()=>{raf=0;position()})},{passive:true});
  root.addEventListener('resize',position);
  root.addEventListener('beforeunload',()=>{if(popout)returnToApp();else send({type:'shutdown'})});
  setInterval(()=>{if(!popout&&external&&popup?.closed)windowClosed(job,token)},1000);
  root.ExcitementPlayer={momentAt,setContext,setEvents,playFrom,seekTo,pause,clear,currentTime,update,returnToApp,windowClosed,fullscreen,openWindow};
})(globalThis);
