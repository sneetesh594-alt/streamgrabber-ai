"use strict";

const paths = {
  studio: '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M3 9h18m-13-5 3 5m3-5 3 5"/>',
  library: '<rect x="7" y="7" width="13" height="14" rx="2"/><path d="M16 3H6a3 3 0 0 0-3 3v11m8-6h5m-5 4h5"/>',
  activity: '<path d="M2 13h5l3-8 4 15 3-9h5"/>',
  scissors: '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="m8 8 12 12M8 16 20 4"/>',
  sliders: '<path d="M4 6h7m4 0h5M4 12h2m4 0h10M4 18h9m4 0h3"/><circle cx="13" cy="6" r="2"/><circle cx="8" cy="12" r="2"/><circle cx="15" cy="18" r="2"/>',
  link: '<path d="m10 13 4-4m-6 6-1 1a3.5 3.5 0 0 1-5-5l4-4a3.5 3.5 0 0 1 5 0m2 10a3.5 3.5 0 0 0 5 0l4-4a3.5 3.5 0 0 0-5-5l-1 1" transform="rotate(-17 12 12)"/>',
  upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
  clipboard: '<rect x="5" y="5" width="14" height="16" rx="2"/><rect x="9" y="3" width="6" height="4" rx="1"/>',
  settings: '<path d="M3 6h5m4 0h9M3 12h11m4 0h3M3 18h3m4 0h11"/><circle cx="10" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="8" cy="18" r="2"/>',
  pencil: '<path d="m14 5 5 5M4 20l4-1 12-12a2 2 0 0 0-4-4L4 15z"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  spark: '<path d="m13 2-2.8 6.8L4 12l6.2 3.1L13 22l2.6-6.9L22 12l-6.4-3.2zM4 2v4m-2-2h4"/>',
  frame: '<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M10 5h4m-3 14h2"/>',
  play: '<path d="m8 5 11 7-11 7z"/>', x: '<path d="m6 6 12 12M18 6 6 18"/>'
};
function icons(root = document) {
  root.querySelectorAll('i[data-i]').forEach(icon => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    svg.classList.add('ico');
    svg.innerHTML = paths[icon.dataset.i] || '';
    icon.replaceWith(svg);
  });
}
const el = id => document.getElementById(id);
function element(tag, text, cls) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
const hostnames = ['youtube.com','youtu.be','twitch.tv','kick.com','instagram.com','tiktok.com','twitter.com','x.com','facebook.com','fb.watch'];
const localKey = 'streamgrabber.studio.history.v1';
function readHistory() {
  try { return JSON.parse(localStorage.getItem(localKey)) || []; } catch { return []; }
}
function record(job, name) {
  const history = readHistory();
  const previous = history.find(j => j.id === job.job_id);
  const entry = {id: job.job_id, name: job.video_title || name || previous?.name || 'Clip job',
    created: previous?.created || Date.now(), state: job.status, count: job.num_clips || 0};
  try { localStorage.setItem(localKey, JSON.stringify([entry,...history.filter(j => j.id !== entry.id)].slice(0,40))); } catch {}
}
function time(seconds) {
  const n = Math.floor(seconds);
  return (n >= 3600 ? Math.floor(n/3600)+':' : '') + String(Math.floor(n%3600/60)).padStart(2,'0') + ':' + String(n%60).padStart(2,'0');
}
function secondsField(id) {
  const value = el(id).value.trim();
  if (!value) return null;
  if (!/^\d{1,3}:[0-5]\d:[0-5]\d$/.test(value)) throw new Error('Use HH:MM:SS, for example 18:30:00.');
  const [hours,minutes,seconds] = value.split(':').map(Number);
  return hours*3600+minutes*60+seconds;
}
el('scan-mode').onchange = () => {
  el('scan-hint').textContent = el('scan-mode').value === 'quick'
    ? 'Sample across the timeline, including the first and last minute.'
    : 'Inspect every section of the recording or available live DVR.';
};
async function api(path, options = {}) {
  let res;
  try { res = await fetch(path, {cache:'no-store',...options}); }
  catch { throw new Error('The processing server is unreachable. Check your connection and retry.'); }
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(typeof json.detail === 'string' ? json.detail : 'The request could not be completed ('+res.status+').');
    error.status = res.status;
    throw error;
  }
  return json;
}
let mode = 'link';
let count = 3;
let selectedFile = null;
let watching = 0;
let activeId = null;
function setMode(next) {
  mode = next;
  el('link-tab').setAttribute('aria-pressed', mode === 'link');
  el('file-tab').setAttribute('aria-pressed', mode === 'file');
  el('url-group').hidden = mode !== 'link';
  el('file-group').hidden = mode !== 'file';
  el('form-note').textContent = '';
}
function setCount(delta) {
  count = Math.min(10,Math.max(1,count+delta));
  el('count').value = count;
  el('more').disabled = count === 10;
  el('fewer').disabled = count === 1;
}
function preview() {
  const overlay = el('overlay').checked;
  const badge = el('badge').value.trim();
  const tag = el('tag').value.trim();
  const logo = ['GTA VI','GTA6','GTA 6'].includes(badge.toUpperCase());
  el('mock-logo').hidden = !overlay || !logo;
  el('mock-badge').hidden = !overlay || !badge || logo;
  el('mock-badge').textContent = badge;
  el('mock-tag').hidden = !overlay || !tag;
  el('mock-tag').textContent = tag;
  el('size-label').textContent = el('quality').value === '720p' ? '720 × 1280' : '1080 × 1920';
}
function choose(file) {
  selectedFile = file || null;
  el('file-name').textContent = file?.name || 'Choose a recording';
  el('form-note').textContent = '';
}
el('link-tab').onclick = () => setMode('link');
el('file-tab').onclick = async () => {
  setMode('file');
  try {
    const health = await api('/api/studio/health');
    el('upload-help').textContent = 'MP4, MOV, MKV or WebM · up to '+health.max_upload_mb+' MB';
  } catch {}
};
el('fewer').onclick = () => setCount(-1);
el('more').onclick = () => setCount(1);
for (const id of ['overlay','badge','tag','quality']) el(id).addEventListener('input',preview);
el('video-file').onchange = e => choose(e.target.files[0]);
const drop = document.querySelector('.drop');
drop.ondragover = e => { e.preventDefault();drop.classList.add('drag'); };
drop.ondragleave = () => drop.classList.remove('drag');
drop.ondrop = e => { e.preventDefault();drop.classList.remove('drag');choose(e.dataTransfer.files[0]); };
el('paste').onclick = async () => {
  try {
    const value = await navigator.clipboard.readText();
    el('stream').value = value.trim();
    el('form-note').textContent = '';
  } catch { el('form-note').textContent = 'Tap the URL field and choose Paste.'; }
  el('stream').focus();
};
async function share(label, url) {
  if (navigator.share) {
    try { await navigator.share({title:label,url}); return; }
    catch (e) { if (e.name === 'AbortError') return; }
  }
  try { await navigator.clipboard.writeText(url); return 'Link copied'; }
  catch { window.prompt('Copy this public link',url); }
}
function videoCard(c,jobId) {
  const box = element('article',null,'clip-card');
  const video = element('video');
  video.controls = true; video.preload = 'metadata'; video.playsInline = true;
  video.setAttribute('webkit-playsinline','');
  video.src = c.media_url; if (c.thumb_url) video.poster = c.thumb_url;
  const title = element('h3',c.title);
  const stats = element('p',time(c.start)+' – '+time(c.end)+' · '+Math.round(c.score*100)+'% highlight score');
  const source = element('p',c.evidence);
  const links = element('div',null,'clip-actions');
  const dl = element('a','Download MP4','secondary');
  dl.href = c.download_url; dl.download = c.file || 'highlight.mp4';
  const link = element('button','Share public link','secondary');
  link.onclick = async () => {
    try {
      const data = await api('/api/studio/jobs/'+jobId+'/share/'+c.id,{method:'POST'});
      const msg = await share(c.title,data.url);
      if (msg) link.textContent = msg;
    } catch (e) { source.textContent=e.message; }
  };
  links.append(dl,link);
  if(c.captions){const srt=element('a','Download subtitles','secondary');srt.href=c.srt_url+'?download=1';links.append(srt);}
  box.append(video,title,stats,source,links);
  return box;
}
async function watch(id, label) {
  activeId = id;
  const iteration = ++watching;
  el('active-job').hidden = false;
  el('job-results').replaceChildren();
  let misses = 0;
  while (watching === iteration) {
    try {
      const job = await api('/api/studio/jobs/'+id);
      if (watching !== iteration) return;
      misses = 0;
      record(job,label);
      el('job-progress').value = job.percent || 0;
      el('job-progress').hidden = job.status === 'error';
      el('job-percent').textContent = job.status === 'error' ? '' : Math.round(job.percent || 0)+'%';
      const note = job.status === 'error' ? job.error : job.stage;
      const extent = job.available_range;
      const origin = extent ? 'Available '+time(extent[0])+' – '+time(extent[1])+' from '+job.timeline_origin+'.' : '';
      const coverage = job.scanned_ranges?.length ? 'Inspected '+job.scanned_ranges.length+' sections.' : '';
      el('job-status').textContent = [note,origin,coverage,...(job.warnings || [])].filter(Boolean).join(' ');
      if(job.status==='paused'){
        const line=job.stage+'. Resumes after '+new Date(job.reset_at).toLocaleString();
        el('job-status').textContent=line;
        if('Notification' in window && Notification.permission==='granted' && notified.get(id)!==job.reset_at){
          notified.set(id,job.reset_at);
          try{
            const reg=await alertWorker();
            if(reg?.active)await reg.showNotification('Clip Studio paused',{body:line,tag:id});
            else new Notification('Clip Studio paused',{body:line,tag:id});
          }catch{}
        }
      }
      if (job.status==='error' && job.resumable) {
        const resume=element('button','Resume scan','secondary');
        resume.onclick=async()=>{try{resume.disabled=true;await api('/api/studio/jobs/'+id+'/resume',{method:'POST'});watch(id,label);}
          catch(e){el('job-status').textContent=e.message;resume.disabled=false;}};
        el('job-results').replaceChildren(resume);
      }
      if (job.status === 'error' || job.status === 'completed') {
        if(job.transcript_url){
          const btn=element('button','Read transcript','secondary');
          btn.onclick=async()=>{try{const rows=await api(job.transcript_url);const text=element('pre',rows.map(s=>time(s.start)+'  '+s.text).join('\n')||'No speech was detected in the inspected gameplay.');text.className='transcript-text';btn.replaceWith(text);}catch(e){btn.textContent=e.message;}};
          el('job-results').append(btn);
        }
        for (const c of job.clips || []) el('job-results').append(videoCard(c,id));
        if (location.hash === '#library') library();
        return;
      }
    } catch(e) {
      if(e.status===404){el('job-status').textContent='This worker no longer has the job. Submit your recording again.';return;}
      if (++misses >= 12) {el('job-status').textContent = e.message+' Reopen the job from Clip library to retry.';return;}
      el('job-status').textContent = 'Reconnecting to the processing server…';
    }
    await new Promise(done => setTimeout(done,Math.min(10000,2500*(1+misses))));
  }
}
el('clip-form').onsubmit = async event => {
  event.preventDefault();
  const note = el('form-note');
  note.textContent = '';
  const url = el('stream').value.trim();
  if (mode === 'link') {
    try {
      const parsed = new URL(url);
      if (!['https:','http:'].includes(parsed.protocol) || parsed.username || parsed.password ||
          !hostnames.some(host => parsed.hostname === host || parsed.hostname.endsWith('.'+host))) throw new Error();
    } catch {note.textContent='Enter a video URL from one of the listed platforms.';el('stream').focus();return;}
  } else if (!selectedFile) {
    note.textContent = 'Choose a video recording.';return;
  }
  const opts = {num_clips:count, clip_duration:Number(el('duration').value),quality:el('quality').value,
    subtitle_font:el('font').value,enable_overlay:el('overlay').checked,creator_tag:el('tag').value.trim(),overlay_badge:el('badge').value.trim()};
  try {
    opts.scan_mode=el('scan-mode').value;
    opts.range_start=secondsField('range-start') || 0;
    const end=secondsField('range-end');
    if(end!==null){
      if(end-opts.range_start<20)throw new Error('Select at least 20 seconds between start and end.');
      opts.range_end=end;
    }
  }catch(e){note.textContent=e.message;return;}
  const btn=el('generate');btn.disabled=true;
  try {
    note.textContent = 'Connecting to the video worker…';
    const h = await api('/api/studio/health',{signal:AbortSignal.timeout(85000)});
    if (h.studio_version !== 4 || !h.evidence_required || !h.long_streams) throw new Error('The video worker is updating. Try again shortly.');
    if(mode==='file' && selectedFile.size>h.max_upload_mb*1024*1024) throw new Error('This worker accepts uploads up to '+h.max_upload_mb+' MB. Paste a stream link for a larger recording.');
    let job;
    if (mode==='link') {
      job=await api('/api/studio/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...opts,url})});
    } else {
      const form = new FormData();
      form.append('file',selectedFile);
      form.append('max_clips',count);
      for (const [key,value] of Object.entries(opts)) if (key!=='num_clips') form.append(key,String(value));
      note.textContent = 'Uploading your recording…';
      job=await api('/api/studio/upload',{method:'POST',body:form});
    }
    const label = mode==='file' ? selectedFile.name : new URL(url).hostname;
    record({...job,status:'queued'},label);
    note.textContent='';
    watch(job.job_id,label);
    el('active-job').scrollIntoView({block:'start',behavior:'smooth'});
  } catch(e) { note.textContent=e.name==='TimeoutError' ? 'The video worker is taking longer to start. Try again in a minute.' : e.message; }
  finally {btn.disabled=false;}
};
function library() {
  const list=el('library-list');list.replaceChildren();
  const records=readHistory();
  if (!records.length) {
    list.append(el('empty-library').content.cloneNode(true));
    icons(list);return;
  }
  for (const job of records) {
    const item=element('article',null,'panel library-row');
    item.append(element('h2',job.name),element('p',new Date(job.created).toLocaleString()+' · '+job.state+' · '+job.count+' clips'));
    const open=element('button','Open job','secondary');
    open.onclick=()=>{location.hash='studio';watch(job.id,job.name);setTimeout(()=>el('active-job').scrollIntoView(),0);};
    item.append(open);list.append(item);
  }
}
function navigate() {
  const inLibrary=location.hash==='#library';
  el('studio-page').hidden=inLibrary;el('library-page').hidden=!inLibrary;
  el('nav-library').toggleAttribute('aria-current',inLibrary);
  el('nav-studio').toggleAttribute('aria-current',!inLibrary);
  if(inLibrary)library();
}
el('usage-open').onclick = async () => {
  const panel=el('usage-content');panel.replaceChildren(element('p','Reading usage from the video worker…'));
  el('usage-dialog').showModal();
  try {
    const u=await api('/api/studio/usage');
    const grid=element('div',null,'usage-grid');
    for(const [num,label] of [[u.requests+' / '+u.daily_limit,'Gemini requests today'],[u.tokens,'Reported tokens'],['$'+Number(u.estimated_cost_usd).toFixed(2),'API spend'],[u.configured_slots+' / 2','Gemini keys'],[(u.groq_slots||0)+' / 4','Groq keys'],[u.groq_requests||0,'Groq requests · 24h'],[u.groq_audio_seconds||0,'Audio seconds · 24h']]){
      const cell=element('div');cell.append(element('b',String(num)),element('small',label));grid.append(cell);
    }
    panel.replaceChildren(grid,element('p',u.paused?'Quota reserve reached. Processing will resume after reset.':'Cloud review requires a verified, unbilled Google project. Local analysis is available independently.'));
  } catch(e){panel.replaceChildren(element('p',e.message));}
};
const notified=new Map();
async function alertWorker(){
  if(!('serviceWorker' in navigator))return null;
  return navigator.serviceWorker.register('/studio-assets/alerts.js');
}
el('alerts').onclick=async()=>{
  const btn=el('alerts');
  try{const enabled='Notification' in window && await Notification.requestPermission()==='granted';if(enabled)await alertWorker();btn.textContent=enabled?'Quota alerts enabled':'Quota alerts appear in Current job';}catch{btn.textContent='Quota alerts appear in Current job';}
};
el('try-sample').onclick=async()=>{
  const panel=el('sample-content');panel.replaceChildren(element('p','Loading sample…'));el('sample-dialog').showModal();
  try {
    const c=await api('/studio-assets/assets/sample.json');
    const v=element('video');v.src='/studio-assets/assets/sample.mp4';v.controls=true;v.preload='metadata';v.playsInline=true;v.setAttribute('webkit-playsinline','');
    const original=element('a','Original recording');original.href=c.source;original.target='_blank';original.rel='noopener';
    const license=element('a','CC BY-SA 4.0');license.href='https://creativecommons.org/licenses/by-sa/4.0/';license.target='_blank';license.rel='noopener';
    const credit=element('p','Adapted from “Urban Mayhem” by Xusder. ');credit.append(original,' · ',license);
    const dl=element('a','Download sample','secondary');dl.href=v.src;dl.download='Urban-Mayhem-sample.mp4';
    const controls=element('div',null,'clip-actions');controls.append(dl);
    panel.replaceChildren(v,element('h3','GTA V · Urban Mayhem'),element('p',time(c.start)+' – '+time(c.end)+' · '+c.resolution+' · '+c.evidence),credit,controls);
  } catch(e){panel.replaceChildren(element('p',e.message));}
};
document.querySelectorAll('dialog').forEach(dialog=>{
  dialog.querySelector('.close').onclick=()=>dialog.close();
  dialog.onclick=e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}};
  dialog.addEventListener('close',()=>dialog.querySelectorAll('video').forEach(v=>v.pause()));
});
window.addEventListener('hashchange',navigate);
icons();setCount(0);navigate();preview();
const ongoing=readHistory().find(j=>['queued','paused','running','starting'].includes(j.state));
if(ongoing) watch(ongoing.id,ongoing.name);
