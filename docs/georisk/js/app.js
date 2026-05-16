// app.js — Live Mars Barn digital twin + multi-planet simulation
// Mars data pulled in real-time from kody-w/mars-barn repo via raw.githubusercontent.com
// Other planets use pre-computed sim-data.json

const BACKGROUND = 'https://unpkg.com/three-globe/example/img/night-sky.png';

const TEXTURE_BASE = 'https://raw.githubusercontent.com/kody-w/mars-barn/main/assets/textures';

const PLANETS = {
    "mercury": { name: "MERCURY", texture: `${TEXTURE_BASE}/2k_mercury.jpg`, color: 0xaaaaaa, atmosColor: "#ffffff", atmosAlt: 0.05 },
    "venus": { name: "VENUS", texture: `${TEXTURE_BASE}/2k_venus_surface.jpg`, color: 0xffddaa, atmosColor: "#eac479", atmosAlt: 0.2 },
    "earth": { name: "EARTH", texture: "https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg", color: 0xffffff, atmosColor: "#38bdf8", atmosAlt: 0.15 },
    "moon": { name: "MOON", texture: `${TEXTURE_BASE}/2k_moon.jpg`, color: 0xffffff, atmosColor: "#c8c8c8", atmosAlt: 0.05 },
    "mars": { name: "MARS", texture: `${TEXTURE_BASE}/2k_mars.jpg`, color: 0xffffff, atmosColor: "#ef4444", atmosAlt: 0.15 },
    "jupiter": { name: "JUPITER", texture: `${TEXTURE_BASE}/2k_jupiter.jpg`, color: 0xffffff, atmosColor: "#d97706", atmosAlt: 0.25 },
    "saturn": { name: "SATURN", texture: `${TEXTURE_BASE}/2k_saturn.jpg`, color: 0xffffff, atmosColor: "#fde047", atmosAlt: 0.25 },
    "uranus": { name: "URANUS", texture: `${TEXTURE_BASE}/2k_uranus.jpg`, color: 0xffffff, atmosColor: "#06b6d4", atmosAlt: 0.2 },
    "neptune": { name: "NEPTUNE", texture: `${TEXTURE_BASE}/2k_neptune.jpg`, color: 0xffffff, atmosColor: "#2563eb", atmosAlt: 0.2 }
};

let currentMode = "mars";
let viewMode = "single";
const COMPARE_KEYS = ["earth", "moon", "mars"];
let globes = { single: null, earth: null, moon: null, mars: null };
let simData = null;
let healthHistory = {};
const MAX_HISTORY_STEPS = 50;

// ── Mars Climate Engine (NASA Mission Data) ─────────────────────────────
// Ported from mars-barn/src/mars_climate.py
// Sources: Viking 1&2 (1976-82), Curiosity/REMS (2012+), Perseverance/MEDA (2021+),
//          Mars Climate Database v6.1, MDAD (14,974 storms MY24-MY32)

const JEZERO = { lat: 18.38, lon: 77.58 };
const MC_TEMP = {
  0:[207,12,180,235],30:[210,11,185,240],60:[213,10,190,243],
  90:[208,11,184,238],120:[205,12,180,235],150:[210,13,182,245],
  180:[218,15,188,260],210:[225,18,190,272],240:[228,20,192,280],
  270:[222,17,189,272],300:[218,15,185,265],330:[212,13,183,250],
};
const MC_PRES = {
  0:[750,30],30:[730,25],60:[710,20],90:[700,20],120:[720,25],150:[750,30],
  180:[800,35],210:[860,40],240:[920,45],270:[960,40],300:[930,35],330:[850,30],
};
const MC_SOLAR = {
  0:[530,350,120],30:[510,340,115],60:[495,330,110],90:[490,325,105],
  120:[505,335,110],150:[530,350,120],180:[570,375,130],210:[620,410,140],
  240:[670,440,90],270:[715,470,80],300:[680,450,100],330:[610,400,135],
};
const MC_DUST = {
  0:[0.02,0.005,0,0.2,0.4],30:[0.02,0.005,0,0.2,0.4],60:[0.03,0.008,0,0.25,0.5],
  90:[0.03,0.008,0,0.25,0.5],120:[0.04,0.01,0,0.3,0.5],150:[0.05,0.015,0,0.3,0.6],
  180:[0.10,0.03,0.002,0.4,0.7],210:[0.15,0.05,0.005,0.5,0.8],240:[0.20,0.08,0.01,0.5,0.9],
  270:[0.25,0.10,0.015,0.6,0.95],300:[0.18,0.06,0.008,0.5,0.85],330:[0.08,0.02,0.002,0.3,0.6],
};
const MC_WIND = {
  0:[4,12],30:[3.5,10],60:[3,9],90:[3,8],120:[3.5,10],150:[4,12],
  180:[5.5,16],210:[7,22],240:[8.5,28],270:[9,35],300:[7.5,25],330:[5,15],
};
const MC_SEASONS = ['Early Spring','Spring','Late Spring','Early Summer','Mid Summer','Late Summer',
  'Autumn Equinox','Dust Season','Peak Dust','Perihelion','Late Winter','Winter Waning'];

