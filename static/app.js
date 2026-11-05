const $ = s => document.querySelector(s);
const labels = {pace:'Word pace',surge:'Volume surge',loudness:'Relative loudness',speech:'Speech activity',change:'Abrupt sound changes'};
const hints = {pace:'Word pace above this commentator’s typical delivery',surge:'Rise above this commentator’s own level; uncertain speech is excluded',loudness:'Loudness above this commentator’s usual level',speech:'Silero speech detection; not an emotion classifier',change:'Spectral changes, including impacts, music, or crowd noise'};
let data=null, scores=[], weights={}, currentJob=null, pollTimer=null, selected=0, transcriptRows=[];
let exportBusy=false;
let failedDownload=null;
let qualitiesReady=false, rangePreview=false;
const momentLength=()=>Number($('#clipLength').value);
const time = s => {s=Math.max(0,Math.floor(s||0));return s>=3600?`${Math.floor(s/3600)}:${String(Math.floor(s/60)%60).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`:`${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`};
function element(tag,cls,text){let e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e}
async function api(url,opts){const r=await fetch(url,opts);if(!r.ok){let e;try{e=await r.json()}catch{}throw Error(e?.detail||`Request failed (${r.status})`)}return r.json()}
function error(e){$('#error').hidden=false;$('#error').textContent=e.message||String(e)}
$('#language').onchange=()=>{$('#customLanguage').hidden=$('#language').value!=='other'};
$('#file').onchange=()=>{$('#fileLabel').textContent=$('#file').files[0]?.name||'Choose a file or drop it here';if($('#file').files.length)$('#url').value=''};
$('#url').oninput=()=>{if($('#url').value){$('#file').value='';$('#fileLabel').textContent='Choose a file or drop it here'}};
for(const event of ['dragenter','dragover'])$('#drop').addEventListener(event,e=>{e.preventDefault();$('#drop').classList.add('over')});
for(const event of ['dragleave','drop'])$('#drop').addEventListener(event,e=>{e.preventDefault();$('#drop').classList.remove('over');if(event==='drop'&&e.dataTransfer.files.length){$('#file').files=e.dataTransfer.files;$('#file').onchange()}});
$('#uploadForm').onsubmit=async e=>{e.preventDefault();$('#error').hidden=true;const form=new FormData();const f=$('#file').files[0];if(f&&f.size>8*1024**3)return error(Error('File exceeds 8 GiB. Choose a smaller recording.'));if(f)form.append('file',f);else form.append('url',$('#url').value);form.append('model',$('#model').value);form.append('language',$('#language').value==='other'?$('#customLanguage').value.trim().toLowerCase():$('#language').value);$('#analyze').disabled=true;$('#status').hidden=false;$('#statusText').textContent='Uploading to the local backend…';$('#percent').textContent='';$('#progress').removeAttribute('value');try{let job=await api('/api/jobs',{method:'POST',body:form});watch(job.id)}catch(e){error(e);$('#analyze').disabled=false;$('#status').hidden=true}};
function watch(id){currentJob=id;clearTimeout(pollTimer);async function tick(){try{const s=await api(`/api/jobs/${id}`);$('#status').hidden=false;$('#statusText').textContent=s.message;$('#percent').textContent=`${s.progress}%`;$('#progress').value=s.progress;if(s.status==='done'){await openResult(id);$('#analyze').disabled=false;loadHistory();return}if(s.status==='error'){error(Error(s.message));$('#analyze').disabled=false;loadHistory();return}pollTimer=setTimeout(tick,1400)}catch(e){error(e);$('#analyze').disabled=false}}tick()}
async function openResult(id){
  try{
    data=await api(`/api/jobs/${id}/result`);currentJob=id;qualitiesReady=false;rangePreview=false;clearRecovery();
    $('#workspace').hidden=false;$('#title').textContent=data.title;$('#meta').textContent=`${time(data.duration)} · ${data.language} · ${data.model==='none'?'audio only':data.model+' model'}`;
    $('#video').src=data.media_url;$('#video').onerror=()=>error(Error('The browser could not play this media. Try another file or inspect the local server log.'));
    $('#warnings').replaceChildren(...data.warnings.map(w=>element('p','',w)));
    if((data.scoring_revision||1)<2){const note=element('p','','This saved analysis uses older volume scoring. Update it to account for different commentator levels.');const button=element('button','clip-download','Update commentator scoring');button.onclick=async()=>{button.disabled=true;try{await api(`/api/jobs/${id}/refresh-scoring`,{method:'POST'});watch(id)}catch(e){error(e);button.disabled=false}};$('#warnings').append(note,button)}
    else $('#warnings').append(element('p','',`${data.speakers?.detected_speakers||0} voices detected automatically · ${data.speakers?.calibrated_speakers||0} with enough reference speech. Voice detection can be imperfect.`));
    $('#midTime').textContent=time(data.duration/2);$('#endTime').textContent=time(data.duration);
    $('#heatmap').setAttribute('aria-valuemax',data.duration);$('#methodText').textContent=data.methodology;
    weights={...data.default_weights};buildWeights();renderTranscript();selected=0;
    $('#rangeIn').value=preciseTime(0);$('#rangeOut').value=preciseTime(Math.min(12,Math.floor(data.duration*1000)/1000));$('#mapAction').value='seek';
    rescore();updateRange();history.replaceState(null,'',`#${id}`);loadQualities(id);
  }catch(e){error(e)}
}
function buildWeights(){$('#weights').replaceChildren();for(const k of Object.keys(labels)){const row=element('div','weight');const label=element('label','',labels[k]);label.htmlFor=`weight-${k}`;const out=element('output','',weights[k]);out.id=`value-${k}`;const input=element('input');input.type='range';input.id=`weight-${k}`;input.min=0;input.max=100;input.value=weights[k];if(k==='pace'&&!data.has_words){weights[k]=0;input.value=0;input.disabled=true;out.textContent='—'}input.oninput=()=>{weights[k]=+input.value;out.textContent=input.value;rescore()};row.append(label,out,input,element('small','',k==='pace'&&!data.has_words?'Unavailable — excluded from scoring':hints[k]));$('#weights').append(row)}}
function rescore(){if(!data)return;const denom=Object.values(weights).reduce((a,b)=>a+b,0);scores=data.bins.map(b=>b.silence||!denom?0:Math.round(1000*Object.entries(b.signals).reduce((s,[k,v])=>s+(weights[k]||0)*v,0)/denom)/10);draw();renderRanked();inspect(selected)}
$('#reset').onclick=()=>{weights={...data.default_weights};buildWeights();rescore()};
function color(s,silent){if(silent)return '#4b524f';const stops=[[38,83,151],[41,164,151],[194,214,86],[245,145,73],[237,66,66]];let p=Math.min(3.999,Math.max(0,s/100*4)),i=Math.floor(p),f=p-i;return `rgb(${stops[i].map((v,k)=>Math.round(v*(1-f)+stops[i+1][k]*f)).join(',')})`}
function draw(){
  if(!data)return;
  const c=$('#heatmap'),r=c.getBoundingClientRect(),dpr=window.devicePixelRatio||1;
  if(!r.width)return;
  c.width=Math.round(r.width*dpr);c.height=Math.round(94*dpr);
  const ctx=c.getContext('2d');ctx.scale(dpr,dpr);
  // Display the maximum in each pixel so narrow peaks survive on long videos.
  for(let x=0;x<Math.ceil(r.width);x++){
    const first=Math.min(data.bins.length-1,Math.floor(x/r.width*data.duration/2));
    const last=Math.min(data.bins.length-1,Math.floor((x+1)/r.width*data.duration/2));
    let peak=0,silent=true;
    for(let i=first;i<=last;i++){peak=Math.max(peak,scores[i]);silent=silent&&data.bins[i].silence}
    ctx.fillStyle=color(peak,silent);ctx.fillRect(x,0,1,94);
    ctx.fillStyle='rgba(12,24,18,.35)';ctx.fillRect(x,0,1,Math.max(3,70*(1-peak/100)));
  }
  ctx.strokeStyle='rgba(255,255,255,.18)';for(let i=1;i<4;i++){ctx.beginPath();ctx.moveTo(0,i*94/4);ctx.lineTo(r.width,i*94/4);ctx.stroke()}
  updatePlayhead();
}
new ResizeObserver(()=>draw()).observe($('#heatmap'));
function inspect(i){if(!data)return;selected=Math.max(0,Math.min(data.bins.length-1,i));const b=data.bins[selected];$('#hoverReadout').textContent=`${time(b.start)}–${time(b.end)} · ${scores[selected].toFixed(1)} / 100`;$('#binDetails').textContent=`${b.silence?'Silence · ':''}${data.has_words?b.wpm+' word-groups/min · ':''}${b.db} dBFS · +${b.surge_db} dB local rise · ${Math.round(b.speech_fraction*100)}% speech · sound change ${Math.round(b.signals.change*100)}/100`;$('#heatmap').setAttribute('aria-valuetext',`${time(b.start)}, score ${scores[selected]}, ${b.silence?'silence':Math.round(b.speech_fraction*100)+' percent speech'}`)}
function eventIndex(e){const r=$('#heatmap').getBoundingClientRect();return Math.min(data.bins.length-1,Math.max(0,Math.floor((e.clientX-r.left)/r.width*data.duration/2)))}
$('#heatmap').onpointermove=e=>{if(data)inspect(eventIndex(e))};
$('#heatmap').onclick=e=>{if(data){inspect(eventIndex(e));const r=$('#heatmap').getBoundingClientRect();const t=Math.max(0,Math.min(data.duration,(e.clientX-r.left)/r.width*data.duration));const mode=$('#mapAction').value;if(mode==='seek')seek(t);else{setMark(mode,t);$('#video').currentTime=t;updatePlayhead()}}};
$('#heatmap').onkeydown=e=>{if(!data)return;if(['ArrowRight','ArrowLeft','Home','End','Enter',' '].includes(e.key)){e.preventDefault();if(e.key==='ArrowRight')inspect(selected+1);if(e.key==='ArrowLeft')inspect(selected-1);if(e.key==='Home')inspect(0);if(e.key==='End')inspect(data.bins.length-1);const t=data.bins[selected].start,mode=$('#mapAction').value;if(mode==='seek')seek(t);else{setMark(mode,t);$('#video').currentTime=t}}};
function seek(seconds){rangePreview=false;const v=$('#video');v.currentTime=Math.max(0,Math.min(data.duration,seconds)-Number($('#lead').value));v.play().catch(()=>{});updatePlayhead()}
function updatePlayhead(){if(!data)return;const t=$('#video').currentTime;if(rangePreview){const range=readRange();if(!range||t>=range.end){$('#video').pause();rangePreview=false}}$('#playhead').style.left=`${Math.min(100,t/data.duration*100)}%`;$('#playTime').textContent=`${time(t)} / ${time(data.duration)}`;$('#heatmap').setAttribute('aria-valuenow',t.toFixed(1));let current=data.transcript.find(s=>s.start<=t&&s.end>t);$('#currentText').textContent=current?.text||'No transcribed speech at this timestamp.';for(const [el,s]of transcriptRows)el.classList.toggle('active',s===current)}
$('#video').ontimeupdate=updatePlayhead;
function ranked(){if(!data||!Object.values(weights).some(v=>v>0))return [];return ExcitementEvents.selectEvents(data.bins,scores,Number($('#eventThreshold').value))}
function reasons(i){const b=data.bins[i],total=Object.values(weights).reduce((a,b)=>a+b,0)||1;return Object.entries(b.signals).filter(([k,v])=>weights[k]>0&&v>0).sort((a,c)=>weights[c[0]]*c[1]-weights[a[0]]*a[1]).slice(0,3).map(([k,v])=>`${labels[k]} +${(100*weights[k]*v/total).toFixed(1)} pts`).join(' · ')}
function renderRanked(){
  const container=$('#ranked');container.replaceChildren();const picks=ranked();
  $('#eventCount').textContent=`${picks.length} events · all retained`;
  $('#downloadAll').disabled=exportBusy||!qualitiesReady||!picks.length;$('#downloadCombined').disabled=exportBusy||!qualitiesReady||!picks.length;
  if(!picks.length){container.append(element('p','empty','No events reach this threshold. Lower the threshold or adjust the signal mix to review weaker candidates.'));return}
  picks.forEach((p,j)=>{
    const b=data.bins[p.i],row=element('div','moment-row'),button=element('button','moment');button.type='button';
    const content=element('div');
    content.append(element('strong','',`${time(p.start)}–${time(Math.min(data.duration,p.end+momentLength()))}`),element('small','',`Peak ${time(b.start)} · ${time(p.end-p.start)} event · ${reasons(p.i)}`),element('small','',`${data.has_words?b.wpm+' word-groups/min · ':''}+${b.surge_db} dB same-voice rise · ${Math.round(b.speech_fraction*100)}% speech`));
    const score=element('div','score',p.score.toFixed(0));score.append(element('small','','/ 100'));
    button.append(element('span','rank',String(j+1).padStart(2,'0')),content,score);
    button.onclick=()=>{inspect(p.i);seek(p.start)};
    const download=element('button','clip-download single-download','Download clip ↓');download.type='button';download.disabled=exportBusy||!qualitiesReady;
    download.setAttribute('aria-label',`Download moment ${j+1} at ${time(b.start)}`);
    download.onclick=()=>downloadMoments([p],'clip');row.append(button,download);container.append(row);
  });
}
async function downloadMoments(picks,format){
  if(exportBusy||!data||!qualitiesReady||!picks.length)return;
  const snapshot=data,lead=Number($('#lead').value),length=momentLength();
  const segments=picks.map(p=>({start:Math.max(0,p.start-lead),end:Math.min(snapshot.duration,p.end+length)}));
  return downloadRanges(segments,format,snapshot.id);
}
async function downloadRanges(segments,format,jobId){
  if(exportBusy||!qualitiesReady)return;
  $('#error').hidden=true;
  const quality=$('#exportQuality').value;
  const status=$('#clipStatus'),manualStatus=$('#rangeStatus');status.hidden=false;
  const report=text=>{status.textContent=text;manualStatus.textContent=text};
  clearRecovery();report('Preparing download at the selected source quality…');exportBusy=true;renderRanked();updateRange();
  try{
    const job=await api(`/api/jobs/${jobId}/exports`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({format,segments,quality})});
    const base=`/api/jobs/${jobId}/exports/${job.id}`;
    for(;;){
      const result=await api(base);report(`${result.message} · ${result.progress}%`);
      if(result.status==='error'){
        if(result.recovery_quality&&data?.id===jobId){
          failedDownload={segments,format,jobId,quality:result.recovery_quality};
          for(const selector of ['#retryCachedRange','#retryCachedMoments']){const button=$(selector);button.textContent=result.recovery_label;button.hidden=false}
        }
        throw Error(result.message);
      }
      if(result.status==='done'){
        const a=element('a');a.href=base+'/download';a.download=result.filename;document.body.append(a);a.click();a.remove();
        report(`Ready — ${result.quality_label||quality}. Your download has started.${result.warnings?.length?' '+result.warnings.join(' '):''}`);break;
      }
      await new Promise(resolve=>setTimeout(resolve,700));
    }
  }catch(e){report(e.message);error(e)}finally{exportBusy=false;if(data){renderRanked();updateRange()}}
}
function clearRecovery(){failedDownload=null;for(const selector of ['#retryCachedRange','#retryCachedMoments']){const button=$(selector);if(button)button.hidden=true}}
function retryCached(){const failed=failedDownload;if(!failed||exportBusy||data?.id!==failed.jobId)return;setQuality(failed.quality);downloadRanges(failed.segments,failed.format,failed.jobId)}
$('#retryCachedRange').onclick=retryCached;$('#retryCachedMoments').onclick=retryCached;
$('#clipLength').onchange=()=>{if(data)renderRanked()};
$('#eventThreshold').oninput=()=>{if(data)renderRanked()};
$('#downloadAll').onclick=()=>downloadMoments(ranked(),'zip');
$('#downloadCombined').onclick=()=>downloadMoments(ranked(),'combined');
let qualityCatalog=null;
async function loadQualities(id,refresh=false){
  qualitiesReady=false;qualityCatalog=null;
  for(const selector of ['#exportQuality','#rangeQuality']){const select=$(selector);select.replaceChildren(element('option','','Checking source qualities…'));select.disabled=true}
  $('#qualityNote').textContent='Checking available source qualities. Analysis and playback quality do not limit source downloads.';
  $('#refreshQualities').disabled=true;if(data){renderRanked();updateRange()}
  try{
    const catalog=await api(`/api/jobs/${id}/qualities${refresh?'?refresh=true':''}`);
    if(data?.id!==id)return;
    qualityCatalog=catalog;
    let remembered;try{remembered=localStorage.getItem('excitement-quality:'+id)}catch{}
    const chosen=catalog.selected|| (catalog.options.some(q=>q.id===remembered)?remembered:catalog.default);
    for(const selector of ['#exportQuality','#rangeQuality']){
      const select=$(selector);select.replaceChildren();
      for(const q of catalog.options){const option=element('option','',q.label);option.value=q.id;select.append(option)}
      select.disabled=!catalog.options.length;select.value=chosen;
    }
    qualitiesReady=!!chosen&&catalog.options.length>0;setQuality(chosen,false);
  }catch(e){if(data?.id===id){$('#qualityNote').textContent='Could not load source qualities. Use Refresh qualities to retry. '+e.message;$('#rangeQualityNote').textContent=$('#qualityNote').textContent}}
  finally{if(data?.id===id){$('#refreshQualities').disabled=false;renderRanked();updateRange()}}
}
function setQuality(value,persist=true){
  for(const selector of ['#exportQuality','#rangeQuality'])$(selector).value=value;
  if(data&&value)try{localStorage.setItem('excitement-quality:'+data.id,value)}catch{}
  const q=qualityCatalog?.options.find(q=>q.id===value);
  let note=q?.origin==='youtube'?'Source-quality YouTube downloads request only the selected intervals. If partial retrieval is unavailable, choose the cached source or upload an original.':q?.origin==='local'?'Downloads are encoded from your original upload at this resolution. No proxy upscaling.':q?.origin==='cached'?'Uses the retained analysis source at its actual resolution, without another YouTube download.':'Only the existing playback proxy is available; missing source detail cannot be recovered.';
  if(qualityCatalog?.warning)note+=' '+qualityCatalog.warning;
  $('#qualityNote').textContent=note;$('#rangeQualityNote').textContent=note;
  if(persist&&data&&value)api(`/api/jobs/${data.id}/quality-choice`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({quality:value})}).catch(e=>{$('#qualityNote').textContent+=' Could not save this choice: '+e.message});
}
$('#exportQuality').onchange=e=>setQuality(e.target.value);
$('#rangeQuality').onchange=e=>setQuality(e.target.value);
$('#refreshQualities').onclick=()=>{if(data)loadQualities(data.id,true)};
function preciseTime(seconds){
  const millis=Math.max(0,Math.round(seconds*1000));const whole=Math.floor(millis/1000);
  return `${String(Math.floor(whole/3600)).padStart(2,'0')}:${String(Math.floor(whole/60)%60).padStart(2,'0')}:${String(whole%60).padStart(2,'0')}.${String(millis%1000).padStart(3,'0')}`;
}
function parseTimestamp(value){
  const text=value.trim();if(!/^\d+(?::\d{1,2}){0,2}(?:\.\d{1,3})?$/.test(text))return NaN;
  const parts=text.split(':').map(Number);if(parts.length>1&&parts.slice(1).some(n=>n>=60))return NaN;
  return parts.reduce((total,n)=>total*60+n,0);
}
function readRange(){
  if(!data)return null;const start=parseTimestamp($('#rangeIn').value),end=parseTimestamp($('#rangeOut').value);
  return Number.isFinite(start)&&Number.isFinite(end)&&start>=0&&end<=data.duration&&end-start>=.1?{start,end}:null;
}
function updateRange(){
  if(!data)return;
  const range=readRange(),overlay=$('#selectionRange');overlay.hidden=!range;
  if(range){overlay.style.left=`${range.start/data.duration*100}%`;overlay.style.width=`${(range.end-range.start)/data.duration*100}%`;$('#rangeSummary').textContent=`${preciseTime(range.start)} → ${preciseTime(range.end)} · ${(range.end-range.start).toFixed(3)} seconds`}
  else $('#rangeSummary').textContent=`Enter valid In/Out timestamps within 0–${preciseTime(Math.floor(data.duration*1000)/1000)}. Out must be at least 0.1 seconds after In.`;
  for(const selector of ['#rangeIn','#rangeOut'])$(selector).setAttribute('aria-invalid',String(!range));
  $('#downloadRange').disabled=!range||exportBusy||!qualitiesReady;$('#previewRange').disabled=!range;
}
function setMark(which,seconds){
  rangePreview=false;clearRecovery();const safe=Math.floor(Math.max(0,Math.min(data.duration,seconds))*1000)/1000;
  $(which==='in'?'#rangeIn':'#rangeOut').value=preciseTime(safe);updateRange();
}
$('#markIn').onclick=()=>{if(data)setMark('in',$('#video').currentTime)};
$('#markOut').onclick=()=>{if(data)setMark('out',$('#video').currentTime)};
for(const selector of ['#rangeIn','#rangeOut'])$(selector).oninput=()=>{rangePreview=false;clearRecovery();updateRange()};
$('#previewRange').onclick=()=>{const range=readRange();if(range){$('#video').currentTime=range.start;rangePreview=true;$('#video').play().catch(()=>{});updatePlayhead()}};
$('#downloadRange').onclick=()=>{const range=readRange();if(range)downloadRanges([range],'clip',data.id)};
function renderTranscript(){const q=$('#search').value.toLocaleLowerCase();const list=$('#transcript');list.replaceChildren();transcriptRows=[];$('#wordCount').textContent=`${data.words.length.toLocaleString()} word-groups`;const rows=data.transcript.filter(s=>s.text.toLocaleLowerCase().includes(q));if(!rows.length){list.append(element('p','empty',data.transcript.length?'No matching commentary.':'No transcript available. Use a transcription model to include spoken word pace.'));return}for(const s of rows){const button=element('button','transcript-row');button.append(element('time','',time(s.start)),element('span','',s.text));button.onclick=()=>seek(s.start);list.append(button);transcriptRows.push([button,s])}updatePlayhead()}
$('#search').oninput=()=>{if(data)renderTranscript()};
$('#export').onclick=()=>{const output={...data,weights,scores,event_threshold:Number($('#eventThreshold').value),selected_source_quality:$('#exportQuality').value,manual_selection:readRange(),ranked_segments:ranked().map(p=>({start:p.start,end:Math.min(data.duration,p.end+momentLength()),peak:data.bins[p.i].start,score:p.score,reasons:reasons(p.i)}))};const url=URL.createObjectURL(new Blob([JSON.stringify(output,null,2)],{type:'application/json'}));const a=element('a');a.href=url;a.download='excitement-results.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
async function loadHistory(){
  try{
    const list=await api('/api/jobs');$('#history').replaceChildren();
    if(!list.length)$('#history').append(element('p','empty','Your completed recordings will appear here.'));
    for(const j of list){
      const row=element('div','history-row'),name=element('div','history-title');
      name.append(element('strong','',j.title),element('small','',`${j.status} · ${j.status==='done'?'ready to review':j.message}`));row.append(name);
      if(j.status==='done'){
        const open=element('button','text-button','Open ↗');open.onclick=()=>openResult(j.id);row.append(open);
      }else if(['running','queued','uploading'].includes(j.status)){
        const follow=element('button','text-button','View progress');follow.onclick=()=>watch(j.id);row.append(follow);
      }else if(j.status==='error'){
        const retry=element('button','text-button','Retry');
        retry.onclick=async()=>{try{$('#error').hidden=true;const resumed=await api(`/api/jobs/${j.id}/retry`,{method:'POST'});watch(resumed.id);loadHistory()}catch(e){error(e)}};
        row.append(retry);
      }
      if(['done','error'].includes(j.status)){
        const del=element('button','text-button delete','Delete');
        del.onclick=async()=>{
          if(!confirm('Delete this analysis and its stored media from this app?'))return;
          try{
            await api(`/api/jobs/${j.id}`,{method:'DELETE'});
            if(data?.id===j.id){$('#video').pause();$('#video').removeAttribute('src');data=null;$('#workspace').hidden=true;history.replaceState(null,'',location.pathname)}
            loadHistory();
          }catch(e){error(e)}
        };
        row.append(del);
      }
      $('#history').append(row);
    }
  }catch(e){error(e)}
}
$('#refresh').onclick=loadHistory;loadHistory();if(/^[a-f0-9]{32}$/.test(location.hash.slice(1)))openResult(location.hash.slice(1));
