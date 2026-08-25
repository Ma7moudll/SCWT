"""Admin web console (single-page, served by the backend).

The HTML shell is INERT — it contains no data and no secrets. Every piece of
information it renders comes from the JSON endpoints under /api/v1/admin/*,
each of which requires role == "admin" server-side. A student who opens the
page sees only the login form; the API calls return 401/403.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["admin-ui"])

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>EcoLoop Admin</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { --green:#0b6e3f; --bg:#f4f7f5; --card:#fff; --line:#dde5e0; --muted:#68766e; }
  * { box-sizing:border-box; margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; }
  body { background:var(--bg); color:#15201a; padding:24px; }
  h1 { color:var(--green); font-size:22px; margin-bottom:4px; }
  .sub { color:var(--muted); font-size:13px; margin-bottom:20px; }
  #login { max-width:360px; margin:10vh auto; background:var(--card); border:1px solid var(--line);
           border-radius:12px; padding:28px; }
  input { width:100%; padding:10px 12px; margin:8px 0; border:1px solid var(--line); border-radius:8px; font-size:14px; }
  button { background:var(--green); border:none; color:#fff; padding:11px 16px; border-radius:8px;
           font-size:14px; font-weight:600; cursor:pointer; width:100%; margin-top:8px; }
  button:hover { filter:brightness(1.08); }
  .err { color:#b3261e; font-size:13px; margin-top:8px; min-height:18px; }
  nav { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:18px; }
  nav button { width:auto; background:#fff; color:#15201a; border:1px solid var(--line); font-weight:500; }
  nav button.active { background:var(--green); color:#fff; border-color:var(--green); }
  section { display:none; } section.active { display:block; }
  .cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(170px,1fr)); gap:12px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; }
  .card b { display:block; font-size:22px; margin-top:4px; }
  .card span { color:var(--muted); font-size:12px; }
  table { width:100%; border-collapse:collapse; background:var(--card); border-radius:10px; overflow:hidden;
          border:1px solid var(--line); font-size:13px; }
  th { text-align:left; background:#eef3ef; padding:9px 12px; color:var(--muted); font-size:11px;
       text-transform:uppercase; letter-spacing:.04em; }
  td { padding:9px 12px; border-top:1px solid var(--line); }
  tr:hover td { background:#fafcfa; }
  .pill { padding:2px 9px; border-radius:99px; font-size:11px; font-weight:700; }
  .ok  { background:#e2f3e8; color:#0b6e3f; }
  .bad { background:#fbe9e7; color:#b3261e; }
  .warn{ background:#fdf3e0; color:#8a6116; }
  #health div { background:var(--card); border:1px solid var(--line); border-radius:10px;
                padding:12px 16px; margin-bottom:8px; display:flex; justify-content:space-between; }
</style>
</head>
<body>
<div id="login">
  <h1>EcoLoop Admin</h1>
  <p class="sub">Administrator sign-in. Student accounts are refused.</p>
  <input id="email" type="email" placeholder="admin email" autocomplete="username">
  <input id="pass" type="password" placeholder="password" autocomplete="current-password">
  <button onclick="login()">Sign in</button>
  <div class="err" id="err"></div>
</div>

<div id="app" style="display:none">
  <h1>EcoLoop Admin Console</h1>
  <p class="sub" id="who"></p>
  <nav id="tabs"></nav>

  <section id="s-overview"></section>
  <section id="s-faculties"></section>
  <section id="s-students"></section>
  <section id="s-stations"></section>
  <section id="s-deposits"></section>
  <section id="s-challenges"></section>
  <section id="s-rewards"></section>
  <section id="s-health"></section>
</div>

<script>
let TOKEN = null;
let currentTab = 'overview';
let LAST_REWARDS = [];
let LAST_USERS = [];
let LAST_FACULTIES = [];
let LAST_STATIONS = [];
let LAST_CHALLENGES = [];

async function login() {
  const email = document.getElementById('email').value.trim();
  const pass  = document.getElementById('pass').value;
  document.getElementById('err').textContent = '';
  try {
    const r = await fetch('/api/v1/auth/login', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({email, password: pass})
    });
    if (!r.ok) throw new Error((await r.json()).detail || 'login failed');
    const body = await r.json();
    const me = await fetch('/api/v1/auth/me', {headers:{Authorization:'Bearer '+body.token}});
    const u = (await me.json()).user;
    if (u.role !== 'admin') throw new Error('This account is not an administrator.');
    TOKEN = body.token;
    document.getElementById('login').style.display = 'none';
    document.getElementById('app').style.display = 'block';
    document.getElementById('who').textContent = 'Signed in as ' + u.name + ' (' + u.email + ')';
    buildTabs();
    show('overview');
  } catch (e) { document.getElementById('err').textContent = e.message; }
}

async function api(path) {
  const r = await fetch('/api/v1' + path, {headers:{Authorization:'Bearer '+TOKEN}});
  if (!r.ok) throw new Error(path + ' -> HTTP ' + r.status);
  return r.json();
}

async function addUserPrompt(){
  const name = ask('Full name:'); if(name===undefined) return;
  const email = ask('Email:'); if(email===undefined||!email) return;
  const code = ask('Student ID (A-Z0-9-):'); if(code===undefined||!code) return;
  const fac = ask('Faculty ID (see Faculties tab, e.g. ENGINEERING):'); if(fac===undefined) return;
  const pass = prompt('Initial password (min 8 chars):'); if(pass===null) return;
  await run(async ()=>{
    await send('POST','/auth/register',{name,email,password:pass,facultyId:(fac||'').toUpperCase(),studentCode:code});
    alert('Student account created.');
  });
}
async function editUser(i){
  const u = LAST_USERS[i]; if(!u){ alert('Row stale — reload.'); return; }
  const n = ask('Edit full name:', u.name); if(n===undefined) return;
  const pRaw = ask('Edit points:', u.points); if(pRaw===undefined) return;
  const p = parseInt(pRaw,10);
  if (!n || isNaN(p) || p<0){ alert('Invalid values.'); return; }
  await run(async ()=>{ await send('PATCH','/admin/users/'+u.id,{name:n, points:p}); });
}
async function toggleUser(i){
  const u = LAST_USERS[i]; if(!u) return;
  await run(async ()=>{ await send('PATCH','/admin/users/'+u.id,{is_active:!u.is_active}); });
}
async function delUser(i){
  const u = LAST_USERS[i]; if(!u) return;
  if(!confirm('Delete '+u.name+'? Accounts with deposit/redemption history cannot be deleted — deactivate them instead.')) return;
  await run(async ()=>{ const r=await send('DELETE','/admin/users/'+u.id); alert('Deleted '+(r.deleted||u.id)); });
}


async function addStationPrompt(){
  const code = ask('Station code (unique):'); if(code===undefined||!code) return;
  const name = ask('Station name:'); if(name===undefined||!name) return;
  await run(async ()=>{
    await send('POST','/admin/stations',{station_code:code.trim(), name:name.trim()});
    alert('Station registered.');
  });
}
async function renameStation(i){
  const x = LAST_STATIONS[i]; if(!x) return;
  const n = ask('Rename station:', x.name); if(n===undefined||!n) return;
  await run(async ()=>{ await send('PATCH','/admin/stations/'+x.id,{name:n}); });
}
async function toggleStation(i){
  const x = LAST_STATIONS[i]; if(!x) return;
  await run(async ()=>{ await send('PATCH','/admin/stations/'+x.id,{enabled:x.status!=='online'}); });
}
async function delStation(i){
  const x = LAST_STATIONS[i]; if(!x) return;
  if(!confirm('Delete station '+x.station_code+'? Stations with deposit history cannot be deleted (disable instead).')) return;
  await run(async ()=>{ const r=await send('DELETE','/admin/stations/'+x.id); alert('Deleted '+(r.deleted||x.id)); });
}

async function addChallengePrompt(){
  const title = ask('Challenge title:'); if(title===undefined||!title) return;
  const emoji = ask('Theme emoji:', '\u267b\ufe0f') || '';
  const wc = (ask('Waste class (plastic/metal/paper/glass):','plastic')||'').toLowerCase();
  if(!['plastic','metal','paper','glass'].includes(wc)){ alert('Invalid waste class.'); return; }
  const tRaw = ask('Target kg:', '5'); if(tRaw===undefined) return; const t = parseFloat(tRaw);
  if(isNaN(t)||t<=0){ alert('Invalid target.'); return; }
  const rRaw = ask('Reward points:', '50'); if(rRaw===undefined) return; const r = parseInt(rRaw,10);
  if(isNaN(r)||r<0){ alert('Invalid reward points.'); return; }
  await run(async ()=>{
    await send('POST','/admin/challenges',{title:title.trim(), description:'Created from admin console',
      theme_emoji:emoji||'\u267b\ufe0f', waste_class:wc, target_kg:t, reward_points:r});
    alert('Challenge created.');
  });
}
async function editChallenge(i){
  const c = LAST_CHALLENGES[i]; if(!c){ alert('Row stale — reload.'); return; }
  const n = ask('Edit title:', c.title); if(n===undefined||!n) return;
  const e = ask('Edit theme emoji:', c.theme_emoji||''); if(e===undefined) return;
  const wRaw = ask('Waste class (plastic/metal/paper/glass):', c.waste_class); if(wRaw===undefined) return;
  const w=(wRaw||'').toLowerCase(); if(!['plastic','metal','paper','glass'].includes(w)){ alert('Invalid waste class.'); return; }
  const tRaw = ask('Target kg:', c.target_kg); if(tRaw===undefined) return; const t=parseFloat(tRaw);
  if(isNaN(t)||t<=0){ alert('Invalid target.'); return; }
  const rRaw = ask('Reward points:', c.reward_points); if(rRaw===undefined) return; const r=parseInt(rRaw,10);
  if(isNaN(r)||r<0){ alert('Invalid reward points.'); return; }
  await run(async ()=>{ await send('PATCH','/admin/challenges/'+c.id,
    {title:n.trim(), theme_emoji:e||'', waste_class:w, target_kg:t, reward_points:r}); });
}
async function toggleChallenge(i){
  const c = LAST_CHALLENGES[i]; if(!c) return;
  await run(async ()=>{ await send('PATCH','/admin/challenges/'+c.id,{active:!c.active}); });
}
async function delChallenge(i){
  const c = LAST_CHALLENGES[i]; if(!c) return;
  if(!confirm('Delete challenge "'+c.title+'"? Challenges students already joined cannot be deleted (deactivate instead).')) return;
  await run(async ()=>{ const r=await send('DELETE','/admin/challenges/'+c.id); alert('Deleted '+(r.deleted||c.id)); });
}

function rewardPayload(name,cost,stockRaw,label,provider){
  const n=(name||'').trim(); if(!n){ alert('Name required.'); return null; }
  const c=parseInt(cost,10); if(isNaN(c)||c<1){ alert('Points cost must be >= 1.'); return null; }
  let stock=null;
  if(stockRaw!=='unl'){ stock=parseInt(stockRaw,10); if(isNaN(stock)||stock<0){ alert('Invalid stock.'); return null; } }
  const v=(label||'').trim(); if(!v){ alert('Value label required.'); return null; }
  return {category:'cash', name:n, description:'', provider:(provider||'').trim(),
          points_cost:c, value_label:v, value_amount:null, currency:'EGP',
          icon:'card_giftcard', is_active:true, stock:stock, requires_destination:true};
}
async function addRewardPrompt(){
  const name=ask('Reward name:'); if(name===undefined) return;
  const cost=ask('Points cost:', '100'); if(cost===undefined) return;
  const stock=prompt('Stock (blank = unlimited):'); if(stock===null) return;
  const label=ask('Value label (e.g. 10 EGP Vodafone Cash):'); if(label===undefined) return;
  const provider=ask('Provider (optional):'); if(provider===undefined) return;
  const body=rewardPayload(name,cost,stock.trim()===''?'unl':stock.trim(),label,provider);
  if(!body) return;
  await run(async ()=>{ await send('POST','/admin/rewards',body); alert('Reward created.'); });
}
async function editReward(i){
  const r = LAST_REWARDS[i]; if(!r){ alert('Row stale — reload.'); return; }
  const n=ask('Edit reward name:', r.name); if(n===undefined) return;
  const c=ask('Edit points cost:', r.points_cost); if(c===undefined) return;
  const st=prompt('Edit stock (blank = unlimited):', r.stock==null?'':String(r.stock)); if(st===null) return;
  const v=ask('Edit value label:', r.value_label); if(v===undefined) return;
  const pr=ask('Edit provider:', r.provider||''); if(pr===undefined) return;
  const body=rewardPayload(n,c,st.trim()===''?'unl':st.trim(),v,pr);
  if(!body) return;
  await run(async ()=>{ await send('PATCH','/admin/rewards/'+r.id,body); });
}
async function toggleReward(i){
  const r = LAST_REWARDS[i]; if(!r){ alert('Row stale — reload.'); return; }
  await run(async ()=>{ await send('PATCH','/admin/rewards/'+r.id,{
      category:r.category, name:r.name, description:r.description||'', provider:r.provider||'',
      points_cost:r.points_cost, value_label:r.value_label, value_amount:null, currency:'EGP',
      icon:r.icon||'card_giftcard', is_active:!r.is_active,
      stock:(r.stock==null?null:r.stock), requires_destination:!!r.requires_destination}); });
}
async function delReward(i){
  const r = LAST_REWARDS[i]; if(!r) return;
  if(!confirm('Delete reward "'+r.name+'" from the catalog? Past redemptions keep their records.')) return;
  await run(async ()=>{ const rr=await send('DELETE','/admin/rewards/'+r.id); alert('Deleted '+(rr.deleted||r.id)); });
}

async function addFacultyPrompt(){
  const n = ask('Faculty name:'); if(n===undefined||!n) return;
  await run(async ()=>{ await send('POST','/admin/faculties',{name:n.trim()}); alert('Faculty added.'); });
}
async function renameFaculty(i){
  const f = LAST_FACULTIES[i]; if(!f) return;
  const n = ask('Rename faculty:', f.name); if(n===undefined||!n) return;
  await run(async ()=>{ await send('PATCH','/admin/faculties/'+f.id,{name:n.trim()}); });
}
async function delFaculty(i){
  const f = LAST_FACULTIES[i]; if(!f) return;
  if(!confirm('Delete faculty "'+f.name+'"? Only faculties with no students can be deleted.')) return;
  await run(async ()=>{ const r=await send('DELETE','/admin/faculties/'+f.id); alert('Deleted '+(r.deleted||f.id)); });
}

const SECTIONS = ['overview','faculties','students','stations','deposits','challenges','rewards','health'];
function buildTabs() {
  const nav = document.getElementById('tabs');
  for (const s of SECTIONS) {
    const b = document.createElement('button');
    b.textContent = s[0].toUpperCase() + s.slice(1);
    b.id = 'tab-' + s;
    b.onclick = () => show(s);
    nav.appendChild(b);
  }
}
function show(s) {
  currentTab = s;
  for (const x of SECTIONS) {
    document.getElementById('tab-'+x).classList.toggle('active', x===s);
    document.getElementById('s-'+x).classList.toggle('active', x===s);
  }
  render(s).catch(e => console.error(e));
}

function esc(v){ return v==null?'':String(v).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function pill(status){
  const good=['confirmed','online','IDLE','fulfilled','used','approved'];
  const bad=['rejected','expired','cancelled','disabled'];
  const cls=good.includes(status)?'ok':bad.includes(status)?'bad':'warn';
  return '<span class="pill '+cls+'">'+esc(status||'-')+'</span>';
}
async function send(method, path, body){
  const r = await fetch('/api/v1'+path, {
    method: method,
    headers:{'Content-Type':'application/json', Authorization:'Bearer '+TOKEN},
    body: body==null ? undefined : JSON.stringify(body)
  });
  if (!r.ok) {
    let msg = 'HTTP '+r.status;
    try { const j = await r.json(); msg = (j.detail && (typeof j.detail==='string'?j.detail:JSON.stringify(j.detail))) || j.error || msg; } catch(e){}
    throw new Error(msg);
  }
  return r.json();
}
function ask(label, current){ const v = prompt(label, current==null?'':String(current)); return v===null ? undefined : v.trim(); }
async function run(fn, refreshTab){ try { await fn(); } catch(e){ alert('Failed: '+e.message); } if(refreshTab!==false) await render(currentTab); }

async function action(path, body){
  const r = await fetch('/api/v1'+path, {
    method:'POST', headers:{'Content-Type':'application/json', Authorization:'Bearer '+TOKEN},
    body: JSON.stringify(body||{})
  });
  if (!r.ok) {
    let msg = 'HTTP '+r.status;
    try { msg = (await r.json()).error || msg; } catch(e){}
    alert('Action failed: '+msg);
  }
  await render(currentTab);
}
function table(headers, rows){
  return '<table><tr>'+headers.map(h=>'<th>'+h+'</th>').join('')+'</tr>'+
    rows.map(r=>'<tr>'+r.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')+'</table>';
}
function cards(items){
  return '<div class="cards">'+items.map(i=>'<div class="card"><span>'+i.label+'</span><b>'+i.value+'</b></div>').join('')+'</div>';
}

async function render(s) {
  const el = document.getElementById('s-'+s);
  if (s==='overview') {
    const d = await api('/admin/overview');
    el.innerHTML = cards([
      {label:'Students', value:d.total_students},
      {label:'Deposits', value:d.total_deposits},
      {label:'Recycled', value:d.recycled_kg+' kg'},
      {label:'Points awarded', value:d.points_awarded},
      {label:'CO2 saved', value:d.co2_saved_kg+' kg'},
      {label:'Active stations', value:d.active_stations},
      {label:'Offline stations', value:d.offline_stations},
      {label:"Today's activity", value:d.today_activity},
    ]);
  }
  else if (s==='faculties') {
    const d = await api('/admin/faculties');
    LAST_FACULTIES = d.items || [];
    el.innerHTML =
      '<div style="margin-bottom:8px"><button style="width:auto;margin:0" onclick="addFacultyPrompt()">+ Add faculty</button></div>'+
      table(['Rank','Faculty','Students','Points','Recycled kg','Items','Actions'],
        d.items.map((f,i)=>[f.rank, esc(f.name), f.students, f.points, f.recycled_kg, f.items,
          '<button style="width:auto;margin:2px" onclick="renameFaculty('+i+')">Rename</button>'+
          (f.students===0?'<button style="width:auto;margin:2px" onclick="delFaculty('+i+')">Delete</button>':'')]));
  }
  else if (s==='students') {
    const q = document.getElementById('q-students')?.value || '';
    const d = await api('/admin/users?q='+encodeURIComponent(q)+'&limit=50');
    LAST_USERS = d.items || [];
    el.innerHTML =
      '<div style="margin-bottom:10px;display:flex;gap:8px">'+
      '<input id="q-students" placeholder="Search name / email / student ID" value="'+esc(q)+'" onkeydown="if(event.key===\\'Enter\\')render(\\'students\\')" style="max-width:320px">'+
      '<button style="width:auto;margin:0" onclick="render(\\'students\\')">Search</button></div>'+
      '<div style="margin-bottom:8px"><button style="width:auto;margin:0" onclick="addUserPrompt()">+ Add student</button></div>'+
      table(['Name','Student ID','Email','Faculty','Role','Points','Status','Actions'],
        d.items.map((u,i)=>[esc(u.name), esc(u.student_code), esc(u.email), esc(u.faculty_name),
          esc(u.role), u.points,
          u.is_active?'<span class="pill ok">active</span>':'<span class="pill bad">inactive</span>',
          '<button style="width:auto;margin:2px" onclick="editUser('+i+')">Edit</button>'+
          '<button style="width:auto;margin:2px" onclick="toggleUser('+i+')">'+(u.is_active?'Deactivate':'Activate')+'</button>'+
          (u.role==='admin' ? '' : '<button style="width:auto;margin:2px" onclick="delUser('+i+')">Delete</button>')]));

    if(q && document.getElementById('q-students')) document.getElementById('q-students').focus();
  }
  else if (s==='stations') {
    const d = await api('/admin/stations');
    LAST_STATIONS = d.items || [];
    el.innerHTML =
      '<div style="margin-bottom:8px"><button style="width:auto;margin:0" onclick="addStationPrompt()">+ Add station</button></div>'+
      table(['Code','Name','Status','Actions'],
        d.items.map((x,i)=>['<b>'+esc(x.station_code)+'</b>', esc(x.name), pill(x.status),
          '<button style="width:auto;margin:2px" onclick="renameStation('+i+')">Rename</button>'+
          '<button style="width:auto;margin:2px" onclick="toggleStation('+i+')">'+(x.status==='online'?'Disable':'Enable')+'</button>'+
          '<button style="width:auto;margin:2px" onclick="delStation('+i+')">Delete</button>']));
  }
  else if (s==='deposits') {
    const d = await api('/admin/deposits?limit=50');
    el.innerHTML = table(['Operation','Student','Station','AI class','Conf.','Routing','Weight g','Points','Status','When'],
      d.items.map(x=>['<code>'+esc(x.operation_id)+'</code>', esc(x.student), esc(x.station),
        esc(x.ai_class||'-'), x.confidence!=null?x.confidence:'-', esc(x.routing||'-'),
        x.measured_weight_g!=null?x.measured_weight_g:'-', x.points,
        pill(x.status)+(x.reject_reason?'<br><small>'+esc(x.reject_reason)+'</small>':''),
        esc((x.created_at||'').slice(0,19).replace('T',' '))]));
  }
  else if (s==='challenges') {
    const d = await api('/admin/challenges');
    LAST_CHALLENGES = d.items || [];
    el.innerHTML =      '<div style="margin-bottom:8px"><button style="width:auto;margin:0" onclick="addChallengePrompt()">+ Add challenge</button></div>'+
      (d.items.length ? table(['Title','Class','Target kg','Reward pts','Status','Actions'],
        d.items.map((c,i)=>[esc((c.theme_emoji||'')+' '+c.title), esc(c.waste_class), c.target_kg, c.reward_points,
          c.active?'<span class="pill ok">active</span>':'<span class="pill warn">off</span>',
          '<button style="width:auto;margin:2px" onclick="editChallenge('+i+')">Edit</button>'+
          '<button style="width:auto;margin:2px" onclick="toggleChallenge('+i+')">'+(c.active?'Deactivate':'Activate')+'</button>'+
          '<button style="width:auto;margin:2px" onclick="delChallenge('+i+')">Delete</button>']))
        : '<p class="sub">No challenges yet.</p>');  }
  else if (s==='rewards') {
    const [cat, queue] = await Promise.all([
      api('/admin/rewards'),
      api('/admin/rewards/redemptions?limit=50')
    ]);
    LAST_REWARDS = cat.items || [];
    const catalog = cat.items.length ? table(
      ['Name','Category','Provider','Value','Cost pts','Stock','Redeemed','Status','Actions'],
      cat.items.map((r,i)=>[esc(r.name), esc(r.category), esc(r.provider||'-'), esc(r.value_label),
        r.points_cost, r.stock==null?'unlimited':r.stock, r.redemption_count,
        r.is_active?'<span class="pill ok">active</span>':'<span class="pill warn">hidden</span>',
        '<button style="width:auto;margin:2px" onclick="editReward('+i+')">Edit</button>'+
        '<button style="width:auto;margin:2px" onclick="toggleReward('+i+')">'+(r.is_active?'Hide':'Show')+'</button>'+
        '<button style="width:auto;margin:2px" onclick="delReward('+i+')">Delete</button>']))
      : '<p class="sub">Catalog is empty.</p>';
    const catHeader = '<div style="display:flex;align-items:center;justify-content:space-between;margin:18px 0 8px">'+
      '<h3 style="margin:0">Catalog</h3>'+
      '<button style="width:auto;margin:0" onclick="addRewardPrompt()">+ Add reward</button></div>';
    const q = queue.items.length ? table(
      ['When','Student','Reward','Points','Destination','Code','Status','Action'],
      queue.items.map(x=>[
        esc((x.created_at||'').slice(0,19).replace('T',' ')),
        '<b>'+esc(x.student.name)+'</b><br><small>'+esc(x.student.email)+'</small>',
        esc(x.reward.name)+' <small>('+esc(x.reward.value_label)+')</small>',
        x.points_spent, esc(x.destination_masked||'-'), '<code>'+esc(x.redemption_code||'-')+'</code>',
        pill(x.status)+(x.admin_note?'<br><small>'+esc(x.admin_note)+'</small>':''),
        (x.status==='pending' ? '<button style="width:auto;margin:2px" onclick="action(\\'/admin/rewards/redemptions/'+x.id+'/approve\\')">Approve</button>' : '')+
        (x.status==='pending'||x.status==='approved' ?
          '<button style="width:auto;margin:2px" onclick="action(\\'/admin/rewards/redemptions/'+x.id+'/fulfill\\')">Fulfill</button>'+
          '<button style="width:auto;margin:2px" onclick="if(confirm(\\'Reject and refund '+x.points_spent+' points?\\'))action(\\'/admin/rewards/redemptions/'+x.id+'/reject\\',{admin_note:\\'Rejected from console\\'})">Reject</button>' : '')+
        (x.status==='available' ? '<button style="width:auto;margin:2px" onclick="action(\\'/admin/rewards/redemptions/'+x.id+'/mark-used\\')">Mark used</button>' : '')
      ]))
      : '<p class="sub">No redemptions yet.</p>';
    el.innerHTML =
      '<h3 style="margin:4px 0 8px">Redemption queue <span class="sub">(cash payouts need manual transfer, then Fulfill)</span></h3>'+
      q +
      catHeader+
      '<div id="catalog-wrap">'+
      catalog+'</div>';
  }
  else if (s==='health') {
    let backend='DOWN', db='-', mqtt='-', ai='-';
    try {
      const h = await (await fetch('/health')).json();
      backend='UP'; db=h.db; mqtt=h.mqtt; ai=h.ai;
    } catch(e){}
    let stationsHtml='<i>unavailable</i>';
    try {
      const st=(await api('/admin/stations')).items;
      stationsHtml=st.map(x=>esc(x.station_code)+': '+x.status+(x.last_seen?' (seen '+x.last_seen.slice(0,19)+')':'')).join('<br>')||'<i>none registered</i>';
    } catch(e){}
    el.innerHTML = '<div id="health">'+
      '<div><span>Backend</span>'+pill(backend)+'</div>'+
      '<div><span>Database</span>'+pill(db==='ok'?'confirmed':db)+'</div>'+
      '<div><span>MQTT broker</span>'+pill(mqtt==='ok'?'confirmed':mqtt)+'</div>'+
      '<div><span>AI service</span>'+pill(ai==='ok'?'confirmed':ai)+'</div>'+
      '<div style="display:block"><span style="color:var(--muted);font-size:12px">Station connectivity</span><br>'+stationsHtml+'</div>'+
      '</div>';
  }
}
document.addEventListener('keydown', e => { if (e.key==='Enter' && !TOKEN) login(); });
</script>
</body>
</html>"""


@router.get("/admin/ui", response_class=HTMLResponse)
def admin_console() -> HTMLResponse:
    return HTMLResponse(_PAGE)