function mcInterp(table, ls) {
  const bin = Math.floor((((ls%360)+360)%360)/30)*30;
  const next = (bin+30)%360;
  const f = (((ls%360)+360)%360 - bin)/30;
  return table[bin].map((v,i) => v + (table[next][i]-v)*f);
}

function marsDateNow() {
  const jd = Date.now()/86400000 + 2440587.5 + 69.184/86400;
  const dJ = jd - 2451545.0;
  const msd = (dJ-4.5)/1.0274912517 + 44796.0 - 0.00096;
  const M = (19.3871 + 0.52402075*msd) % 360;
  const Mr = M*Math.PI/180;
  const eoc = 10.691*Math.sin(Mr) + 0.623*Math.sin(2*Mr) + 0.050*Math.sin(3*Mr) + 0.005*Math.sin(4*Mr);
  let ls = (M+eoc+270.3863) % 360;
  if (ls<0) ls+=360;
  let lmst = ((24*msd)%24 + JEZERO.lon/15) % 24;
  if (lmst<0) lmst+=24;
  return { msd, ls, lmst, sol: Math.floor(msd) };
}

function getMarsWeather() {
  const md = marsDateNow();
  const t = mcInterp(MC_TEMP, md.ls);
  const p = mcInterp(MC_PRES, md.ls);
  const s = mcInterp(MC_SOLAR, md.ls);
  const d = mcInterp(MC_DUST, md.ls);
  const w = mcInterp(MC_WIND, md.ls);
  // Diurnal temp: peak ~14:00, min ~5:00
  const phase = (md.lmst-14)/24*2*Math.PI;
  const tempK = (t[2]+t[3])/2 + ((t[3]-t[2])/2)*Math.cos(phase);
  const tau = 0.3 + d[3]*1.5;
  const surfSolar = Math.round(s[1]*(1-tau*0.4));
  return {
    sol: md.sol, ls: Math.round(md.ls*10)/10, lmst: md.lmst,
    season: MC_SEASONS[Math.floor((((md.ls%360)+360)%360)/30)],
    tempC: Math.round(tempK-273.15), tempK: Math.round(tempK),
    pressurePa: Math.round(p[0]), windMs: Math.round(w[0]*10)/10,
    gustMs: Math.round(w[1]), dustTau: Math.round(tau*100)/100,
    uvIndex: Math.round((s[1]/470)*12*(1-tau*0.3)*10)/10,
    solarWm2: surfSolar, dustStormProb: Math.round(d[0]*100),
    timeStr: `${String(Math.floor(md.lmst)).padStart(2,'0')}:${String(Math.floor((md.lmst%1)*60)).padStart(2,'0')}`,
  };
}

let marsWeather = getMarsWeather();
setInterval(() => { marsWeather = getMarsWeather(); }, 30000);
// ── End Mars Climate Engine ─────────────────────────────────────────────

const MARS_BARN_RAW = 'https://raw.githubusercontent.com/kody-w/mars-barn/main';
const MARS_BARN_STATE_FILES = [
    'state/colony.json',
    'state/olympus_base.json',
    'state/the_hobbit_hole.json',
    'state/valles_marineris_outpost.json',
    'state/dead_on_arrival.json',
    'data/colonies.json',
];

// Convert Mars 0-360 longitude to globe -180 to 180
function marsLng(lng) { return lng > 180 ? lng - 360 : lng; }

