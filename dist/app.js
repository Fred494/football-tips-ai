'use strict';
const main=document.querySelector('main');
const esc=x=>String(x??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct=x=>typeof x==='number'?(x*100).toFixed(1)+'%':'—';
const pretty=d=>new Intl.DateTimeFormat('en-GB',{weekday:'long',day:'numeric',month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(d+'T12:00Z'));
const dayNow=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Lisbon',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
function offset(day,n){const d=new Date(day+'T12:00Z');d.setUTCDate(d.getUTCDate()+n);return d.toISOString().slice(0,10);}
function loadPref(){try{return JSON.parse(localStorage.getItem('edge-disabled'))||[];}catch{return [];}}
let data,disabled=new Set(loadPref());

const ranked=m=>m.prob!=null&&!m.stale;
const getLeague=id=>data.leagues.find(l=>l.code===id);
const result=(m,t)=>{const [h,a]=m.score;const d=(h-a)*(t===m.home?1:-1);return d>0?'W':d<0?'L':'D';};
function table(headers,rows){return '<div class="table-scroll"><table><thead><tr>'+headers.map(x=>'<th scope="col">'+esc(x)+'</th>').join('')+'</tr></thead><tbody>'+rows+'</tbody></table></div>';}
const row=(items,highlight=false)=>'<tr'+(highlight?' class="highlight"':'')+'>'+items.map(x=>'<td>'+esc(x)+'</td>').join('')+'</tr>';
const number=x=>x==null?'—':x;
function formBox(matches,t,stats,long,international){
  const context=international?'International matches':'League matches';
  return '<section class="box"><h3>'+esc(t)+' · Last five</h3><p>League matches · '+stats.n+' available</p>'+
    table(['Date','Opponent','Venue','Score (H–A)','Result'],matches.map(m=>row([m.day,t===m.home?m.away:m.home,t===m.home?'Home':'Away',m.score.join('–'),result(m,t)])).join(''))+
    '<p>'+stats.w+'W / '+stats.d+'D / '+stats.l+'L · Goals '+stats.gf+'–'+stats.ga+' · '+stats.pts+' pts · '+number(stats.ppg)+' PPG</p><small>Last '+long.n+' matches · '+long.pts+' points</small></section>';
}
function card(m){
  const [h,a,hv,av,hr,ar]=m.stats;
  const rank=t=>{const n=m.table.findIndex(r=>r.team===t);return n>=0?'#'+(n+1):'—';};
  const comparison=[[m.international?'Group points/game':'Season points/game',h.ppg,a.ppg],['Goals/game',h.gpg,a.gpg],['Goals conceded/game',h.gapg,a.gapg],['Home vs away points/game',hv.ppg,av.ppg],['Home vs away win rate',hv.n?pct(hv.w/hv.n):null,av.n?pct(av.w/av.n):null],['Home vs away draw rate',hv.n?pct(hv.d/hv.n):null,av.n?pct(av.d/av.n):null],['Venue sample',hv.n,av.n],['Last five points',hr.pts,ar.pts]];
  const explanation=(ranked(m)?m.why:null)?.map(v=>'<p class="reason"><strong>'+esc(v.name)+'</strong> · '+v.value.toFixed(2)+'. '+(v.delta>=0?'+':'')+(v.delta*100).toFixed(1)+' percentage points versus the training median.</p>').join('')||(m.stale?'<p>The league feed has no verified result from the last 21 days. The estimate is excluded from the default ranking.</p>':'<p>Forecast withheld when either team lacks five prior league results or three current-season games, or when no model is available.</p>');
  return '<details class="fixture"><summary><div class="meta">'+esc(getLeague(m.league).name)+'<small>'+esc(m.kickoff?m.kickoff+' Lisbon time':'Kickoff time unavailable')+'</small></div>'+
    '<div class="teams"><span>'+crest(m.home)+'<strong>'+esc(m.home)+'</strong><small>'+rank(m.home)+'</small></span><span>'+crest(m.away)+'<strong>'+esc(m.away)+'</strong><small>'+rank(m.away)+'</small></span></div>'+
    '<div class="score"><span class="market">'+esc(m.market)+'</span> '+pct(m.prob)+'<small>Match analysis <span aria-hidden="true">⌄</span></small></div></summary><div class="inside grid">'+
    '<section class="box full"><h3>Why this prediction?</h3>'+explanation+(m.why?'<small>Each factor is varied individually. Effects may overlap and are approximate.</small>':'')+'</section>'+
    (m.international&&m.source?.startsWith('https://www.uefa.com/')?'<section class="box full"><a href="'+esc(m.source)+'">Official UEFA match page</a></section>':'')+playerBox(m)+
    formBox(m.form[0],m.home,hr,m.long[0],m.international)+formBox(m.form[1],m.away,ar,m.long[1],m.international)+
    '<section class="box"><h3>Team performance</h3>'+table(['Metric',m.home,m.away],comparison.map(x=>row(x)).join(''))+'</section>'+
    '<section class="box"><h3>Probability breakdown</h3>'+(ranked(m)?table(['Outcome','Estimate'],['Home win','Draw','Away win','1X · Home or draw','X2 · Draw or away'].map((k,i)=>row([k,pct([...m.breakdown,1-m.breakdown[2],1-m.breakdown[0]][i])])).join('')):'<p>No estimate for this fixture.</p>')+'</section>'+
    '<section class="box full"><h3>Reconstructed standings</h3><p>'+esc(m.season)+' · Before '+esc(data.day)+' · Ordered by points, goal difference and goals scored. Official deductions and phase rules may differ.</p>'+table(['#','Team','P','W','D','L','GF','GA','GD','Pts','PPG'],m.table.map((r,i)=>row([i+1,r.team,r.n,r.w,r.d,r.l,r.gf,r.ga,r.gd,r.pts,r.ppg],[m.home,m.away].includes(r.team))).join(''))+'</section>'+
    (m.h2h.length?'<section class="box full"><h3>Recent league meetings</h3>'+table(['Date','Home','Score','Away'],m.h2h.map(x=>row([x.day,x.home,x.score.join('–'),x.away])).join(''))+'</section>':'')+'</div></details>';
}
function playerBox(m){
  const entries=(m.players||[]).filter(Boolean);
  const message=m.playersUsed?'Verified player form and availability contributed to this forecast.':
    entries.length?'Available player reports are shown below. This forecast uses team data.':
      'Verified player ratings, injuries and suspensions are unavailable for this fixture. The forecast uses team data.';
  return '<section class="box full"><h3>Player form and availability</h3><p>'+esc(message)+'</p>'+
    entries.map(entry=>{
      const players=entry.players.filter(p=>p.status!=='available').concat(entry.players.filter(p=>p.status==='available').sort((a,b)=>b.rating-a.rating).slice(0,3));
      return '<h4>'+esc(entry.team)+'</h4><small>'+esc(entry.source)+' · '+esc(entry.observedAt)+'</small>'+
        table(['Player','Status','Recent rating','Minutes share'],players.map(p=>row([p.name,p.status,p.rating,pct(p.minutesShare)])).join(''));
    }).join('')+'</section>';
}
function hero(k,h,p){return '<section class="hero"><div class="kicker">'+esc(k)+'</div><h1>'+esc(h)+'</h1><p>'+esc(p)+'</p></section>';}
function tile(label,value){return '<div class="tile"><strong>'+esc(value)+'</strong><small>'+esc(label)+'</small></div>';}
const minimumPick = () => data.pickMinimum ?? .75;
let windowStart=null;
function loadVisibleDays(){
  try {
    const saved=JSON.parse(localStorage.getItem('edge-visible-days'));
    return new Set(Array.isArray(saved)?saved:[]);
  } catch {return new Set();}
}
const visibleDays=loadVisibleDays();
const dateLabel=(day,options)=>new Intl.DateTimeFormat('en-GB',{...options,timeZone:'UTC'}).format(new Date(day+'T12:00Z'));
function crest(team){
  const initials=team.split(/\s+/).filter(word=>word.length>1).slice(0,2).map(word=>word[0]).join('').toUpperCase();
  const path=data.crests?.[team];
  return '<span class="crest"><span aria-hidden="true">'+esc(initials)+'</span>'+(path?'<img src="'+esc(path)+'" alt="" loading="lazy">':'')+'</span>';
}
function refreshMatches(){
  const today=dayNow();
  const start=windowStart||today;
  const groups=[start,...[...visibleDays].filter(d=>d>start&&d<=offset(start,3)).sort()];
  document.querySelector('#results').innerHTML=groups.map(day=>{
    const fixtures=data.matches.filter(m=>m.day===day&&!disabled.has(m.league));
    const picks=fixtures.filter(m=>!m.stale&&m.prob>minimumPick())
      .sort((a,b)=>Number(getLeague(b.league).priority)-Number(getLeague(a.league).priority)||b.prob-a.prob||a.home.localeCompare(b.home));
    let message='No picks meet the confidence threshold for this date.';
    if(!fixtures.length) message=day===today?'No fixtures are listed today in the available feeds.':'No fixtures are listed for this date in the available feeds.';
    else if(!fixtures.some(m=>ranked(m))) message='There are fixtures for this date, but the available data is insufficient to rank them.';
    return '<section class="day"><div class="day-title"><div><h2>'+(day===today?'Today':pretty(day))+'</h2>'+(day===today?'<span>'+pretty(day)+'</span>':'')+'</div><span class="count">'+picks.length+' '+(picks.length===1?'pick':'picks')+'</span></div>'+
      (picks.length?picks.map(card).join(''):'<div class="empty"><strong>'+esc(message)+'</strong><span>'+(day===today?'Select another date above to check its picks.':'Check another date or change your selected leagues.')+'</span></div>')+'</section>';
  }).join('');
  document.querySelector('#results').querySelectorAll('img').forEach(img=>img.addEventListener('error',()=>img.remove(),{once:true}));
}
function predictions(){
  const today=dayNow();
  const start=windowStart||today;
  const dates=Array.from({length:4},(_,i)=>offset(start,i));
  const next=data.matches.filter(m=>m.day>dates.at(-1)&&!disabled.has(m.league)&&ranked(m)&&m.prob>minimumPick())
    .map(m=>m.day).sort()[0];
  const jump=windowStart?'<button id="jump-window" class="window-button">Back to today</button>':
    next?'<button id="jump-window" class="window-button">Next picks · '+esc(dateLabel(next,{day:'numeric',month:'short'}))+'</button>':'';

  main.innerHTML=hero('Double chance · 1X / X2','Top match picks','Explore the strongest model predictions for today and the next three days.')+
    (data.day!==today?'<p class="notice">Forecast snapshot from '+esc(data.day)+'. A newer refresh is unavailable.</p>':'')+
    '<div class="date-grid" aria-label="Match dates">'+dates.map((day,i)=>{
      const active=i===0||visibleDays.has(day);
      return '<button class="date-chip '+(active?'active':'')+'" data-day="'+day+'" aria-pressed="'+active+'" '+(i===0?'disabled':'')+'><span>'+esc(day===today?'Today':dateLabel(day,{weekday:'short'}))+'</span><strong>'+esc(dateLabel(day,{day:'numeric',month:'short'}))+'</strong></button>';
    }).join('')+'</div><p class="criteria">All picks above '+Math.round(minimumPick()*100)+'% estimated probability. Major leagues appear first.</p>'+jump+'<div id="results"></div>';
  const jumpButton=document.querySelector('#jump-window');
  if(jumpButton)jumpButton.onclick=()=>{windowStart=windowStart?null:next;predictions();};
  document.querySelectorAll('[data-day]:not([disabled])').forEach(b=>b.onclick=()=>{
    if(visibleDays.has(b.dataset.day))visibleDays.delete(b.dataset.day);else visibleDays.add(b.dataset.day);
    const active=visibleDays.has(b.dataset.day);
    try {localStorage.setItem('edge-visible-days',JSON.stringify([...visibleDays]));} catch {}
    b.setAttribute('aria-pressed',String(active));
    b.classList.toggle('active',active);
    refreshMatches();
  });
  refreshMatches();
}
function leagues(){
  main.innerHTML=hero('Competition coverage','Your leagues','Select the competitions you want to see in daily predictions.')+
    '<p>Fixture checks show when the current schedule was fetched. Results show the latest verified score date and any recent fixtures still missing a score.</p><div class="coverage">'+
    [...data.leagues].sort((a,b)=>Number(b.priority)-Number(a.priority)).map(l=>'<section class="box"><span class="kicker">'+esc(l.country)+'</span><h3>'+esc(l.name)+'</h3><label><input type="checkbox" data-code="'+esc(l.code)+'" '+(!disabled.has(l.code)?'checked':'')+'> Include in predictions</label><p>'+l.completed+' results · '+l.upcoming+' fixtures in forecast window</p>'+(l.resultsFeed.length?'<p>Scores supplemented by Football-Data.co.uk.</p>':'')+'<p>'+esc(l.fixtureStatus)+(l.fixturesChecked?' · '+esc(l.fixturesChecked.slice(0,10)):'')+(l.unresolved?' · '+l.unresolved+' recent scores missing':'')+'</p><small>'+esc(l.seasons.join(', ')||(l.international?'International coverage':'No season feed found'))+(l.latest?' · Latest result '+esc(l.latest):'')+'</small>'+(l.table.length?'<details><summary>Reconstructed standings</summary>'+table(['#','Team','P','GD','Pts'],l.table.map((r,i)=>row([i+1,r.team,r.n,r.gd,r.pts])).join(''))+'</details>':'')+'</section>').join('')+'</div>';
  document.querySelectorAll('[data-code]').forEach(el=>el.onchange=()=>{if(el.checked)disabled.delete(el.dataset.code);else disabled.add(el.dataset.code);localStorage.setItem('edge-disabled',JSON.stringify([...disabled]));});
}
function performance(){
  const e=data.evaluation;
  const intl=data.internationalEvaluation;
  main.innerHTML=hero('Out-of-sample evaluation','Model performance','Historical forecasts tested on matches dated after training and calibration.')+
    (!e?'<p class="notice">Insufficient verified results to evaluate a model.</p>':
      '<p>'+esc(e.name)+' · Test window '+esc(e.start)+' to '+esc(e.end)+' · '+e.train+' training matches since '+esc(e.trainingStart)+' · '+e.validation+' calibration matches</p>'+
      '<div class="stats">'+tile('Test matches',e.n)+tile('Selected outcome hit rate',pct(e.selected))+tile('1X hit rate',pct(e.hit[0]))+tile('X2 hit rate',pct(e.hit[1]))+tile('Multiclass log loss',e.logLoss)+tile('Multiclass Brier',e.brier)+'</div>'+
      '<div class="grid"><section class="box full"><h3>Calibration by probability band</h3>'+table(['Band','Matches','Mean forecast','Observed success'],e.bands.map(b=>row([Math.round(b.lo*100)+'–'+Math.round(b.hi*100)+'%',b.n,pct(b.expected),pct(b.observed)])).join(''))+'</section>'+
      '<section class="box"><h3>Historical '+Math.round(minimumPick()*100)+'% filter</h3>'+table(['Qualifying matches','Hit rate','Matchdays with picks'],row([e.displayed.n,pct(e.displayed.hit),e.displayed.days+' / '+e.displayed.matchDays]))+'<p>Tests the probability rule on completed fixtures. Historical feed availability could not be replayed.</p></section>'+
      '<section class="box"><h3>Model comparison</h3>'+table(['Model','Training matches','Log loss','Brier'],e.models.map(m=>row([m.name,m.train,m.logLoss,m.brier])).join(''))+'</section>'+
      '<section class="box full"><h3>Performance by league</h3>'+table(['League','Matches','Selected hit rate','Log loss'],Object.entries(e.leagues).map(([k,v])=>row([getLeague(k).name,v.n,pct(v.selected),v.logLoss])).join(''))+'</section></div>'+(intl?'<section class="box"><h3>National team model</h3><p>'+intl.n+' held-out international matches · '+intl.above+' above the threshold · '+pct(intl.hitAbove)+' hit rate</p></section>':''));
}
function route(){
  const page=['#leagues','#performance'].includes(location.hash)?location.hash:'#predictions';
  document.querySelectorAll('nav a').forEach(a=>a.getAttribute('href')===page?a.setAttribute('aria-current','page'):a.removeAttribute('aria-current'));
  ({'#predictions':predictions,'#leagues':leagues,'#performance':performance})[page]();
}
fetch('snapshot.json').then(r=>{if(!r.ok)throw Error('Snapshot unavailable');return r.json();}).then(x=>{data=x;document.querySelector('#freshness').textContent='Snapshot '+data.day;route();window.addEventListener('hashchange',route);}).catch(()=>{main.textContent='The forecast snapshot could not be loaded. Refresh to try again.';});
