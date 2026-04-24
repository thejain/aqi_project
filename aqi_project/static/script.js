/* ════════════════════════════════════════════════════════
   AQI Intelligence Dashboard v3 — script.js
   New: AQI status card, pollutant grid, compact compass
════════════════════════════════════════════════════════ */
'use strict';

let currentCity  = '';
let currentAQI   = 0;
let currentRange = '30d';
let zoneCities   = {};
let histChart    = null;
let hourlyChart  = null;
let compassDeg   = 0;
let compassAnimId= null;

const $ = id => document.getElementById(id);

/* ── AQI Zone helpers ─────────────────────────────── */
const ZONES = [
  {lo:0,   hi:50,  label:'Good',         cls:'aqi-good',  color:'#22c55e', badge:'#16a34a'},
  {lo:51,  hi:100, label:'Satisfactory', cls:'aqi-sat',   color:'#eab308', badge:'#a16207'},
  {lo:101, hi:200, label:'Moderate',     cls:'aqi-mod',   color:'#f97316', badge:'#c2410c'},
  {lo:201, hi:300, label:'Poor',         cls:'aqi-poor',  color:'#ef4444', badge:'#b91c1c'},
  {lo:301, hi:400, label:'Very Poor',    cls:'aqi-vpoor', color:'#a855f7', badge:'#7e22ce'},
  {lo:401, hi:9999,label:'Severe',       cls:'aqi-severe',color:'#9f1239', badge:'#881337'},
];
const zoneFor = aqi => ZONES.find(z => aqi >= z.lo && aqi <= z.hi) || ZONES[ZONES.length-1];