// Fetch live Mars Barn simulation state and overlay onto the globe
async function fetchMarsBarnLive() {
    try {
        const results = await Promise.allSettled(
            MARS_BARN_STATE_FILES.map(f =>
                fetch(`${MARS_BARN_RAW}/${f}?t=${Date.now()}`).then(r => r.ok ? r.json() : null)
            )
        );

        const [colony, olympus, hobbit, valles, doa, sectors] = results.map(r =>
            r.status === 'fulfilled' ? r.value : null
        );

        if (!simData || !simData.mars) return;

        // Override Mars colonies with LIVE data from the repo
        const marsColonies = simData.mars.colonies;

        if (colony) {
            const h = colony.habitat || {};
            const crew = colony.crew || {};
            marsColonies.jezero = {
                name: colony.name || 'Mars Barn — Jezero Crater',
                lat: colony.location?.latitude || 18.38,
                lng: marsLng(colony.location?.longitude || 77.58),
                health: Math.round((crew.health || 0.5) * 100),
                live: true,
                sol: colony.sol || 0,
                crew_size: h.crew_size || 0,
                morale: Math.round((crew.morale || 0.5) * 100),
                water_l: Math.round(h.water_reserves_l || 0),
                food_kg: Math.round(h.food_reserves_kg || 0),
                energy_kwh: Math.round(h.stored_energy_kwh || 0),
                interior_temp_c: Math.round((h.interior_temp_k || 293) - 273.15),
            };
        }

        if (olympus) {
            marsColonies.olympus = {
                name: olympus.name || 'Olympus Base',
                lat: olympus.location?.latitude || 18.65,
                lng: marsLng(olympus.location?.longitude || -133.8),
                health: Math.round((olympus.crew?.health || 0.5) * 100),
                live: true,
                sol: olympus.sol || 0,
            };
        }

        if (valles) {
            marsColonies.valles = {
                name: valles.name || 'Valles Marineris Outpost',
                lat: valles.location?.latitude || -13.9,
                lng: marsLng(valles.location?.longitude || -59.2),
                health: Math.round((valles.crew?.health || 0.5) * 100),
                live: true,
                sol: valles.sol || 0,
            };
        }

        if (hobbit) {
            marsColonies.hobbit = {
                name: hobbit.name || 'The Hobbit Hole',
                lat: hobbit.location?.latitude || -4.5,
                lng: marsLng(hobbit.location?.longitude || 137.4),
                health: Math.round((hobbit.crew?.health || 0.5) * 100),
                live: true,
                sol: hobbit.sol || 0,
            };
        }

        if (doa) {
            marsColonies.doa = {
                name: doa.name || 'Dead on Arrival',
                lat: doa.location?.latitude || 80.0,
                lng: marsLng(doa.location?.longitude || 0.0),
                health: Math.round((doa.crew?.health || 0) * 100),
                live: true,
                sol: doa.sol || 0,
            };
        }

        // Sectors from data/colonies.json
        if (sectors && Array.isArray(sectors)) {
            sectors.forEach((s, i) => {
                const id = (s.id || `sector-${i}`).toLowerCase().replace(/[^a-z0-9]/g, '_');
                marsColonies[id] = {
                    name: s.id || `Sector ${i}`,
                    lat: -4.5 + (i * 2.5),  // Spread around Jezero
                    lng: marsLng(137.4 + (i * 3.0)),
                    health: s.status === 'DEAD' ? 0 : Math.min(100, Math.round(s.age_sols / 3)),
                    live: true,
                    sol: s.age_sols || 0,
                    status: s.status,
                    last_event: (s.last_event || '').slice(0, 60),
                };
            });
        }

        // Update Mars resources with live data + real weather
        if (colony) {
            const h = colony.habitat || {};
            const w = getMarsWeather();
            simData.mars.resources = {
                'Surface Temp': `${w.tempC}°C (${w.tempK}K)`,
                'Pressure': `${w.pressurePa} Pa`,
                'Wind': `${w.windMs} m/s (gusts ${w.gustMs})`,
                'Dust τ': w.dustTau,
                'Solar': `${w.solarWm2} W/m²`,
                'UV Index': w.uvIndex,
                'Season': `${w.season} (Ls ${w.ls}°)`,
                'Storm Risk': `${w.dustStormProb}%/sol`,
                'LMST': `${w.timeStr}`,
                'Sol': colony.sol || w.sol,
                'O₂ Reserves': `${Math.round((h.stored_energy_kwh || 0) / 10)} tons`,
                'H₂O Extract': `${Math.round((h.water_reserves_l || 0) / 1000 * 100) / 100} kL`,
                'Crew Morale': Math.round((colony.crew?.morale || 0) * 100) + '%',
            };
        }

        // Update health history for live colonies
        Object.keys(marsColonies).forEach(cid => {
            if (!healthHistory[cid]) healthHistory[cid] = [];
            healthHistory[cid].push(marsColonies[cid].health);
            if (healthHistory[cid].length > MAX_HISTORY_STEPS) healthHistory[cid].shift();
        });

        updateUI();
        // Force globe re-render with explicit new data array
        if (currentMode === 'mars' && globes.single) {
            const pts = Object.keys(marsColonies).map(k => ({ ...marsColonies[k], id: k }));
            globes.single.htmlElementsData(pts);
        }
        updateGlobeData();
        console.log(`[Mars Barn] Live data loaded: ${Object.keys(marsColonies).length} colonies, Sol ${colony?.sol || '?'}`);
    } catch (err) {
        console.warn('[Mars Barn] Live fetch failed, using cached data:', err);
    }
}

// ---------------------------------------------------------------------------
// Globe setup
// ---------------------------------------------------------------------------

function initGlobes() {
    globes.single = createBaseGlobe('globeVizSingle', currentMode);
    globes.earth = createBaseGlobe('globeVizEarth', 'earth');
    globes.moon = createBaseGlobe('globeVizMoon', 'moon');
    globes.mars = createBaseGlobe('globeVizMars', 'mars');
}

