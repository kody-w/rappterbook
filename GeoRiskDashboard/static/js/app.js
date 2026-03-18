// App.js - Core Logic for Solar System Simulation

const BACKGROUND = 'https://unpkg.com/three-globe/example/img/night-sky.png';

const PLANETS = {
    "mercury": { name: "MERCURY", texture: "https://upload.wikimedia.org/wikipedia/commons/4/4a/Mercury_in_true_color.jpg", color: 0xaaaaaa, atmosColor: "rgba(255, 255, 255, 0.05)", atmosAlt: 0.05 },
    "venus": { name: "VENUS", texture: "https://upload.wikimedia.org/wikipedia/commons/e/e5/Venus-real_color.jpg", color: 0xffddaa, atmosColor: "rgba(234, 196, 121, 0.6)", atmosAlt: 0.2 },
    "earth": { name: "EARTH", texture: "https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg", color: 0xffffff, atmosColor: "rgba(56, 189, 248, 0.4)", atmosAlt: 0.15 },
    "moon": { name: "MOON", texture: "https://upload.wikimedia.org/wikipedia/commons/d/db/Moonmap_from_clementine_data.png", color: 0xffffff, atmosColor: "rgba(200, 200, 200, 0.1)", atmosAlt: 0.05 },
    "mars": { name: "MARS", texture: "https://upload.wikimedia.org/wikipedia/commons/0/02/OSIRIS_Mars_true_color.jpg", color: 0xffffff, atmosColor: "rgba(239, 68, 68, 0.4)", atmosAlt: 0.15 },
    "jupiter": { name: "JUPITER", texture: "https://upload.wikimedia.org/wikipedia/commons/e/e2/Jupiter.jpg", color: 0xffffff, atmosColor: "rgba(217, 119, 6, 0.4)", atmosAlt: 0.25 },
    "saturn": { name: "SATURN", texture: "https://upload.wikimedia.org/wikipedia/commons/c/c7/Saturn_during_Equinox.jpg", color: 0xffffff, atmosColor: "rgba(253, 224, 71, 0.3)", atmosAlt: 0.25 },
    "uranus": { name: "URANUS", texture: "https://upload.wikimedia.org/wikipedia/commons/3/3d/Uranus2.jpg", color: 0xffffff, atmosColor: "rgba(6, 182, 212, 0.4)", atmosAlt: 0.2 },
    "neptune": { name: "NEPTUNE", texture: "https://upload.wikimedia.org/wikipedia/commons/5/56/Neptune_Full.jpg", color: 0xffffff, atmosColor: "rgba(37, 99, 235, 0.4)", atmosAlt: 0.2 }
};

let currentMode = "mars"; // Default single view
let viewMode = "single"; // "single" or "compare"

// The Three globes for compare mode
const COMPARE_KEYS = ["earth", "moon", "mars"];
let globes = {
    single: null,
    earth: null,
    moon: null,
    mars: null
};

let simData = null; // The robust state object from the backend containing all planets
let healthHistory = {}; // Format: { colony_id: [hp1, hp2, hp3...] }
const MAX_HISTORY_STEPS = 50;