/* ── Fetch ────────────────────────────────────────── */
const api = async url => {
  try {
    const r = await fetch(url);
    if(!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  } catch(e) {
    console.error(`[API Error] ${url}:`, e.message);
    throw e;
  }
};

/* ── Loader ────────────────────────────────────────── */
const loader = on => $('loaderOverlay').classList.toggle('active', on);

/* ═══════════════════════════════════════════════════
   INIT
═══════════════════════════════════════════════════ */
async function init() {
  try {
    const cities = await api('/api/cities');
    const sel = $('citySelect');
    sel.innerHTML = '';
    cities.cities.forEach(c => { const o = document.createElement('option'); o.value = o.textContent = c; sel.appendChild(o); });
    sel.addEventListener('change', () => loadCity(sel.value));
    await loadCity(cities.cities[0]);
    // Load metrics separately
    try {
      const metrics = await api('/api/model_metrics');
      $('metricR2').textContent  = metrics.r2.toFixed(4);
      $('metricMAE').textContent = metrics.mae + ' AQI';
    } catch(e) { console.error('Metrics:', e); }
  } catch(e) { console.error('Init:', e); }
}

/* ═══════════════════════════════════════════════════
   CITY LOAD
═══════════════════════════════════════════════════ */
async function loadCity(city) {
  if (!city) return;
  currentCity = city;
  loader(true);
  $('cityBadge').textContent  = city;
  $('pollCityLbl').textContent = city;

  try {
    const [liveData, weatherData, windData, pastData, zoneData] = await Promise.all([
      api(`/api/live_aqi?city=${encodeURIComponent(city)}`),
      api(`/api/weather?city=${encodeURIComponent(city)}`),
      api(`/api/wind?city=${encodeURIComponent(city)}`),
      api(`/api/past_aqi?city=${encodeURIComponent(city)}`),
      api('/api/zone_cities'),
    ]);
    currentAQI = liveData.aqi;
    zoneCities = zoneData.zones;

    renderAQICard(liveData);
    renderPollutants(liveData);
    renderPollSection(city);
    renderWeather(weatherData);
    renderWind(windData);
    renderPastCards(pastData);
    renderHealth(liveData.aqi);
    loadForecast(city);
    loadHourly(city);
    loadHistory(null, currentRange);
    $('lastUpdated').textContent = new Date().toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit'});
  } catch(e) { console.error('City load:', e); }
  finally { loader(false); }
}

/* ═══════════════════════════════════════════════════
   AQI STATUS CARD  (replaces speedometer)
═══════════════════════════════════════════════════ */
function renderAQICard(data) {
  const aqi  = data.aqi;
  const zone = zoneFor(aqi);
  const card = $('aqiCard');

  /* Background class */
  ZONES.forEach(z => card.classList.remove(z.cls));
  card.classList.add(zone.cls);

  /* Badge */
  const badge = $('aqiBadge');
  badge.textContent = zone.label;
  badge.style.background = zone.badge;

  /* PM values */
  $('aqiPm25').textContent = data.pm25;
  $('aqiPm10').textContent = data.pm10;

  /* Animated number */
  animateNumber($('aqiNumber'), 0, aqi, 1200);

  /* Scale pointer — map 0-500 to 0-100% */
  const pct = Math.min(100, (aqi / 500) * 100);
  setTimeout(() => { $('aqiScalePtr').style.left = pct + '%'; }, 100);

  /* Source chip update */
  const src = data.source === 'live' ? '● Live' : '◌ Historical';
}

function animateNumber(el, from, to, dur) {
  const t0 = performance.now();
  function step(now) {
    const t    = Math.min((now - t0) / dur, 1);
    const ease = t < .5 ? 4*t*t*t : 1 - Math.pow(-2*t+2, 3)/2;
    el.textContent = Math.round(from + (to - from) * ease);
    if (t < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

/* ═══════════════════════════════════════════════════
   POLLUTANTS CARD (in live section)
═══════════════════════════════════════════════════ */
const POLL_CFG = [
  {key:'pm25', sym:'PM₂.₅', icon:'PM',  sub:'Fine particles',   color:'#4f9eff', max:250, safe:12,  mod:35},
  {key:'pm10', sym:'PM₁₀',  icon:'PM',  sub:'Coarse particles', color:'#f97316', max:430, safe:50,  mod:100},
  {key:'so2',  sym:'SO₂',   icon:'SO₂', sub:'Sulphur dioxide',  color:'#eab308', max:380, safe:40,  mod:80},
  {key:'co',   sym:'CO',    icon:'CO',  sub:'Carbon monoxide',  color:'#ef4444', max:10000,safe:1000,mod:2000},
  {key:'no2',  sym:'NO₂',   icon:'NO₂', sub:'Nitrogen dioxide', color:'#a855f7', max:400, safe:40,  mod:80},
  {key:'o3',   sym:'O₃',    icon:'O₃',  sub:'Ozone',            color:'#22c55e', max:200, safe:50,  mod:100},
];

function renderPollutants(data) {
  const grid = $('pollGrid');
  grid.innerHTML = '';
  POLL_CFG.forEach(cfg => {
    const val = data[cfg.key] ?? 0;
    const statusColor = val <= cfg.safe ? '#22c55e' : val <= cfg.mod ? '#f97316' : '#ef4444';
    const statusLbl   = val <= cfg.safe ? 'Good' : val <= cfg.mod ? 'Moderate' : 'Unhealthy';
    const card = document.createElement('div');
    card.className = 'pc';
    card.innerHTML = `
      <div class="pc-head">
        <span class="pc-name">${cfg.sym}</span>
        <div class="pc-icon" style="color:${cfg.color};background:${cfg.color}18;border-color:${cfg.color}33">${cfg.icon}</div>
      </div>
      <div class="pc-val" style="color:${cfg.color}">${typeof val==='number'?val.toFixed(1):val}</div>
      <div class="pc-unit">µg/m³</div>
      <div class="pc-sub" style="color:${statusColor}">${statusLbl} · ${cfg.sub}</div>`;
    grid.appendChild(card);
  });
}

async function renderPollSection(city) {
  try {
    const data = await api(`/api/pollutant_comparison?city=${encodeURIComponent(city)}`);
    const grid = $('pollSectionGrid');
    grid.innerHTML = '';
    const items = [
      {sym:'PM₂.₅', val:data.pm25, unit:'µg/m³', sub:'Fine particles',   color:'#4f9eff'},
      {sym:'PM₁₀',  val:data.pm10, unit:'µg/m³', sub:'Coarse particles', color:'#f97316'},
      {sym:'NO₂',   val:data.no2,  unit:'µg/m³', sub:'Nitrogen dioxide', color:'#a855f7'},
      {sym:'SO₂',   val:data.so2,  unit:'µg/m³', sub:'Sulphur dioxide',  color:'#eab308'},
      {sym:'CO',    val:data.co,   unit:'mg/m³',  sub:'Carbon monoxide',  color:'#ef4444'},
      {sym:'O₃',    val:data.o3,   unit:'µg/m³', sub:'Ozone',            color:'#22c55e'},
    ];
    items.forEach((it,i) => {
      const div = document.createElement('div');
      div.className = 'pc';
      div.style.animationDelay = `${i*0.07}s`;
      div.innerHTML = `
        <div class="pc-head">
          <span class="pc-name">${it.sym}</span>
          <div class="pc-icon" style="color:${it.color};background:${it.color}18;border-color:${it.color}33;font-size:8px">${it.sym.replace('₂','2').replace('₁','1').replace('₃','3')}</div>
        </div>
        <div class="pc-val" style="color:${it.color}">${it.val}</div>
        <div class="pc-unit">${it.unit} (30d avg)</div>
        <div class="pc-sub">${it.sub}</div>`;
      grid.appendChild(div);
    });
  } catch(e) { console.error('PollSection:', e); }
}

/* ═══════════════════════════════════════════════════
   WEATHER
═══════════════════════════════════════════════════ */
function renderWeather(d) {
  $('wTemp').textContent   = d.temp + '°';
  $('wDesc').textContent   = d.description;
  $('wFeels').textContent  = `Feels like ${d.feels_like}°C`;
  $('wHum').textContent    = d.humidity + '%';
  $('wWind').textContent   = d.wind_speed + ' km/h';
  $('wPress').textContent  = d.pressure + ' hPa';
  $('wVis').textContent    = d.visibility + ' km';
  if (d.icon) { $('wIcon').src = `https://openweathermap.org/img/wn/${d.icon}@2x.png`; $('wIcon').alt = d.description; }
}

/* ═══════════════════════════════════════════════════
   WIND + ANIMATED COMPASS
═══════════════════════════════════════════════════ */
function renderWind(d) {
  $('windSpeed').textContent = d.speed_kph;
  $('windDir').textContent   = d.direction;
  $('windDeg').textContent   = d.deg + '°';
  $('windMsg').textContent   = d.dispersion;
  animateCompassTo(d.deg);
}

function animateCompassTo(targetDeg) {
  if (compassAnimId) cancelAnimationFrame(compassAnimId);
  let cur = compassDeg;
  function step() {
    const diff = ((targetDeg - cur + 540) % 360) - 180;
    cur += diff * 0.06;
    drawCompass(cur);
    if (Math.abs(diff) > 0.3) compassAnimId = requestAnimationFrame(step);
    else { compassDeg = targetDeg; drawCompass(targetDeg); }
  }
  step();
}

function drawCompass(deg) {
  const canvas = $('compassCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height, cx = W/2, cy = H/2, R = W/2 - 7;
  ctx.clearRect(0, 0, W, H);

  /* Rings */
  [[R, .09],[R*.7,.05],[R*.42,.04]].forEach(([r,a]) => {
    ctx.beginPath(); ctx.arc(cx,cy,r,0,2*Math.PI);
    ctx.strokeStyle=`rgba(255,255,255,${a})`; ctx.lineWidth=1; ctx.stroke();
  });

  /* Tick marks */
  for (let a = 0; a < 360; a += 22.5) {
    const rad = (a - 90) * Math.PI/180;
    const r1 = R - 3, r2 = R - (a%90===0 ? 14 : 7);
    ctx.beginPath();
    ctx.moveTo(cx + r1*Math.cos(rad), cy + r1*Math.sin(rad));
    ctx.lineTo(cx + r2*Math.cos(rad), cy + r2*Math.sin(rad));
    ctx.strokeStyle = a%90===0 ? 'rgba(255,255,255,.3)' : 'rgba(255,255,255,.1)';
    ctx.lineWidth = a%90===0 ? 1.5 : 0.8; ctx.stroke();
  }

  /* Cardinal labels */
  [['N',0,'#ef4444'],['E',90,'rgba(255,255,255,.32)'],['S',180,'rgba(255,255,255,.32)'],['W',270,'rgba(255,255,255,.32)']].forEach(([l,a,c]) => {
    const rad = (a - 90) * Math.PI/180, lr = R - 20;
    ctx.font = '600 9.5px Outfit,sans-serif';
    ctx.fillStyle = c; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(l, cx + lr*Math.cos(rad), cy + lr*Math.sin(rad));
  });

  /* Arrow */
  const windRad = (deg - 90) * Math.PI/180;
  const aLen = R * 0.54, tLen = R * 0.22;

  /* Subtle glow via double draw */
  ctx.strokeStyle = 'rgba(79,158,255,.3)'; ctx.lineWidth = 5; ctx.lineCap = 'round';
  ctx.beginPath();
  ctx.moveTo(cx - tLen*Math.cos(windRad), cy - tLen*Math.sin(windRad));
  ctx.lineTo(cx + aLen*Math.cos(windRad), cy + aLen*Math.sin(windRad));
  ctx.stroke();

  ctx.strokeStyle = '#4f9eff'; ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(cx - tLen*Math.cos(windRad), cy - tLen*Math.sin(windRad));
  ctx.lineTo(cx + aLen*Math.cos(windRad), cy + aLen*Math.sin(windRad));
  ctx.stroke();

  /* Arrowhead */
  const hx = cx + aLen*Math.cos(windRad), hy = cy + aLen*Math.sin(windRad);
  const ha = 0.45, hl = 9;
  ctx.beginPath();
  ctx.moveTo(hx, hy);
  ctx.lineTo(hx - hl*Math.cos(windRad-ha), hy - hl*Math.sin(windRad-ha));
  ctx.moveTo(hx, hy);
  ctx.lineTo(hx - hl*Math.cos(windRad+ha), hy - hl*Math.sin(windRad+ha));
  ctx.stroke();

  /* Center */
  ctx.beginPath(); ctx.arc(cx, cy, 4.5, 0, 2*Math.PI); ctx.fillStyle = '#4f9eff'; ctx.fill();
  ctx.beginPath(); ctx.arc(cx, cy, 1.8, 0, 2*Math.PI); ctx.fillStyle = '#fff'; ctx.fill();
}

/* ═══════════════════════════════════════════════════
   PAST + FORECAST CARDS
═══════════════════════════════════════════════════ */
function renderPastCards(data) {
  const wrap = $('pastCards');
  wrap.innerHTML = '';
  data.past.forEach((d, i) => {
    const zone = zoneFor(d.aqi);
    const card = document.createElement('div');
    card.className = 'fcast-day-card';
    card.style.setProperty('--fc', zone.color);
    card.style.animationDelay = `${i*0.07}s`;
    card.innerHTML = `
      <div class="fd-day">${['3 Days Ago','2 Days Ago','Yesterday'][i]}</div>
      <div class="fd-date">${d.date}</div>
      <div class="fd-aqi" style="color:${zone.color}">${d.aqi}</div>
      <div class="fd-bucket" style="color:${zone.color}">${zone.label}</div>`;
    wrap.appendChild(card);
  });
}

async function loadForecast(city) {
  try {
    const data = await api(`/api/forecast?city=${encodeURIComponent(city)}`);
    const wrap = $('forecastCards');
    wrap.innerHTML = '';
    data.predictions.forEach((p, i) => {
      const zone = zoneFor(p.aqi);
      const card = document.createElement('div');
      card.className = 'fcast-day-card';
      card.style.setProperty('--fc', zone.color);
      card.style.animationDelay = `${i*0.1}s`;
      card.innerHTML = `
        <div class="fd-day">${p.day}</div>
        <div class="fd-date">${p.date}</div>
        <div class="fd-aqi" style="color:${zone.color}">${p.aqi}</div>
        <div class="fd-bucket" style="color:${zone.color}">${zone.label}</div>`;
      wrap.appendChild(card);
    });
  } catch(e) { console.error('Forecast:', e); }
}

/* ═══════════════════════════════════════════════════
   HOURLY
═══════════════════════════════════════════════════ */
async function loadHourly(city) {
  try {
    const data = await api(`/api/hourly_forecast?city=${encodeURIComponent(city)}`);
    const strip = $('hourlyStrip');
    strip.innerHTML = '';
    data.hours.forEach(h => {
      const slot = document.createElement('div'); slot.className = 'h-slot';
      slot.innerHTML = `
        <div class="h-time">${h.label}</div>
        <img width="32" height="32" src="https://openweathermap.org/img/wn/${h.icon}.png" alt="${h.desc}" loading="lazy"/>
        <div class="h-temp">${h.temp}°</div>
        <div class="h-hum">💧${h.humidity}%</div>
        <div class="h-hum">💨${h.wind_kph}</div>`;
      strip.appendChild(slot);
    });
    if (hourlyChart) hourlyChart.destroy();
    const ctx = $('hourlyChart').getContext('2d');
    const base = currentAQI;
    const aqiVals = data.hours.map(h => Math.round(Math.max(10, Math.min(500, base * (0.85 + (h.humidity/100)*0.3 - (h.wind_kph/30)*0.2)))));
    const grad = ctx.createLinearGradient(0,0,0,100); grad.addColorStop(0,'rgba(79,158,255,.18)'); grad.addColorStop(1,'rgba(79,158,255,0)');
    hourlyChart = new Chart(ctx, {
      type:'line',
      data:{ labels:data.hours.map(h=>h.label), datasets:[{ label:'Est. AQI', data:aqiVals, borderColor:'#4f9eff', backgroundColor:grad, borderWidth:2, tension:0.42, fill:true, pointRadius:3, pointHoverRadius:6, pointBackgroundColor:aqiVals.map(v=>zoneFor(v).color), pointBorderColor:'transparent' }] },
      options:{ responsive:true, maintainAspectRatio:false, plugins:{ legend:{display:false}, tooltip:{ backgroundColor:'rgba(10,14,26,.97)', borderColor:'rgba(255,255,255,.1)', borderWidth:1, titleColor:'#7a8aaa', bodyColor:'#e2e8f8', padding:9, callbacks:{ label:ctx=>`AQI ~${ctx.parsed.y} — ${zoneFor(ctx.parsed.y).label}` } } }, scales:{ x:{grid:{display:false},ticks:{color:'#7a8aaa',font:{size:10}},border:{display:false}}, y:{grid:{color:'rgba(255,255,255,.03)'},ticks:{color:'#7a8aaa',font:{size:10}},border:{display:false},min:0} }, interaction:{mode:'index',intersect:false} }
    });
  } catch(e) { console.error('Hourly:', e); }
}

/* ═══════════════════════════════════════════════════
   HISTORICAL CHART
═══════════════════════════════════════════════════ */
async function loadHistory(btn, range) {
  if (btn) { document.querySelectorAll('.rtab').forEach(b => b.classList.remove('active')); btn.classList.add('active'); }
  currentRange = range;
  if (!currentCity) return;
  try {
    const data = await api(`/api/history_range?city=${encodeURIComponent(currentCity)}&range=${range}`);
    /* Stats */
    $('histStats').innerHTML = [
      {lbl:'Average AQI', val:data.avg, color:zoneFor(data.avg).color},
      {lbl:'Maximum',     val:data.max, color:zoneFor(data.max).color},
      {lbl:'Minimum',     val:data.min, color:zoneFor(data.min).color},
    ].map(it=>`<div class="hs-item"><div class="hs-label">${it.lbl}</div><div class="hs-val" style="color:${it.color}">${it.val}</div></div>`).join('');
    /* Chart */
    if (histChart) histChart.destroy();
    const ctx = $('histChart').getContext('2d');
    const ptColors = data.values.map(v => zoneFor(v).color);
    const grad = ctx.createLinearGradient(0,0,0,260); grad.addColorStop(0,'rgba(79,158,255,.22)'); grad.addColorStop(1,'rgba(79,158,255,.0)');
    histChart = new Chart(ctx, {
      type: range==='monthly'?'bar':'line',
      data:{ labels:data.dates, datasets:[{ label:'AQI', data:data.values, borderColor:'#4f9eff', backgroundColor:range==='monthly'?ptColors.map(c=>c+'bb'):grad, borderWidth:range==='monthly'?0:2.5, tension:0.35, fill:range!=='monthly', pointRadius:range==='7d'?5:2, pointHoverRadius:7, pointBackgroundColor:ptColors, pointBorderColor:'transparent', borderRadius:range==='monthly'?6:0 }] },
      options:{ responsive:true, maintainAspectRatio:false, plugins:{ legend:{display:false}, tooltip:{ backgroundColor:'rgba(10,14,26,.97)', borderColor:'rgba(255,255,255,.1)', borderWidth:1, titleColor:'#7a8aaa', bodyColor:'#e2e8f8', padding:11, callbacks:{ label:ctx=>` AQI: ${ctx.parsed.y} — ${zoneFor(ctx.parsed.y).label}` } } }, scales:{ x:{grid:{color:'rgba(255,255,255,.03)'},ticks:{color:'#7a8aaa',font:{size:11},maxTicksLimit:range==='monthly'?12:10},border:{color:'rgba(255,255,255,.04)'}}, y:{min:0,suggestedMax:500,grid:{color:'rgba(255,255,255,.04)'},ticks:{color:'#7a8aaa',font:{size:11}},border:{color:'rgba(255,255,255,.04)'}} }, interaction:{mode:'index',intersect:false} }
    });
  } catch(e) { console.error('History:', e); }
}

/* ═══════════════════════════════════════════════════
   HEALTH RECS
═══════════════════════════════════════════════════ */
async function renderHealth(aqi) {
  const zone = zoneFor(aqi);
  const chip = $('healthChip');
  chip.textContent = `AQI ${aqi} — ${zone.label}`;
  chip.style.borderColor = zone.color + '44';
  chip.style.color = zone.color;
  try {
    const data = await api(`/api/health_recs?aqi=${aqi}`);
    const grid = $('healthGrid');
    grid.innerHTML = '';
    data.recommendations.forEach((rec, i) => {
      const card = document.createElement('div');
      card.className = `health-card ${rec.level}`;
      card.style.animationDelay = `${i*0.07}s`;
      card.innerHTML = `<div class="hc-icon">${rec.icon}</div><div class="hc-title">${rec.title}</div><div class="hc-desc">${rec.desc}</div>`;
      grid.appendChild(card);
    });
  } catch(e) { console.error('Health:', e); }
}

/* ═══════════════════════════════════════════════════
   NAV
═══════════════════════════════════════════════════ */
const SECS = ['sec-live','sec-pollutants','sec-forecast','sec-history','sec-health'];
function scrollTo(id) {
  const el = $(id); if (el) el.scrollIntoView({behavior:'smooth',block:'start'});
  document.querySelectorAll('.snav').forEach(a => a.classList.remove('active'));
  const idx = SECS.indexOf(id);
  document.querySelectorAll('.snav')[idx]?.classList.add('active');
  if (window.innerWidth <= 700) $('sidebar').classList.remove('open');
}
function toggleSidebar() { $('sidebar').classList.toggle('open'); }
window.addEventListener('scroll', () => {
  let cur = SECS[0];
  SECS.forEach(id => { const el=$(id); if(el && window.scrollY >= el.offsetTop - 120) cur=id; });
  document.querySelectorAll('.snav').forEach((a,i) => a.classList.toggle('active', SECS[i]===cur));
}, {passive:true});

/* ─── Boot ─── */
document.addEventListener('DOMContentLoaded', init);