function createBaseGlobe(containerId, planetKey) {
    const config = PLANETS[planetKey];
    const g = Globe()
        (document.getElementById(containerId))
        .backgroundColor('rgba(0,0,0,0)')
        .showAtmosphere(true)
        .atmosphereColor(config.atmosColor)
        .atmosphereAltitude(config.atmosAlt)
        .globeImageUrl(config.texture);

    const isMainGlobe = containerId === 'globeVizSingle';
    g.htmlElementsData([])
        .htmlElement(d => {
            const isFailed = d.health < 60;
            const statusOverlay = isFailed ? `<div style="color: #ef4444; font-weight: bold; font-size: 14px;">SIM FAILED</div>` : '';
            const el = document.createElement('div');
            el.style.cursor = 'pointer';
            el.style.pointerEvents = 'auto';
            el.addEventListener('click', (e) => {
                e.stopPropagation();
                const resolvedPlanet = isMainGlobe ? currentMode : planetKey;
                openGroundView(d, resolvedPlanet);
            });
            el.innerHTML = `
                <div style="text-align: center; pointer-events: auto;">
                    <div style="
                        width: ${isFailed ? '20px' : '8px'}; 
                        height: ${isFailed ? '20px' : '8px'}; 
                        background: ${isFailed ? '#ef4444' : getColorForHealth(d.health)}; 
                        border-radius: 50%;
                        box-shadow: 0 0 ${isFailed ? '20px' : '5px'} ${isFailed ? '#ef4444' : getColorForHealth(d.health)};
                        border: 1px solid white;
                        margin: 0 auto;
                        animation: ${isFailed ? 'pulse_fast 0.5s infinite' : 'pulse 2s infinite'};
                    "></div>
                    <div style="
                        background: rgba(0,0,0,0.8);
                        color: white;
                        padding: 2px 4px;
                        border-radius: 4px;
                        font-family: monospace;
                        font-size: 9px;
                        margin-top: 4px;
                        border: 1px solid ${isFailed ? '#ef4444' : 'rgba(255,255,255,0.2)'};
                        white-space: nowrap;
                    ">
                        ${statusOverlay}
                        ${d.name}<br>HP: ${d.health}%
                        ${d.live ? `<div><a href="https://kody-w.github.io/mars-barn/ground.html?colony=${({jezero:'mars-barn',olympus:'olympus',hobbit:'hobbit',valles:'valles',doa:'doa'})[d.id]||'mars-barn'}" target="_blank" style="color:#f0a060;font-size:10px;text-decoration:none" onclick="event.stopPropagation()">🔭 Ground View</a></div>` : ''}
                    </div>
                </div>`;
            return el;
        });

    g.controls().autoRotate = true;
    g.controls().autoRotateSpeed = 0.5;
    g.pointOfView({ altitude: 2.2 });
    g.globeMaterial().color.setHex(config.color);
    return g;
}

// ---------------------------------------------------------------------------
// Planet menu & view toggles
// ---------------------------------------------------------------------------

function buildPlanetMenu() {
    const menu = document.getElementById('planet-menu');
    menu.innerHTML = '';
    Object.keys(PLANETS).forEach(key => {
        const btn = document.createElement('button');
        btn.innerText = PLANETS[key].name;
        btn.id = `btn-${key}`;
        if (key === currentMode) btn.classList.add('active');
        btn.addEventListener('click', () => { if (viewMode === "single") switchSingleMode(key); });
        menu.appendChild(btn);
    });
}

document.getElementById('btn-single-view').addEventListener('click', () => {
    viewMode = "single";
    document.getElementById('btn-single-view').classList.add('active');
    document.getElementById('btn-compare-view').classList.remove('active');
    document.getElementById('globeVizSingle').classList.remove('hidden');
    document.getElementById('compareVizContainer').classList.add('hidden');
    document.getElementById('planet-menu').style.opacity = '1';
    document.getElementById('planet-menu').style.pointerEvents = 'auto';
    window.dispatchEvent(new Event('resize'));
    updateUI();
    updateGlobeData();
});

document.getElementById('btn-compare-view').addEventListener('click', () => {
    viewMode = "compare";
    document.getElementById('btn-compare-view').classList.add('active');
    document.getElementById('btn-single-view').classList.remove('active');
    document.getElementById('globeVizSingle').classList.add('hidden');
    document.getElementById('compareVizContainer').classList.remove('hidden');
    document.getElementById('planet-menu').style.opacity = '0.5';
    document.getElementById('planet-menu').style.pointerEvents = 'none';
    window.dispatchEvent(new Event('resize'));
    updateUI();
    updateGlobeData();
});