// Initializers
function initGlobes() {
    // 1. Init Single Globe
    globes.single = createBaseGlobe('globeVizSingle', currentMode);

    // 2. Init Compare Globes
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

    g.htmlElementsData([])
        .htmlElement(d => {
            const isFailed = d.health < 60;
            const statusOverlay = isFailed ? `<div style="color: #ef4444; font-weight: bold; font-size: 14px;">SIM FAILED</div>` : '';

            const el = document.createElement('div');
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
                    </div>
                </div>
             `;
            return el;
        });

    // Auto rotate
    g.controls().autoRotate = true;
    g.controls().autoRotateSpeed = 0.5;
    g.pointOfView({ altitude: 2.2 });
    g.globeMaterial().color.setHex(config.color);

    return g;
}

// Build the planetary menu for Single View
function buildPlanetMenu() {
    const menu = document.getElementById('planet-menu');
    menu.innerHTML = '';

    Object.keys(PLANETS).forEach(key => {
        const btn = document.createElement('button');
        btn.innerText = PLANETS[key].name;
        btn.id = `btn-${key}`;
        if (key === currentMode) btn.classList.add('active');

        btn.addEventListener('click', () => {
            if (viewMode === "single") switchSingleMode(key);
        });

        menu.appendChild(btn);
    });
}

// Toggle View Modes
document.getElementById('btn-single-view').addEventListener('click', () => {
    viewMode = "single";
    document.getElementById('btn-single-view').classList.add('active');
    document.getElementById('btn-compare-view').classList.remove('active');

    document.getElementById('globeVizSingle').classList.remove('hidden');
    document.getElementById('compareVizContainer').classList.add('hidden');

    document.getElementById('planet-menu').style.opacity = '1';
    document.getElementById('planet-menu').style.pointerEvents = 'auto';

    // Force resize to fix canvas layout
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

    // Force resize to fix canvases
    window.dispatchEvent(new Event('resize'));
    updateUI();
    updateGlobeData();
});

// Switch Single View planet
function switchSingleMode(mode) {
    if (!PLANETS[mode]) return;
    currentMode = mode;

    // Update Button Styles
    document.querySelectorAll('.planet-toggle button').forEach(b => b.classList.remove('active'));
    document.getElementById(`btn-${mode}`).classList.add('active');

    // Update Globe Visuals
    const config = PLANETS[mode];
    globes.single.globeImageUrl(config.texture);
    globes.single.atmosphereColor(config.atmosColor);
    globes.single.atmosphereAltitude(config.atmosAlt);
    globes.single.globeMaterial().color.setHex(config.color);

    // Clear feed
    document.getElementById('live-feed').innerHTML = '';

    updateUI();
    updateGlobeData();
}

// Utilities
function getColorForHealth(health) {
    if (health < 60) return '#ef4444';
    if (health < 80) return '#f59e0b';
    return '#10b981';
}

function calculateGPA(colonyId) {
    const history = healthHistory[colonyId];
    if (!history || history.length === 0) return "N/A";
    const avgHealth = history.reduce((a, b) => a + b, 0) / history.length;
    if (avgHealth >= 93) return "4.0 (A)";
    if (avgHealth >= 90) return "3.7 (A-)";
    if (avgHealth >= 87) return "3.3 (B+)";
    if (avgHealth >= 83) return "3.0 (B)";
    if (avgHealth >= 80) return "2.7 (B-)";
    if (avgHealth >= 77) return "2.3 (C+)";
    if (avgHealth >= 73) return "2.0 (C)";
    if (avgHealth >= 70) return "1.7 (C-)";
    if (avgHealth >= 67) return "1.3 (D+)";
    if (avgHealth >= 65) return "1.0 (D)";
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

// Update 3D Globes based on mode
function updateGlobeData() {
    if (!simData) return;

    if (viewMode === "single") {
        globes.single.htmlElementsData(getColoniesList(currentMode));
    } else {
        COMPARE_KEYS.forEach(key => {
            if (globes[key]) globes[key].htmlElementsData(getColoniesList(key));
        });
    }
}

// Setup Event Stream
function setupSSE() {
    const eventSource = new EventSource('/stream');
    eventSource.onmessage = function (event) {
        handleSimEvent(JSON.parse(event.data));
    };
}

// Realtime Signal Routing
function handleSimEvent(payload) {
    if (payload.type === "init") {
        simData = payload.data;
        Object.keys(simData).forEach(b_id => {
            Object.keys(simData[b_id].colonies).forEach(c_id => {
                healthHistory[c_id] = [simData[b_id].colonies[c_id].health];
            });
        });
        updateUI();
        updateGlobeData();
        return;
    }

    const b_id = payload.body_id;
    if (!b_id || !simData[b_id]) return;

    // Determine if this planet's data should be visible right now
    const isVisible = (viewMode === "single" && b_id === currentMode) || (viewMode === "compare" && COMPARE_KEYS.includes(b_id));

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
        if (isVisible) {
            // Dispatch visual ring to the correct globe renderer
            flashBotRadar(payload.lat, payload.lng, payload.bot_id, document.getElementById(`globeViz${viewMode === 'single' ? 'Single' : b_id.charAt(0).toUpperCase() + b_id.slice(1)}`));
        }
    }
}

// Sidebar Sync
function updateUI() {
    if (!simData) return;

    const colList = document.getElementById('colony-list');
    colList.innerHTML = '';

    // In Compare mode, we list all colonies from the 3 displayed planets
    const bodiesToDisplay = viewMode === "single" ? [currentMode] : COMPARE_KEYS;

    let allCols = [];
    bodiesToDisplay.forEach(b => {
        allCols = allCols.concat(getColoniesList(b).map(c => ({ ...c, planetContext: PLANETS[b].name })));
    });

    allCols.sort((a, b) => a.health - b.health)
        .forEach(colony => {
            const isFailed = colony.health < 60;
            const colorClass = isFailed ? 'bg-red' : (colony.health > 80 ? 'bg-green' : 'bg-amber');
            const colorTextClass = isFailed ? 'status-red' : (colony.health > 80 ? 'status-green' : 'status-amber');

            const card = document.createElement('div');
            card.className = `station-card ${isFailed ? 'failed-card' : ''}`;
            const gpa = calculateGPA(colony.id);

            // Keep local avg fed
            if (gpa !== "N/A" && localStorage) localStorage.setItem(`gpa_${colony.id}`, gpa.split(' ')[0]);

            card.innerHTML = `
                    <div class="card-header" style="font-size: 0.9em;">
                        <span>${colony.name} <span style="opacity: 0.5;">(${colony.planetContext})</span></span>
                        <span class="${colorTextClass}">${colony.health}%</span>
                    </div>
                    <div style="font-size: 0.8em; color: var(--text-dim); margin-bottom: 6px;">
                        History GPA: <span style="color: white">${gpa}</span>
                    </div>
                    <div class="progress-bar-bg">
                        <div class="progress-bar-fill ${colorClass}" style="width: ${colony.health}%;"></div>
                    </div>
                `;
            colList.appendChild(card);
        });

    updateResourcesUI(bodiesToDisplay);
    updateLocalGPA();
}

function updateResourcesUI(bodiesToDisplay) {
    if (!simData) return;
    const resList = document.getElementById('resource-list');
    resList.innerHTML = '';

    bodiesToDisplay.forEach(b => {
        if (!simData[b]) return;
        const resources = simData[b].resources;
        Object.entries(resources).forEach(([key, value]) => {
            const card = document.createElement('div');
            card.className = 'resource-card';
            card.style.padding = '8px';
            card.innerHTML = `
                <div class="card-header" style="color: #7dd3fc; font-weight: normal; font-size: 0.8em; margin: 0;">${key} 
                <span style="opacity:0.3; float:right;">${PLANETS[b].name}</span></div>
                <div class="card-value" style="color: #e0f2fe; font-size: 1rem;">${value.toFixed(1)}</div>
            `;
            resList.appendChild(card);
        });
    });
}

function updateLocalGPA() {
    // Aggregates all tracked GPA floats for the local fork ranking
    let total = 0; let count = 0;
    for (let i = 0; i < localStorage.length; i++) {
        let k = localStorage.key(i);
        if (k.startsWith('gpa_')) {
            total += parseFloat(localStorage.getItem(k) || 0);
            count++;
        }
    }
    let avg = count > 0 ? (total / count).toFixed(2) : "0.0";
    document.getElementById('local-gpa-avg').innerText = avg;
}

function addNewsFeedItem(headline) {
    const feed = document.getElementById('live-feed');
    const item = document.createElement('div');

    let alertClass = '';
    const headlineLow = headline.toLowerCase();

    if (headlineLow.includes('anomaly') || headlineLow.includes('storm')) alertClass = 'alert-amber';
    if (headlineLow.includes('impact') || headlineLow.includes('critical')) alertClass = 'alert-red';

    item.className = `feed-item ${alertClass}`;
    item.innerHTML = `
        <div class="feed-time">[${new Date().toLocaleTimeString([], { hour12: false })}] SYSTEM MSG</div>
        <div>${headline}</div>
    `;

    feed.prepend(item);
    if (feed.children.length > 30) feed.removeChild(feed.lastChild);
}

function flashBotRadar(lat, lng, bot_id, containerEl) {
    // Basic stub, multi-globe targeting logic
}

window.addEventListener('DOMContentLoaded', () => {
    buildPlanetMenu();
    initGlobes();
    setupSSE();

    window.addEventListener('resize', () => {
        globes.single.width(window.innerWidth).height(window.innerHeight);
        if (viewMode === "compare") {
            const cw = document.querySelector('.compare-pane').clientWidth;
            const ch = document.querySelector('.compare-pane').clientHeight;
            COMPARE_KEYS.forEach(k => {
                if (globes[k]) globes[k].width(cw).height(ch);
            });
        }
    });
});