function switchSingleMode(mode) {
    if (!PLANETS[mode]) return;
    currentMode = mode;
    document.querySelectorAll('.planet-toggle button').forEach(b => b.classList.remove('active'));
    document.getElementById(`btn-${mode}`).classList.add('active');
    const config = PLANETS[mode];
    globes.single.globeImageUrl(config.texture);
    globes.single.atmosphereColor(config.atmosColor);
    globes.single.atmosphereAltitude(config.atmosAlt);
    const mat = globes.single.globeMaterial();
    if (mat && mat.color) mat.color.setHex(config.color);
    document.getElementById('live-feed').innerHTML = '';
    updateUI();
    updateGlobeData();
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getColorForHealth(health) {
    if (health < 60) return '#ef4444';
    if (health < 80) return '#f59e0b';
    return '#10b981';
}

function calculateGPA(colonyId) {
    const history = healthHistory[colonyId];
    if (!history || history.length === 0) return "N/A";
    const avg = history.reduce((a, b) => a + b, 0) / history.length;
    if (avg >= 93) return "4.0 (A)";
    if (avg >= 90) return "3.7 (A-)";
    if (avg >= 87) return "3.3 (B+)";
    if (avg >= 83) return "3.0 (B)";
    if (avg >= 80) return "2.7 (B-)";
    if (avg >= 77) return "2.3 (C+)";
    if (avg >= 73) return "2.0 (C)";
    if (avg >= 70) return "1.7 (C-)";
    if (avg >= 67) return "1.3 (D+)";
    if (avg >= 65) return "1.0 (D)";
    return "0.0 (F)";
}

function getColoniesList(b_id) {
    if (!simData || !simData[b_id]) return [];
    return Object.keys(simData[b_id].colonies).map(key => {
        let col = simData[b_id].colonies[key];
        col.id = key;
        return col;
    });
}

function updateGlobeData() {
    if (!simData) return;
    if (viewMode === "single") {
        // Spread into new array to force three-globe re-render
        globes.single.htmlElementsData([...getColoniesList(currentMode)]);
    } else {
        COMPARE_KEYS.forEach(key => {
            if (globes[key]) globes[key].htmlElementsData([...getColoniesList(key)]);
        });
    }
}

// ---------------------------------------------------------------------------
// Event replay (replaces SSE)
// ---------------------------------------------------------------------------

let eventQueue = [];
let eventIndex = 0;
let replayTimer = null;

function startReplay(events) {
    eventQueue = events;
    eventIndex = 0;
    document.getElementById('status-text').textContent = 'SYSTEM ONLINE';
    replayNext();
}

function replayNext() {
    if (eventIndex >= eventQueue.length) {
        // Loop — restart with fresh randomized delays
        eventIndex = 0;
    }
    handleSimEvent(eventQueue[eventIndex]);
    eventIndex++;
    // Random delay between 100-500ms to simulate real-time
    const delay = 100 + Math.random() * 400;
    replayTimer = setTimeout(replayNext, delay);
}

function handleSimEvent(payload) {
    const b_id = payload.body_id;
    if (!b_id || !simData[b_id]) return;

    const isVisible = (viewMode === "single" && b_id === currentMode) ||
                      (viewMode === "compare" && COMPARE_KEYS.includes(b_id));

    if (payload.type === "health") {
        if (simData[b_id].colonies[payload.colony_id]) {
            simData[b_id].colonies[payload.colony_id].health = payload.health;
            if (!healthHistory[payload.colony_id]) healthHistory[payload.colony_id] = [];
            healthHistory[payload.colony_id].push(payload.health);
            if (healthHistory[payload.colony_id].length > MAX_HISTORY_STEPS) healthHistory[payload.colony_id].shift();
            if (isVisible) {
                updateUI();
                updateGlobeData();
                if (payload.health < 60) addNewsFeedItem(`CRITICAL FAILURE AT ${simData[b_id].colonies[payload.colony_id].name}. SIM TERMINATED.`);
            }
        }
    } else if (payload.type === "resource") {
        simData[b_id].resources[payload.res_name] = payload.value;
        if (isVisible) updateResourcesUI();
    } else if (payload.type === "news") {
        if (isVisible) addNewsFeedItem(payload.headline);
    } else if (payload.type === "bot_radar") {
        // Visual only — no globe ring in static mode
    }
}

// ---------------------------------------------------------------------------
// UI updates
// ---------------------------------------------------------------------------

function updateUI() {
    if (!simData) return;
    const colList = document.getElementById('colony-list');
    colList.innerHTML = '';
    const bodiesToDisplay = viewMode === "single" ? [currentMode] : COMPARE_KEYS;
    let allCols = [];
    bodiesToDisplay.forEach(b => {
        allCols = allCols.concat(getColoniesList(b).map(c => ({ ...c, planetContext: PLANETS[b].name, planetKey: b })));
    });

    allCols.sort((a, b) => a.health - b.health).forEach(colony => {
        const isFailed = colony.health < 60;
        const colorTextClass = isFailed ? 'status-red' : (colony.health > 80 ? 'status-green' : 'status-amber');
        const colorClass = isFailed ? 'bg-red' : (colony.health > 80 ? 'bg-green' : 'bg-amber');
        const card = document.createElement('div');
        card.className = `station-card ${isFailed ? 'failed-card' : ''}`;
        card.style.cursor = 'pointer';
        card.addEventListener('click', () => openGroundView(colony, colony.planetKey));
        const gpa = calculateGPA(colony.id);
        if (gpa !== "N/A" && localStorage) localStorage.setItem(`gpa_${colony.id}`, gpa.split(' ')[0]);
        card.innerHTML = `
            <div class="card-header" style="font-size: 0.9em;">
                <span>${colony.name} <span style="opacity: 0.5;">(${colony.planetContext})</span></span>
                <span class="${colorTextClass}">${colony.health}%</span>
            </div>
            <div style="font-size: 0.8em; color: var(--text-dim); margin-bottom: 6px;">
                History GPA: <span style="color: white">${gpa}</span>
                &nbsp;|&nbsp; <span style="color: var(--accent-blue); cursor: pointer;">⬡ GROUND VIEW</span>
            </div>
            <div class="progress-bar-bg">
                <div class="progress-bar-fill ${colorClass}" style="width: ${colony.health}%;"></div>
            </div>`;
        colList.appendChild(card);
    });
    updateResourcesUI(bodiesToDisplay);
    updateLocalGPA();
}

function updateResourcesUI(bodiesToDisplay) {
    if (!simData) return;
    if (!bodiesToDisplay) bodiesToDisplay = viewMode === "single" ? [currentMode] : COMPARE_KEYS;
    const resList = document.getElementById('resource-list');
    resList.innerHTML = '';
    bodiesToDisplay.forEach(b => {
        if (!simData[b]) return;
        Object.entries(simData[b].resources).forEach(([key, value]) => {
            const card = document.createElement('div');
            card.className = 'resource-card';
            card.style.padding = '8px';
            card.innerHTML = `
                <div class="card-header" style="color: #7dd3fc; font-weight: normal; font-size: 0.8em; margin: 0;">${key}
                <span style="opacity:0.3; float:right;">${PLANETS[b].name}</span></div>
                <div class="card-value" style="color: #e0f2fe; font-size: 1rem;">${typeof value === 'string' ? value : (Number(value) || 0).toFixed(1)}</div>`;
            resList.appendChild(card);
        });
    });
}

function updateLocalGPA() {
    let total = 0, count = 0;
    for (let i = 0; i < localStorage.length; i++) {
        let k = localStorage.key(i);
        if (k.startsWith('gpa_')) { total += parseFloat(localStorage.getItem(k) || 0); count++; }
    }
    document.getElementById('local-gpa-avg').innerText = count > 0 ? (total / count).toFixed(2) : "0.0";
}

function addNewsFeedItem(headline) {
    const feed = document.getElementById('live-feed');
    const item = document.createElement('div');
    let alertClass = '';
    const low = headline.toLowerCase();
    if (low.includes('anomaly') || low.includes('storm')) alertClass = 'alert-amber';
    if (low.includes('impact') || low.includes('critical')) alertClass = 'alert-red';
    item.className = `feed-item ${alertClass}`;
    item.innerHTML = `
        <div class="feed-time">[${new Date().toLocaleTimeString([], { hour12: false })}] SYSTEM MSG</div>
        <div>${headline}</div>`;
    feed.prepend(item);
    if (feed.children.length > 30) feed.removeChild(feed.lastChild);
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

window.addEventListener('DOMContentLoaded', () => {
    buildPlanetMenu();
    initGlobes();

    // Fetch pre-computed simulation data, then overlay live Mars Barn state
    fetch('sim-data.json')
        .then(r => r.json())
        .then(data => {
            simData = data.init;
            // Seed health history from initial state
            Object.keys(simData).forEach(b_id => {
                Object.keys(simData[b_id].colonies).forEach(c_id => {
                    healthHistory[c_id] = [simData[b_id].colonies[c_id].health];
                });
            });
            updateUI();
            updateGlobeData();
            startReplay(data.events);

            // Overlay LIVE Mars Barn data from the repo
            fetchMarsBarnLive();
            // Auto-refresh Mars Barn data every 60 seconds
            setInterval(fetchMarsBarnLive, 60000);
        })
        .catch(err => {
            document.getElementById('status-text').textContent = 'TELEMETRY OFFLINE';
            console.error('Failed to load sim-data.json:', err);
        });

    window.addEventListener('resize', () => {
        globes.single.width(window.innerWidth).height(window.innerHeight);
        if (viewMode === "compare") {
            const cw = document.querySelector('.compare-pane').clientWidth;
            const ch = document.querySelector('.compare-pane').clientHeight;
            COMPARE_KEYS.forEach(k => { if (globes[k]) globes[k].width(cw).height(ch); });
        }
    });

    document.getElementById('ground-close-btn').addEventListener('click', closeGroundView);
});

// ---------------------------------------------------------------------------
// Ground-level 3D Colony Viewer
// ---------------------------------------------------------------------------

const PLANET_GROUND_COLORS = {
    mercury: { ground: 0x8a8a8a, sky: 0x111111, fog: 0x222222 },
    venus:   { ground: 0xc4a040, sky: 0x443300, fog: 0x554400 },
    earth:   { ground: 0x3a7a3a, sky: 0x1a3a5a, fog: 0x2a4a6a },
    moon:    { ground: 0x999999, sky: 0x050505, fog: 0x111111 },
    mars:    { ground: 0xb44a2a, sky: 0x2a1008, fog: 0x3a1a0a },
    jupiter: { ground: 0xb87333, sky: 0x1a0f00, fog: 0x2a1a00 },
    saturn:  { ground: 0xc4a860, sky: 0x1a1500, fog: 0x2a2000 },
    uranus:  { ground: 0x6ab0c0, sky: 0x0a1a20, fog: 0x152a30 },
    neptune: { ground: 0x2a4a8a, sky: 0x050a1a, fog: 0x0a1530 },
};

let groundScene = null;
let groundCamera = null;
let groundRenderer = null;
let groundAnimId = null;
let groundColonyData = null;

function openGroundView(colony, planetKey) {
    // Mars Barn live colonies → open full 3D ground simulation
    if (colony.live && planetKey === 'mars') {
        const groundColonyMap = { jezero: 'mars-barn', olympus: 'olympus', hobbit: 'hobbit', valles: 'valles', doa: 'doa' };
        const groundParam = groundColonyMap[colony.id] || 'mars-barn';
        window.open(`https://kody-w.github.io/mars-barn/ground.html?colony=${groundParam}`, '_blank');
        return;
    }
    groundColonyData = { colony, planetKey };
    const modal = document.getElementById('ground-view-modal');
    modal.classList.remove('hidden');

    document.getElementById('ground-colony-name').textContent = colony.name;
    const pName = PLANETS[planetKey] ? PLANETS[planetKey].name : planetKey.toUpperCase();
    document.getElementById('ground-colony-stats').textContent =
        `${pName} // LAT ${(Number(colony.lat) || 0).toFixed(1)} LNG ${(Number(colony.lng) || 0).toFixed(1)} // HP ${colony.health}%`;

    updateGroundHUD(colony, planetKey);
    buildGroundScene(colony, planetKey);
}

function closeGroundView() {
    const modal = document.getElementById('ground-view-modal');
    modal.classList.add('hidden');
    if (groundAnimId) cancelAnimationFrame(groundAnimId);
    if (groundRenderer) {
        groundRenderer.dispose();
        const container = document.getElementById('ground-scene');
        container.innerHTML = '';
    }
    groundScene = null;
    groundCamera = null;
    groundRenderer = null;
}

function updateGroundHUD(colony, planetKey) {
    const resources = simData && simData[planetKey] ? simData[planetKey].resources : {};
    const entries = Object.entries(resources).slice(0, 4);
    const hud = document.getElementById('ground-hud-content');
    hud.innerHTML = `<div class="ground-hud-row">
        <div class="ground-hud-item">
            <div class="ground-hud-label">Health</div>
            <div class="ground-hud-value" style="color: ${getColorForHealth(colony.health)}">${colony.health}%</div>
        </div>
        <div class="ground-hud-item">
            <div class="ground-hud-label">GPA</div>
            <div class="ground-hud-value">${calculateGPA(colony.id)}</div>
        </div>
        ${entries.map(([k, v]) => `<div class="ground-hud-item">
            <div class="ground-hud-label">${k}</div>
            <div class="ground-hud-value">${typeof v === 'string' ? v : (Number(v) || 0).toFixed(1)}</div>
        </div>`).join('')}
    </div>`;
}

function buildGroundScene(colony, planetKey) {
    const container = document.getElementById('ground-scene');
    container.innerHTML = '';

    const THREE = window.THREE || Globe.__THREE__;
    if (!THREE) { console.error('Three.js not available'); return; }

    const colors = PLANET_GROUND_COLORS[planetKey] || PLANET_GROUND_COLORS.mars;
    const w = container.clientWidth;
    const h = container.clientHeight;

    // Scene
    groundScene = new THREE.Scene();
    groundScene.background = new THREE.Color(colors.sky);
    groundScene.fog = new THREE.FogExp2(colors.fog, 0.015);

    // Camera
    groundCamera = new THREE.PerspectiveCamera(60, w / h, 0.1, 1000);
    groundCamera.position.set(0, 8, 25);
    groundCamera.lookAt(0, 3, 0);

    // Renderer
    groundRenderer = new THREE.WebGLRenderer({ antialias: true });
    groundRenderer.setSize(w, h);
    groundRenderer.setPixelRatio(window.devicePixelRatio);
    groundRenderer.shadowMap.enabled = true;
    container.appendChild(groundRenderer.domElement);

    // Lights
    const ambient = new THREE.AmbientLight(0x404060, 0.6);
    groundScene.add(ambient);

    const sun = new THREE.DirectionalLight(0xffeedd, 1.2);
    sun.position.set(30, 40, 20);
    sun.castShadow = true;
    groundScene.add(sun);

    const point = new THREE.PointLight(colors.ground, 0.4, 100);
    point.position.set(0, 15, 0);
    groundScene.add(point);

    // Ground plane
    const groundGeo = new THREE.PlaneGeometry(200, 200, 64, 64);
    const verts = groundGeo.attributes.position;
    for (let i = 0; i < verts.count; i++) {
        verts.setZ(i, (Math.random() - 0.5) * 1.5);
    }
    groundGeo.computeVertexNormals();
    const groundMat = new THREE.MeshStandardMaterial({
        color: colors.ground,
        roughness: 0.9,
        metalness: 0.1,
        flatShading: true,
    });
    const ground = new THREE.Mesh(groundGeo, groundMat);
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    groundScene.add(ground);

    // Seed buildings from colony health
    const rng = seedRandom(colony.id);
    const buildingCount = 8 + Math.floor(colony.health / 10);
    const healthFactor = colony.health / 100;

    for (let i = 0; i < buildingCount; i++) {
        const bw = 1 + rng() * 2;
        const bh = 2 + rng() * 8 * healthFactor;
        const bd = 1 + rng() * 2;
        const geo = new THREE.BoxGeometry(bw, bh, bd);
        const hue = 0.55 + rng() * 0.15;
        const lightness = colony.health > 60 ? (0.3 + rng() * 0.2) : (0.1 + rng() * 0.1);
        const mat = new THREE.MeshStandardMaterial({
            color: new THREE.Color().setHSL(hue, 0.5, lightness),
            roughness: 0.7,
            metalness: 0.3,
        });
        const mesh = new THREE.Mesh(geo, mat);
        const angle = rng() * Math.PI * 2;
        const dist = 3 + rng() * 20;
        mesh.position.set(Math.cos(angle) * dist, bh / 2, Math.sin(angle) * dist);
        mesh.rotation.y = rng() * Math.PI;
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        groundScene.add(mesh);

        // Glowing windows
        if (colony.health > 40 && rng() > 0.3) {
            const windowColor = colony.health > 60 ? 0x00ccff : 0xff3333;
            const windowMat = new THREE.MeshBasicMaterial({ color: windowColor });
            const windowGeo = new THREE.PlaneGeometry(bw * 0.3, bh * 0.15);
            const win = new THREE.Mesh(windowGeo, windowMat);
            win.position.set(mesh.position.x, bh * 0.6, mesh.position.z + bd / 2 + 0.01);
            groundScene.add(win);
        }
    }

    // Dome (central habitat)
    const domeGeo = new THREE.SphereGeometry(4, 16, 12, 0, Math.PI * 2, 0, Math.PI / 2);
    const domeMat = new THREE.MeshStandardMaterial({
        color: 0x88bbdd,
        roughness: 0.2,
        metalness: 0.6,
        transparent: true,
        opacity: 0.4,
    });
    const dome = new THREE.Mesh(domeGeo, domeMat);
    dome.position.set(0, 0, 0);
    groundScene.add(dome);

    // Antenna tower
    const antennaGeo = new THREE.CylinderGeometry(0.1, 0.15, 12, 8);
    const antennaMat = new THREE.MeshStandardMaterial({ color: 0xaaaaaa, metalness: 0.8 });
    const antenna = new THREE.Mesh(antennaGeo, antennaMat);
    antenna.position.set(-8, 6, -5);
    antenna.castShadow = true;
    groundScene.add(antenna);

    // Blinking light on antenna
    const blinkGeo = new THREE.SphereGeometry(0.3, 8, 8);
    const blinkMat = new THREE.MeshBasicMaterial({ color: colony.health > 60 ? 0x00ff44 : 0xff0000 });
    const blink = new THREE.Mesh(blinkGeo, blinkMat);
    blink.position.set(-8, 12, -5);
    groundScene.add(blink);

    // Particle dust
    const particleCount = 200;
    const particleGeo = new THREE.BufferGeometry();
    const positions = new Float32Array(particleCount * 3);
    for (let i = 0; i < particleCount; i++) {
        positions[i * 3] = (Math.random() - 0.5) * 80;
        positions[i * 3 + 1] = Math.random() * 20;
        positions[i * 3 + 2] = (Math.random() - 0.5) * 80;
    }
    particleGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    const particleMat = new THREE.PointsMaterial({
        color: colors.ground,
        size: 0.15,
        transparent: true,
        opacity: 0.5,
    });
    const particles = new THREE.Points(particleGeo, particleMat);
    groundScene.add(particles);

    // Stars
    const starCount = 500;
    const starGeo = new THREE.BufferGeometry();
    const starPos = new Float32Array(starCount * 3);
    for (let i = 0; i < starCount; i++) {
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.random() * Math.PI * 0.4; // upper hemisphere only
        const r = 150 + Math.random() * 50;
        starPos[i * 3] = r * Math.sin(phi) * Math.cos(theta);
        starPos[i * 3 + 1] = r * Math.cos(phi);
        starPos[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta);
    }
    starGeo.setAttribute('position', new THREE.BufferAttribute(starPos, 3));
    const starMat = new THREE.PointsMaterial({ color: 0xffffff, size: 0.5 });
    groundScene.add(new THREE.Points(starGeo, starMat));

    // Animate
    let time = 0;
    function animate() {
        groundAnimId = requestAnimationFrame(animate);
        time += 0.005;

        // Slow camera orbit
        groundCamera.position.x = Math.sin(time * 0.3) * 25;
        groundCamera.position.z = Math.cos(time * 0.3) * 25;
        groundCamera.position.y = 8 + Math.sin(time * 0.5) * 2;
        groundCamera.lookAt(0, 3, 0);

        // Blink antenna light
        blink.visible = Math.sin(time * 8) > 0;

        // Drift particles
        const pos = particles.geometry.attributes.position;
        for (let i = 0; i < particleCount; i++) {
            pos.array[i * 3] += Math.sin(time + i) * 0.02;
            pos.array[i * 3 + 1] += 0.01;
            if (pos.array[i * 3 + 1] > 20) pos.array[i * 3 + 1] = 0;
        }
        pos.needsUpdate = true;

        groundRenderer.render(groundScene, groundCamera);
    }
    animate();

    // Handle resize
    const onResize = () => {
        if (!groundRenderer) return;
        const nw = container.clientWidth;
        const nh = container.clientHeight;
        groundCamera.aspect = nw / nh;
        groundCamera.updateProjectionMatrix();
        groundRenderer.setSize(nw, nh);
    };
    window.addEventListener('resize', onResize);
}

// Simple seeded random for deterministic colony layouts
function seedRandom(str) {
    let h = 0;
    for (let i = 0; i < str.length; i++) {
        h = ((h << 5) - h + str.charCodeAt(i)) | 0;
    }
    return function() {
        h = (h * 16807) % 2147483647;
        return (h & 0x7fffffff) / 0x7fffffff;
    };
}
