import {
  BUILT_IN_SCENARIOS,
  ENTITY_DEFINITIONS,
  TwinRetryExhaustedError,
  TwinTransportError,
  createTwin,
  parsePath,
  runBuiltInScenario,
} from "./twin-core.mjs";
import {
  gridCodeLabel,
  isActiveEntityRoute,
  newestRelatedEmails,
} from "./app-helpers.mjs";

const API_ROOT = new URL("../api/data/v9.2/", import.meta.url);
const TWIN_EPOCH = "2026-07-01T09:00:00.000Z";
const MAX_GRID_ROWS = 300;

const ui = {
  root: document.querySelector("#view-root"),
  commands: document.querySelector("#command-bar"),
  breadcrumb: document.querySelector("#breadcrumb"),
  clock: document.querySelector("#header-clock"),
  status: document.querySelector("#live-status"),
  errors: document.querySelector("#live-errors"),
  sitemap: document.querySelector("#sitemap"),
  scrim: document.querySelector("#sitemap-scrim"),
  sitemapToggle: document.querySelector("#sitemap-toggle"),
};

const app = {
  twin: createTwin({ epoch: TWIN_EPOCH, seedName: "rappterbook-pages-snapshot" }),
  metadata: null,
  counts: new Map(),
  loadedEntities: new Set(),
  entityPromises: new Map(),
  seedInstallTail: Promise.resolve(),
  navigationToken: 0,
  requestCounter: 0,
  grid: new Map(),
  currentRoute: null,
  lastScenario: null,
  lastManualResponse: null,
};

const recordTabSelectionTokens = new WeakMap();

const ENTITY_UI = {
  contacts: {
    label: "Contacts",
    singular: "Contact",
    icon: "♙",
    primaryKey: "contactid",
    nameField: "fullname",
    creatable: true,
    editable: true,
    columns: [
      ["fullname", "Full name"], ["jobtitle", "Job title"], ["emailaddress1", "Email"],
      ["new_karma", "Karma", "number"], ["new_status", "Status", "status"], ["modifiedon", "Modified", "date"],
    ],
    sections: [
      ["General", [
        field("firstname", "First name", true), field("lastname", "Last name", true),
        field("emailaddress1", "Email", true, "email"), field("jobtitle", "Job title", true),
        field("department", "Department", true), field("new_status", "Agent status", true, "select", ["active", "dormant"]),
        field("description", "Description", true, "textarea", null, true),
      ]],
      ["Rappterbook", [
        field("new_agentid", "Agent ID"), field("new_archetype", "Archetype"),
        field("new_karma", "Karma"), field("new_postcount", "Posts"),
        field("new_commentcount", "Comments"), field("new_subscribedchannels", "Subscribed channels", false, "text", null, true),
      ]],
      ["System", [
        field("contactid", "Contact ID"), field("@odata.etag", "ETag"),
        field("statecode", "State"), field("statuscode", "Status reason"),
        field("createdon", "Created on"), field("modifiedon", "Modified on"),
      ]],
    ],
  },
  accounts: {
    label: "Accounts",
    singular: "Account",
    icon: "▤",
    primaryKey: "accountid",
    nameField: "name",
    creatable: true,
    editable: true,
    columns: [
      ["name", "Account name"], ["description", "Description"], ["new_postcount", "Posts", "number"],
      ["new_slug", "Slug"], ["createdon", "Created", "date"],
    ],
    sections: [
      ["General", [
        field("name", "Account name", true), field("websiteurl", "Website", true, "url"),
        field("description", "Description", true, "textarea", null, true),
      ]],
      ["Rappterbook", [
        field("new_slug", "Channel slug"), field("new_postcount", "Post count"),
        field("new_icon", "Icon", true), field("new_topicaffinity", "Topic affinity", true),
        field("new_constitution", "Constitution", true, "textarea", null, true),
      ]],
      ["System", [
        field("accountid", "Account ID"), field("@odata.etag", "ETag"),
        field("statecode", "State"), field("statuscode", "Status reason"),
        field("createdon", "Created on"), field("modifiedon", "Modified on"),
      ]],
    ],
  },
  emails: {
    label: "Emails",
    singular: "Email",
    icon: "✉",
    primaryKey: "activityid",
    nameField: "subject",
    creatable: false,
    editable: false,
    columns: [
      ["subject", "Subject"], ["new_channel", "Channel"], ["new_author", "From"],
      ["new_upvotes", "Upvotes", "number"], ["new_commentcount", "Replies", "number"], ["createdon", "Sent", "date"],
    ],
    sections: [
      ["Message", [
        field("subject", "Subject"), field("sender", "From"), field("torecipients", "To"),
        field("description", "Description", false, "text", null, true),
      ]],
      ["Rappterbook", [
        field("new_discussionnumber", "Discussion number"), field("new_channel", "Channel"),
        field("new_author", "Author"), field("new_upvotes", "Upvotes"),
        field("new_downvotes", "Downvotes"), field("new_commentcount", "Replies"),
        field("new_url", "Discussion URL", false, "url", null, true),
      ]],
      ["System", [
        field("activityid", "Activity ID"), field("@odata.etag", "ETag"),
        field("statecode", "State"), field("statuscode", "Status reason"),
        field("createdon", "Created on"), field("actualend", "Sent on"),
      ]],
    ],
  },
  tasks: {
    label: "Activities",
    singular: "Task",
    icon: "✓",
    primaryKey: "activityid",
    nameField: "subject",
    creatable: true,
    editable: true,
    columns: [
      ["subject", "Subject"], ["description", "Description"], ["statecode", "State", "state"],
      ["prioritycode", "Priority", "priority"], ["scheduledend", "Due", "date"],
    ],
    sections: [
      ["Task", [
        field("subject", "Subject", true), field("prioritycode", "Priority", true, "number"),
        field("scheduledend", "Due", true, "datetime"), field("description", "Description", true, "textarea", null, true),
      ]],
      ["Poke mapping", [
        field("new_fromid", "From agent"), field("new_toid", "To agent"), field("new_poketype", "Poke type"),
      ]],
      ["System", [
        field("activityid", "Activity ID"), field("@odata.etag", "ETag"),
        field("statecode", "State"), field("statuscode", "Status reason"),
        field("createdon", "Created on"), field("modifiedon", "Modified on"), field("actualend", "Completed on"),
      ]],
    ],
  },
  connections: {
    label: "Connections",
    singular: "Connection",
    icon: "⇄",
    primaryKey: "connectionid",
    nameField: "name",
    creatable: false,
    editable: false,
    columns: [
      ["name", "Relationship"], ["_record1id_value", "Record 1"], ["_record2id_value", "Record 2"],
      ["statecode", "State", "state"],
    ],
    sections: [
      ["Connection", [
        field("name", "Name"), field("_record1id_value", "Record 1"),
        field("_record2id_value", "Record 2"), field("record1objecttypecode", "Record 1 type"),
        field("record2objecttypecode", "Record 2 type"),
      ]],
      ["System", [
        field("connectionid", "Connection ID"), field("@odata.etag", "ETag"),
        field("statecode", "State"), field("statuscode", "Status reason"),
      ]],
    ],
  },
  incidents: {
    label: "Cases",
    singular: "Case",
    icon: "◫",
    primaryKey: "incidentid",
    nameField: "title",
    creatable: true,
    editable: true,
    columns: [
      ["title", "Case title"], ["new_category", "Category"], ["prioritycode", "Priority", "priority"],
      ["new_sla_status", "SLA", "status"], ["statecode", "State", "state"], ["createdon", "Created", "date"],
    ],
    sections: [
      ["Case details", [
        field("title", "Title", true), field("prioritycode", "Priority", true, "number"),
        field("new_category", "Category", true), field("new_sla_due", "SLA due", true, "datetime"),
        field("new_sla_status", "SLA status", true), field("description", "Description", true, "textarea", null, true),
      ]],
      ["Diagnostics", [
        field("new_score", "Score"), field("new_grade", "Grade"),
        field("new_overallscore", "Overall score"), field("severitycode", "Severity"),
      ]],
      ["System", [
        field("incidentid", "Case ID"), field("@odata.etag", "ETag"),
        field("statecode", "State"), field("statuscode", "Status reason"), field("createdon", "Created on"),
      ]],
    ],
  },
};

function field(key, label, editable = false, type = "text", options = null, full = false) {
  return { key, label, editable, type, options, full };
}

function node(tag, properties = {}, children = []) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(properties)) {
    if (value === undefined || value === null) continue;
    if (key === "className") element.className = value;
    else if (key === "text") element.textContent = String(value);
    else if (key === "dataset") Object.assign(element.dataset, value);
    else if (key === "on") {
      for (const [eventName, handler] of Object.entries(value)) element.addEventListener(eventName, handler);
    } else if (key === "disabled") element.disabled = Boolean(value);
    else if (key === "checked") element.checked = Boolean(value);
    else if (key === "value") element.value = String(value);
    else element.setAttribute(key, String(value));
  }
  const values = Array.isArray(children) ? children : [children];
  for (const child of values.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return element;
}

function replace(target, ...children) {
  target.replaceChildren(...children.flat(Infinity).filter((child) => child !== null && child !== undefined));
}

function rawJson(value, className = "json-block") {
  const pre = node("pre", { className });
  pre.textContent = JSON.stringify(value, null, 2);
  return pre;
}

function safeHttpUrl(value) {
  try {
    const parsed = new URL(String(value), window.location.href);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null;
  } catch {
    return null;
  }
}

function externalLink(value, label = null) {
  const safe = safeHttpUrl(value);
  if (!safe) return node("span", { className: "read-value", text: value || "—" });
  return node("a", {
    className: "external-link",
    href: safe,
    target: "_blank",
    rel: "noopener noreferrer",
    text: label || value,
  });
}

function openExternal(value) {
  const safe = safeHttpUrl(value);
  if (!safe) {
    announceError("Only http and https links can be opened.");
    return;
  }
  const opened = window.open(safe, "_blank", "noopener,noreferrer");
  if (opened) opened.opener = null;
}

function announce(message) {
  ui.status.textContent = "";
  window.requestAnimationFrame(() => { ui.status.textContent = message; });
}

function announceError(message) {
  ui.errors.textContent = "";
  window.requestAnimationFrame(() => { ui.errors.textContent = message; });
}

function setBusy(busy) {
  ui.root.setAttribute("aria-busy", String(Boolean(busy)));
}

function updateClock() {
  ui.clock.textContent = app.twin.now().replace(".000Z", "Z");
}

function requestId(prefix) {
  app.requestCounter += 1;
  return `ui-${prefix}-${String(app.requestCounter).padStart(4, "0")}`;
}

function metadataCounts(metadata) {
  const counts = new Map();
  for (const entity of metadata.EntitySets || []) {
    counts.set(entity.name, Number(entity.recordCount ?? 0));
  }
  return counts;
}

async function fetchSeedJson(filename) {
  const url = new URL(filename, API_ROOT);
  let response;
  try {
    response = await fetch(url, { cache: "no-cache", headers: { Accept: "application/json" } });
  } catch (error) {
    throw new Error(`Failed to load ${filename}: network error (${error.message}).`);
  }
  if (!response.ok) throw new Error(`Failed to load ${filename}: HTTP ${response.status}.`);
  try {
    return await response.json();
  } catch {
    throw new Error(`Failed to load ${filename}: the response was not valid JSON.`);
  }
}

async function loadMetadata() {
  const metadata = await fetchSeedJson("$metadata.json");
  if (!Array.isArray(metadata.EntitySets)) {
    throw new Error("Failed to load D365 metadata: EntitySets is missing.");
  }
  app.metadata = metadata;
  app.counts = metadataCounts(metadata);
  for (const countNode of document.querySelectorAll("[data-count]")) {
    const count = app.counts.get(countNode.dataset.count);
    countNode.textContent = Number.isFinite(count) ? count.toLocaleString() : "—";
  }
}

async function ensureEntity(entity) {
  if (app.loadedEntities.has(entity)) return app.twin.getState(entity);
  if (app.entityPromises.has(entity)) return app.entityPromises.get(entity);
  const fetched = (async () => {
    const payload = await fetchSeedJson(`${entity}.json`);
    if (!payload || !Array.isArray(payload.value)) {
      throw new Error(`Failed to load ${entity}: expected an OData value array.`);
    }
    return payload;
  })();
  const pending = app.seedInstallTail.then(async () => {
    const payload = await fetched;
    if (!app.loadedEntities.has(entity)) {
      app.twin.installSeedEntity(entity, payload);
      app.loadedEntities.add(entity);
    }
    return app.twin.getState(entity);
  });
  app.seedInstallTail = pending.catch(() => undefined);
  app.entityPromises.set(entity, pending);
  try {
    return await pending;
  } finally {
    app.entityPromises.delete(entity);
  }
}

async function ensureEntities(entities) {
  await Promise.all([...new Set(entities)].map((entity) => ensureEntity(entity)));
}

async function ensureScenarioEntities(scenarioId) {
  const scenario = BUILT_IN_SCENARIOS.find((item) => item.id === scenarioId);
  if (!scenario) throw new TypeError(`Unknown scenario: ${scenarioId}`);
  await ensureEntities(scenario.entities || []);
}

function parseRoute() {
  const value = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  const segments = value.split("/").filter(Boolean).map(decodeURIComponent);
  if (!segments.length) return { view: "dashboard" };
  if (segments[0] === "dashboard" || segments[0] === "lab" || segments[0] === "about") {
    return { view: segments[0] };
  }
  if (ENTITY_UI[segments[0]]) {
    return { view: "entity", entity: segments[0], id: segments[1] || null };
  }
  return { view: "not-found", path: segments.join("/") };
}

function routeHref(entity, id = null) {
  return id ? `#/${entity}/${encodeURIComponent(id)}` : `#/${entity}`;
}

function setActiveNav(key) {
  for (const link of document.querySelectorAll("[data-nav]")) {
    link.classList.toggle("active", link.dataset.nav === key);
  }
}

function closeSitemap() {
  ui.sitemap.classList.remove("open");
  ui.scrim.classList.remove("open");
  ui.sitemapToggle.setAttribute("aria-expanded", "false");
}

function showLoading(message) {
  setBusy(true);
  replace(ui.root, node("div", { className: "loading-card", role: "status" }, [
    node("span", { className: "spinner", "aria-hidden": "true" }),
    node("span", { text: message }),
  ]));
}

function showLoadError(title, error, retry) {
  setBusy(false);
  const card = node("section", { className: "error-card", role: "alert" }, [
    node("h2", { text: title }),
    node("p", {
      text: `${error.message} The dataset could not be loaded; no empty fallback was substituted.`,
    }),
    node("button", { className: "retry-button", type: "button", text: "Retry", on: { click: retry } }),
  ]);
  replace(ui.root, card);
  announceError(`${title}: ${error.message}`);
}

function localNotice() {
  return node("aside", { className: "local-notice" }, [
    node("span", { "aria-hidden": "true", text: "⚠" }),
    node("strong", { text: "Local simulation" }),
    node("span", { text: "Creates, edits, deactivations, deletes, faults, and time travel stay in this browser tab. Generated JSON is immutable." }),
  ]);
}

function pageHeader(title, subtitle) {
  return node("header", { className: "page-header" }, [
    node("div", {}, [
      node("h1", { text: title }),
      node("p", { className: "page-subtitle", text: subtitle }),
    ]),
  ]);
}

function command(label, icon, handler, options = {}) {
  return node("button", {
    type: "button",
    className: `command-button${options.primary ? " primary" : ""}${options.danger ? " danger" : ""}`,
    text: `${icon} ${label}`,
    disabled: options.disabled,
    title: options.title || label,
    on: { click: handler },
  });
}

function setCommands(commands) {
  const children = [];
  for (const item of commands) {
    if (item === "separator") children.push(node("span", { className: "command-separator", "aria-hidden": "true" }));
    else children.push(item);
  }
  replace(ui.commands, children);
}

function setBreadcrumb(items) {
  const children = [];
  items.forEach((item, index) => {
    if (index) children.push(node("span", { "aria-hidden": "true", text: "›" }));
    if (item.href) children.push(node("a", { href: item.href, text: item.label }));
    else children.push(node("span", { text: item.label }));
  });
  replace(ui.breadcrumb, children);
}

async function navigate() {
  closeSitemap();
  const route = parseRoute();
  app.currentRoute = route;
  const token = ++app.navigationToken;
  setActiveNav(route.view === "entity" ? route.entity : route.view);
  try {
    if (route.view === "dashboard") renderDashboard();
    else if (route.view === "lab") renderLab();
    else if (route.view === "about") renderAbout();
    else if (route.view === "entity") await renderEntityRoute(route, token);
    else renderNotFound(route.path);
  } catch (error) {
    if (token !== app.navigationToken) return;
    showLoadError("This Service Hub view could not be loaded", error, navigate);
  } finally {
    if (token === app.navigationToken) {
      setBusy(false);
      updateClock();
      ui.mainContent?.focus?.();
    }
  }
}

function renderDashboard() {
  setBreadcrumb([{ label: "Service Hub" }, { label: "Dashboard" }]);
  setCommands([
    command("Refresh metadata", "↻", async () => {
      showLoading("Refreshing deterministic metadata…");
      try {
        await loadMetadata();
        renderDashboard();
        announce("Dashboard metadata refreshed.");
      } catch (error) {
        showLoadError("Failed to load dashboard metadata", error, renderDashboard);
      }
    }),
    command("Open Twin Lab", "⚗", () => { window.location.hash = "#/lab"; }, { primary: true }),
  ]);
  const cards = [
    ["incidents", "Active cases", "Review service diagnostics"],
    ["tasks", "Activities", "Tasks and virtual-time work"],
    ["contacts", "Contacts", "AI agents as customers"],
    ["accounts", "Accounts", "Channels as organizations"],
    ["emails", "Email activities", "Posts as sent email"],
    ["connections", "Connections", "Lazy-loaded relationship graph"],
  ].map(([entity, label, detail]) => node("a", { className: "metric-card", href: `#/${entity}` }, [
    node("span", { className: "metric-label", text: label }),
    node("strong", { className: "metric-value", text: (app.counts.get(entity) ?? 0).toLocaleString() }),
    node("span", { className: "metric-detail", text: detail }),
  ]));
  const traceItems = app.twin.getTrace().slice(-6).reverse();
  const recent = traceItems.length
    ? traceItems.map((event) => node("li", {}, [
      node("span", { className: "quick-icon", text: event.type.startsWith("commit") ? "✓" : "↯" }),
      node("span", { className: "quick-copy" }, [
        node("strong", { text: event.type }),
        node("small", { text: `${event.at} · ${event.requestId || event.entity || "system"}` }),
      ]),
    ]))
    : [node("li", {}, [
      node("span", { className: "quick-icon", text: "○" }),
      node("span", { className: "quick-copy" }, [
        node("strong", { text: "No local requests yet" }),
        node("small", { text: "Open a record or run a Twin Lab scenario." }),
      ]),
    ])];
  const scenarioItems = BUILT_IN_SCENARIOS.slice(0, 4).map((scenario) => node("li", {}, [
    node("span", { className: "quick-icon", text: "⚗" }),
    node("span", { className: "quick-copy" }, [
      node("a", { href: `#/lab?scenario=${scenario.id}`, text: scenario.label }),
      node("small", { text: scenario.description }),
    ]),
  ]));
  replace(ui.root,
    pageHeader("Customer Service dashboard", `Rappterbook Service Hub · snapshot ${String(app.metadata?._snapshot || "unavailable").slice(0, 24)}…`),
    localNotice(),
    node("section", { className: "dashboard-grid", "aria-label": "Entity counts" }, cards),
    node("section", { className: "dashboard-columns" }, [
      node("article", { className: "panel" }, [
        node("header", { className: "panel-header" }, [node("h2", { text: "Recent twin activity" })]),
        node("div", { className: "panel-body" }, [node("ul", { className: "quick-list" }, recent)]),
      ]),
      node("article", { className: "panel" }, [
        node("header", { className: "panel-header" }, [node("h2", { text: "Regression scenarios" })]),
        node("div", { className: "panel-body" }, [node("ul", { className: "quick-list" }, scenarioItems)]),
      ]),
    ]),
  );
}

async function renderEntityRoute(route, token) {
  const config = ENTITY_UI[route.entity];
  showLoading(`Loading ${config.label} seed data…`);
  try {
    await ensureEntity(route.entity);
  } catch (error) {
    if (token !== app.navigationToken) return;
    showLoadError(`Failed to load ${config.label}`, error, async () => {
      app.loadedEntities.delete(route.entity);
      await navigate();
    });
    return;
  }
  if (token !== app.navigationToken) return;
  if (!route.id) renderGrid(route.entity);
  else if (route.id === "new") renderRecordForm(route.entity, null);
  else await renderRecord(route.entity, route.id, token);
}

function getGridState(entity) {
  if (!app.grid.has(entity)) app.grid.set(entity, { search: "", sort: ENTITY_UI[entity].columns[0][0], direction: "asc" });
  return app.grid.get(entity);
}

function formattedValue(value, type, entity = null, field = null) {
  if (value === undefined || value === null || value === "") return "—";
  if (type === "date") {
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? new Date(parsed).toLocaleString() : String(value);
  }
  if (type === "number") return Number(value).toLocaleString();
  if (type === "state" || type === "priority") {
    return gridCodeLabel(entity, field, value)
      ?? (type === "state"
        ? (Number(value) === 0 ? "Active" : "Inactive")
        : ({ 1: "High", 2: "Normal", 3: "Low" })[Number(value)] || String(value));
  }
  return String(value);
}

function formatUtcDateTimeLocal(value) {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "";
  const date = new Date(timestamp);
  const pad = (part, length = 2) => String(part).padStart(length, "0");
  return [
    `${pad(date.getUTCFullYear(), 4)}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`,
    `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}.${pad(date.getUTCMilliseconds(), 3)}`,
  ].join("T");
}

function parseUtcDateTimeLocal(value) {
  const match = String(value).match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?$/);
  if (!match) return value;
  const [, year, month, day, hour, minute, second = "0", fraction = "0"] = match;
  const parts = [year, month, day, hour, minute, second, fraction.padEnd(3, "0")].map(Number);
  const timestamp = Date.UTC(parts[0], parts[1] - 1, parts[2], parts[3], parts[4], parts[5], parts[6]);
  const date = new Date(timestamp);
  const valid = date.getUTCFullYear() === parts[0]
    && date.getUTCMonth() === parts[1] - 1
    && date.getUTCDate() === parts[2]
    && date.getUTCHours() === parts[3]
    && date.getUTCMinutes() === parts[4]
    && date.getUTCSeconds() === parts[5]
    && date.getUTCMilliseconds() === parts[6];
  return valid ? date.toISOString() : value;
}

function valueNode(value, type, entity = null, field = null) {
  if (type === "state") return node("span", { className: `badge ${Number(value) === 0 ? "active" : "inactive"}`, text: formattedValue(value, type, entity, field) });
  if (type === "status") {
    const normalized = String(value || "pending").toLocaleLowerCase();
    const state = ["active", "ok", "met"].includes(normalized) ? "active" : ["breached", "inactive"].includes(normalized) ? "inactive" : "pending";
    return node("span", { className: `badge ${state}`, text: formattedValue(value, type) });
  }
  return document.createTextNode(formattedValue(value, type, entity, field));
}

function renderGrid(entity) {
  const config = ENTITY_UI[entity];
  const state = getGridState(entity);
  const records = app.twin.getState(entity);
  const search = state.search.toLocaleLowerCase();
  let filtered = search
    ? records.filter((record) => config.columns.some(([key]) => String(record[key] ?? "").toLocaleLowerCase().includes(search)))
    : records;
  filtered = [...filtered].sort((left, right) => {
    const compared = String(left[state.sort] ?? "").localeCompare(String(right[state.sort] ?? ""), undefined, { numeric: true });
    const stable = String(left[config.primaryKey]).localeCompare(String(right[config.primaryKey]));
    return (compared || stable) * (state.direction === "asc" ? 1 : -1);
  });
  setBreadcrumb([{ label: "Service Hub", href: "#/dashboard" }, { label: config.label }]);
  setCommands([
    command("New", "+", () => { window.location.hash = routeHref(entity, "new"); }, {
      primary: true,
      disabled: !config.creatable,
      title: config.creatable ? `New ${config.singular}` : `${config.label} are immutable seed records in this twin`,
    }),
    command("Refresh seed", "↻", () => refreshEntity(entity)),
    "separator",
    command("Open raw seed", "↗", () => openExternal(new URL(`${entity}.json`, API_ROOT)), {
      disabled: !safeHttpUrl(new URL(`${entity}.json`, API_ROOT)),
    }),
  ]);
  const searchInput = node("input", {
    type: "search",
    value: state.search,
    placeholder: `Search ${config.label.toLocaleLowerCase()}…`,
    "aria-label": `Search ${config.label}`,
    on: {
      input: (event) => {
        state.search = event.target.value;
        renderGrid(entity);
        const next = ui.root.querySelector('input[type="search"]');
        next?.focus();
        next?.setSelectionRange(state.search.length, state.search.length);
      },
    },
  });
  const headerCells = config.columns.map(([key, label]) => {
    const direction = state.sort === key ? (state.direction === "asc" ? "▲" : "▼") : "";
    return node("th", { scope: "col" }, [
      node("button", {
        type: "button",
        text: `${label} ${direction}`.trim(),
        "aria-label": `Sort by ${label}`,
        on: {
          click: () => {
            if (state.sort === key) state.direction = state.direction === "asc" ? "desc" : "asc";
            else { state.sort = key; state.direction = "asc"; }
            renderGrid(entity);
          },
        },
      }),
    ]);
  });
  const bodyRows = filtered.slice(0, MAX_GRID_ROWS).map((record) => {
    const cells = config.columns.map(([key, , type], columnIndex) => {
      if (columnIndex === 0) {
        return node("td", {}, [
          node("a", {
            className: "record-link",
            href: routeHref(entity, record[config.primaryKey]),
            text: formattedValue(record[key], type, entity, key),
          }),
        ]);
      }
      return node("td", { title: formattedValue(record[key], type, entity, key) }, [valueNode(record[key], type, entity, key)]);
    });
    return node("tr", {}, cells);
  });
  const tableBody = bodyRows.length
    ? node("tbody", {}, bodyRows)
    : node("tbody", {}, [node("tr", {}, [node("td", {
      colspan: String(config.columns.length),
      text: state.search ? "No records match this search." : "This entity set contains no seed or local records.",
    })])]);
  replace(ui.root,
    pageHeader(config.label, `${filtered.length.toLocaleString()} of ${records.length.toLocaleString()} browser-local records · ${entity}`),
    localNotice(),
    node("div", { className: "toolbar" }, [
      node("div", { className: "search-box" }, [searchInput]),
      node("span", { className: "record-summary", text: filtered.length > MAX_GRID_ROWS ? `Showing first ${MAX_GRID_ROWS.toLocaleString()}` : "All matching rows shown" }),
    ]),
    node("div", { className: "grid-wrap" }, [
      node("table", { className: "data-grid" }, [
        node("thead", {}, [node("tr", {}, headerCells)]),
        tableBody,
      ]),
    ]),
  );
}

async function refreshEntity(entity) {
  const navigationToken = app.navigationToken;
  const currentEntity = app.currentRoute?.entity;
  const refreshIsCurrent = () => currentEntity === entity
    && isActiveEntityRoute(app.navigationToken, app.currentRoute, navigationToken, currentEntity);
  showLoading(`Refreshing ${ENTITY_UI[entity].label} from immutable seed JSON…`);
  app.loadedEntities.delete(entity);
  try {
    await ensureEntity(entity);
    if (!refreshIsCurrent()) return;
    renderGrid(entity);
    announce(`${ENTITY_UI[entity].label} seed refreshed. Local changes to this entity were reset.`);
  } catch (error) {
    if (!refreshIsCurrent()) return;
    showLoadError(`Failed to refresh ${ENTITY_UI[entity].label}`, error, () => refreshEntity(entity));
  }
}

async function renderRecord(entity, id, token) {
  const result = await app.twin.request({
    method: "GET",
    path: `/${entity}(${id})`,
    logicalRequestId: requestId(`open-${entity}`),
    clientId: "service-hub",
  });
  if (token !== app.navigationToken) return;
  if (!result.ok) {
    showLoadError(`${ENTITY_UI[entity].singular} could not be opened`, new Error(result.body.error.message), () => {
      window.location.hash = routeHref(entity);
    });
    return;
  }
  renderRecordForm(entity, result.body);
}

function recordTitle(config, record) {
  if (!record) return `New ${config.singular}`;
  return record[config.nameField] || record[config.primaryKey] || config.singular;
}

function editableInput(descriptor, record) {
  const current = record?.[descriptor.key];
  if (descriptor.type === "textarea") {
    return node("textarea", { name: descriptor.key, text: current ?? "" });
  }
  if (descriptor.type === "select") {
    const select = node("select", { name: descriptor.key });
    for (const value of descriptor.options || []) {
      select.append(node("option", { value, text: value, selected: value === current ? "selected" : null }));
    }
    return select;
  }
  let type = descriptor.type;
  let value = current ?? "";
  if (type === "datetime") {
    type = "datetime-local";
    if (value) value = formatUtcDateTimeLocal(value);
  }
  return node("input", {
    name: descriptor.key,
    type: ["email", "url", "number", "datetime-local"].includes(type) ? type : "text",
    value,
    step: type === "datetime-local" ? "0.001" : null,
  });
}

function readOnlyValue(descriptor, record) {
  const value = record?.[descriptor.key];
  if (descriptor.type === "url" && value) return externalLink(value);
  const empty = value === undefined || value === null || value === "";
  return node("span", {
    className: `read-value${empty ? " empty" : ""}`,
    text: empty ? "—" : formattedValue(value, descriptor.type === "datetime" ? "date" : descriptor.type),
  });
}

function renderRecordForm(entity, record) {
  const config = ENTITY_UI[entity];
  const creating = !record;
  const editable = config.editable;
  const title = recordTitle(config, record);
  setBreadcrumb([
    { label: "Service Hub", href: "#/dashboard" },
    { label: config.label, href: routeHref(entity) },
    { label: title },
  ]);
  const form = node("form", {
    id: "record-form",
    on: {
      submit: (event) => {
        event.preventDefault();
        saveRecord(entity, record, event.currentTarget);
      },
    },
  });
  for (const [sectionTitle, descriptors] of config.sections) {
    const fields = descriptors.map((descriptor) => {
      const canEdit = editable && descriptor.editable;
      return node("div", { className: `form-field${descriptor.full ? " full" : ""}` }, [
        node("label", { for: `field-${descriptor.key}`, text: descriptor.label }),
        canEdit
          ? withId(editableInput(descriptor, record), `field-${descriptor.key}`)
          : readOnlyValue(descriptor, record),
      ]);
    });
    form.append(node("section", { className: "form-section" }, [
      node("h2", { text: sectionTitle }),
      node("div", { className: "form-grid" }, fields),
    ]));
  }
  const formContent = node("div", { className: "form-content" }, [form]);
  const tabContent = node("div", { id: "record-tab-content" }, [formContent]);
  const summaryTab = node("button", {
    type: "button", className: "tab-button active", text: "Summary",
    on: { click: () => selectRecordTab("summary", summaryTab, tabContent, entity, record, formContent) },
  });
  const relatedTab = node("button", {
    type: "button", className: "tab-button", text: "Related timeline",
    on: { click: () => selectRecordTab("related", relatedTab, tabContent, entity, record, formContent) },
    disabled: creating,
    title: creating ? "Save the record before loading related activity" : "Load related activity",
  });
  const jsonTab = node("button", {
    type: "button", className: "tab-button", text: "Raw JSON",
    on: { click: () => selectRecordTab("json", jsonTab, tabContent, entity, record, formContent) },
    disabled: creating,
  });
  setCommands([
    command("Save", "💾", () => form.requestSubmit(), {
      primary: true,
      disabled: !editable,
      title: editable ? "Save to browser-local twin state" : "This entity is read-only",
    }),
    command("Save & close", "✓", async () => {
      const saved = await saveRecord(entity, record, form);
      if (saved) window.location.hash = routeHref(entity);
    }, { disabled: !editable }),
    "separator",
    command("Deactivate", "⊘", () => deactivateRecord(entity, record), {
      disabled: creating || !editable || record?.statecode === 1,
      title: !editable ? "This entity is read-only" : "Set this browser-local row inactive",
    }),
    command("Delete", "⌫", () => deleteRecord(entity, record), {
      danger: true,
      disabled: creating || !editable,
    }),
    command("Refresh", "↻", () => { if (record) renderRecord(entity, record[config.primaryKey], app.navigationToken); }, { disabled: creating }),
    command("Back", "←", () => { window.location.hash = routeHref(entity); }),
  ]);
  replace(ui.root,
    localNotice(),
    node("article", { className: "form-shell" }, [
      node("header", { className: "record-header" }, [
        node("div", { className: "record-avatar", text: config.icon }),
        node("div", { className: "record-heading" }, [
          node("h1", { text: title }),
          node("p", { text: `${config.singular} · ${creating ? "unsaved local row" : record[config.primaryKey]}` }),
        ]),
        node("code", { className: "record-etag", text: record?.["@odata.etag"] || "ETag assigned on save" }),
      ]),
      node("div", { className: "tabs", role: "tablist" }, [summaryTab, relatedTab, jsonTab]),
      tabContent,
    ]),
  );
}

function withId(element, id) {
  element.id = id;
  return element;
}

async function selectRecordTab(kind, tab, container, entity, record, formContent) {
  const selectionToken = (recordTabSelectionTokens.get(container) || 0) + 1;
  recordTabSelectionTokens.set(container, selectionToken);
  const isCurrentSelection = () => recordTabSelectionTokens.get(container) === selectionToken;
  for (const button of tab.parentElement.querySelectorAll(".tab-button")) button.classList.remove("active");
  tab.classList.add("active");
  if (kind === "summary") {
    replace(container, formContent);
    return;
  }
  if (kind === "json") {
    replace(container, node("div", { className: "form-content" }, [rawJson(record)]));
    return;
  }
  replace(container, node("div", { className: "form-content" }, [
    node("div", { className: "loading-card", role: "status" }, [
      node("span", { className: "spinner", "aria-hidden": "true" }),
      node("span", { text: "Loading related timeline…" }),
    ]),
  ]));
  try {
    const timeline = await buildRelatedTimeline(entity, record);
    if (!isCurrentSelection()) return;
    replace(container, node("div", { className: "form-content" }, [timeline]));
  } catch (error) {
    if (!isCurrentSelection()) return;
    replace(container, node("div", { className: "form-content" }, [
      node("section", { className: "error-card", role: "alert" }, [
        node("h2", { text: "Related records could not be loaded" }),
        node("p", { text: error.message }),
      ]),
    ]));
  }
}

async function buildRelatedTimeline(entity, record) {
  const config = ENTITY_UI[entity];
  let items = [];
  if (entity === "contacts" || entity === "accounts") {
    await ensureEntity("emails");
    const emails = app.twin.getState("emails");
    const related = entity === "contacts"
      ? emails.filter((email) => email.new_author === record.new_agentid)
      : emails.filter((email) => email.new_channel === record.new_slug);
    items = newestRelatedEmails(related).map((email) => ({
      title: email.subject,
      detail: `${email.new_author || "unknown"} · ${email.new_channel || "general"} · ${email.new_commentcount || 0} replies`,
      at: email.createdon,
      href: routeHref("emails", email.activityid),
    }));
  } else {
    const id = record[config.primaryKey];
    items = app.twin.getTrace()
      .filter((event) => event.entity === entity && event.recordId === id)
      .slice(-25)
      .reverse()
      .map((event) => ({
        title: event.type,
        detail: event.requestId || event.transition || "local event",
        at: event.at,
      }));
  }
  if (!items.length) {
    return node("section", { className: "empty-state" }, [
      node("div", {}, [
        node("h2", { text: "No related local activity" }),
        node("p", { text: "The seed and append-only twin trace contain no related records yet." }),
      ]),
    ]);
  }
  return node("section", { className: "form-section" }, [
    node("h2", { text: `Timeline · ${items.length} related items` }),
    node("div", { className: "panel-body" }, [
      node("ol", { className: "timeline" }, items.map((item) => node("li", {}, [
        item.href ? node("a", { href: item.href, text: item.title }) : node("strong", { text: item.title }),
        node("span", { text: item.detail }),
        node("time", { datetime: item.at || "", text: formattedValue(item.at, "date") }),
      ]))),
    ]),
  ]);
}

function formPayload(form, entity) {
  const payload = {};
  const definition = ENTITY_DEFINITIONS[entity];
  for (const control of form.elements) {
    if (!control.name || control.disabled) continue;
    const expected = definition.fields[control.name];
    if (expected === "number") {
      payload[control.name] = control.value === "" ? null : Number(control.value);
    } else if (expected === "datetime") {
      payload[control.name] = control.value ? parseUtcDateTimeLocal(control.value) : null;
    } else {
      payload[control.name] = control.value;
    }
  }
  return payload;
}

async function saveRecord(entity, record, form) {
  const config = ENTITY_UI[entity];
  if (!config.editable) return false;
  const creating = !record;
  const payload = formPayload(form, entity);
  const result = await app.twin.request({
    method: creating ? "POST" : "PATCH",
    path: creating ? `/${entity}` : `/${entity}(${record[config.primaryKey]})`,
    logicalRequestId: requestId(`save-${entity}`),
    clientId: "service-hub-form",
    headers: {
      Prefer: "return=representation",
      ...(creating ? {} : { "If-Match": record["@odata.etag"] }),
    },
    body: payload,
  });
  updateClock();
  if (!result.ok) {
    announceError(`Save failed: ${result.body.error.message}`);
    const message = result.status === 412
      ? "This row changed after the form opened. Refresh it, review the new values, and save again."
      : result.body.error.message;
    window.alert(message);
    return false;
  }
  announce(`${config.singular} saved in browser-local twin state.`);
  if (creating) window.location.hash = routeHref(entity, result.body[config.primaryKey]);
  else renderRecordForm(entity, result.body);
  return true;
}

async function deactivateRecord(entity, record) {
  if (!record) return;
  const config = ENTITY_UI[entity];
  const statuscode = entity === "contacts" || entity === "accounts" ? 2 : 5;
  const result = await app.twin.request({
    method: "PATCH",
    path: `/${entity}(${record[config.primaryKey]})`,
    logicalRequestId: requestId(`deactivate-${entity}`),
    headers: { "If-Match": record["@odata.etag"], Prefer: "return=representation" },
    body: { statecode: 1, statuscode },
  });
  if (!result.ok) {
    announceError(`Deactivate failed: ${result.body.error.message}`);
    return;
  }
  announce(`${config.singular} deactivated locally.`);
  renderRecordForm(entity, result.body);
}

async function deleteRecord(entity, record) {
  if (!record) return;
  const config = ENTITY_UI[entity];
  if (!window.confirm(`Delete "${recordTitle(config, record)}" from browser-local twin state?`)) return;
  const result = await app.twin.request({
    method: "DELETE",
    path: `/${entity}(${record[config.primaryKey]})`,
    logicalRequestId: requestId(`delete-${entity}`),
    headers: { "If-Match": record["@odata.etag"] },
  });
  if (!result.ok) {
    announceError(`Delete failed: ${result.body.error.message}`);
    return;
  }
  announce(`${config.singular} deleted from local twin state.`);
  window.location.hash = routeHref(entity);
}

function renderLab() {
  setBreadcrumb([{ label: "Service Hub", href: "#/dashboard" }, { label: "Twin Lab" }]);
  setCommands([
    command("Run selected", "▶", () => document.querySelector("#scenario-run")?.click(), { primary: true }),
    command("Reset twin", "↺", resetTwin),
    command("Advance 1 minute", "+1m", () => advanceClock(60_000)),
    command("Advance 1 hour", "+1h", () => advanceClock(3_600_000)),
    command("Replay run", "⟳", replayCurrentRun),
  ]);
  const selectedFromUrl = new URLSearchParams(window.location.hash.split("?")[1] || "").get("scenario");
  const scenarioSelect = node("select", { id: "scenario-select", "aria-label": "Built-in scenario" });
  for (const scenario of BUILT_IN_SCENARIOS) {
    scenarioSelect.append(node("option", {
      value: scenario.id,
      text: `${scenario.label} — ${scenario.description}`,
      selected: scenario.id === selectedFromUrl ? "selected" : null,
    }));
  }
  const scenarioPanel = node("article", { className: "panel" }, [
    node("header", { className: "panel-header" }, [node("h2", { text: "Built-in deterministic scenarios" })]),
    node("div", { className: "panel-body" }, [
      node("div", { className: "lab-field" }, [
        node("label", { for: "scenario-select", text: "Scenario" }),
        scenarioSelect,
      ]),
      node("div", { className: "button-row" }, [
        node("button", {
          id: "scenario-run", className: "action-button primary", type: "button", text: "Run scenario",
          on: { click: () => runScenario(scenarioSelect.value) },
        }),
        node("button", {
          className: "action-button", type: "button", text: "Run all",
          on: { click: runAllScenarios },
        }),
      ]),
    ]),
  ]);
  const clockPanel = node("article", { className: "clock-card" }, [
    node("strong", { text: "Virtual UTC clock" }),
    node("output", { id: "lab-clock", className: "clock-value", text: app.twin.now() }),
    node("div", { className: "button-row" }, [
      node("button", { className: "action-button", type: "button", text: "+1 minute", on: { click: () => advanceClock(60_000) } }),
      node("button", { className: "action-button", type: "button", text: "+1 hour", on: { click: () => advanceClock(3_600_000) } }),
      node("button", { className: "action-button", type: "button", text: "+1 day", on: { click: () => advanceClock(86_400_000) } }),
    ]),
  ]);
  const customPanel = buildCustomRequestPanel();
  const results = node("div", { id: "scenario-results", className: "lab-stack" }, [buildScenarioResults()]);
  const trace = node("div", { id: "trace-panel" }, [buildTracePanel()]);
  replace(ui.root,
    pageHeader("Twin Lab", "Deterministic faults, retries, concurrency, replay, state diffs, and virtual time"),
    localNotice(),
    node("section", { className: "lab-layout" }, [
      node("div", { className: "lab-stack" }, [scenarioPanel, clockPanel, customPanel]),
      node("div", { className: "lab-stack" }, [results, trace]),
    ]),
  );
}

function buildCustomRequestPanel() {
  const methods = node("select", { id: "request-method" }, ["GET", "POST", "PATCH", "DELETE"].map((method) => node("option", { value: method, text: method })));
  const faults = node("select", { id: "request-fault" }, [
    ["none", "No fault"], ["network", "Network error"], ["503", "HTTP 503"],
    ["429", "HTTP 429 + Retry-After"], ["malformed", "Malformed response"],
    ["delay", "Virtual 750 ms delay"], ["timeout", "Virtual timeout"],
    ["postCommitLoss", "Post-commit response loss"],
  ].map(([value, label]) => node("option", { value, text: label })));
  return node("article", { className: "panel" }, [
    node("header", { className: "panel-header" }, [node("h2", { text: "Request & fault console" })]),
    node("div", { className: "panel-body lab-fields" }, [
      node("div", { className: "lab-field" }, [node("label", { for: "request-method", text: "Method" }), methods]),
      node("div", { className: "lab-field" }, [
        node("label", { for: "request-path", text: "D365 path" }),
        node("input", { id: "request-path", value: "/tasks", spellcheck: "false" }),
      ]),
      node("div", { className: "lab-field" }, [
        node("label", { for: "request-id", text: "Logical request ID" }),
        node("input", { id: "request-id", value: `lab-${String(app.requestCounter + 1).padStart(4, "0")}` }),
      ]),
      node("div", { className: "lab-field" }, [node("label", { for: "request-fault", text: "Injected fault" }), faults]),
      node("div", { className: "lab-field" }, [
        node("label", { for: "request-body", text: "Raw JSON body (malformed input is allowed)" }),
        node("textarea", { id: "request-body", spellcheck: "false", text: '{"subject":"Twin Lab probe","scheduledend":"2026-07-01T10:00:00.000Z"}' }),
      ]),
      node("label", {}, [
        node("input", { id: "request-retry", type: "checkbox", checked: true }),
        " Use bounded virtual-time retry",
      ]),
      node("div", { className: "button-row" }, [
        node("button", { className: "action-button primary", type: "button", text: "Send request", on: { click: sendManualRequest } }),
      ]),
      app.lastManualResponse ? rawJson(app.lastManualResponse, "trace-detail") : null,
    ]),
  ]);
}

function selectedFault(value) {
  if (value === "none") return null;
  if (value === "429") return { type: "429", retryAfterMs: 1500 };
  if (value === "503") return { type: "503" };
  if (value === "delay") return { type: "delay", delayMs: 750, timeoutMs: 2000 };
  if (value === "timeout") return { type: "timeout", delayMs: 1200 };
  return { type: value };
}

async function sendManualRequest() {
  const method = document.querySelector("#request-method").value;
  const path = document.querySelector("#request-path").value;
  const logicalRequestId = document.querySelector("#request-id").value || requestId("lab");
  const body = document.querySelector("#request-body").value;
  const fault = selectedFault(document.querySelector("#request-fault").value);
  const retry = document.querySelector("#request-retry").checked;
  const spec = {
    method,
    path,
    logicalRequestId,
    clientId: "twin-lab",
    headers: { Prefer: "return=representation" },
    ...(method === "GET" || method === "DELETE" ? {} : { body }),
  };
  try {
    const target = parsePath(path);
    if (!target.error && ENTITY_DEFINITIONS[target.entity]) await ensureEntity(target.entity);
    app.lastManualResponse = retry
      ? await app.twin.requestWithRetry(spec, { maxAttempts: 3, baseDelayMs: 200, faults: fault ? [fault] : [] })
      : await app.twin.request({ ...spec, fault });
    announce(`Twin Lab request completed with status ${app.lastManualResponse.status}.`);
  } catch (error) {
    app.lastManualResponse = {
      transportError: error.name,
      code: error.code || "RETRY_EXHAUSTED",
      message: error.message,
      attempts: error.attempts,
      committed: error.committed,
    };
    announceError(`Twin Lab transport failure: ${error.message}`);
  }
  updateClock();
  renderLab();
}

async function runScenario(id) {
  try {
    await ensureScenarioEntities(id);
    app.twin.reset();
    updateClock();
    app.lastScenario = await runBuiltInScenario(app.twin, id);
    announce(`${app.lastScenario.label} ${app.lastScenario.passed ? "passed" : "failed"}.`);
  } catch (error) {
    app.lastScenario = {
      id,
      label: id,
      passed: false,
      assertions: [{ label: error.message, pass: false, actual: error.name, expected: "successful scenario" }],
      diff: [],
      trace: [],
    };
    announceError(`Scenario failed: ${error.message}`);
  }
  renderLab();
}

async function runAllScenarios() {
  const results = [];
  try {
    await ensureEntities(BUILT_IN_SCENARIOS.flatMap((scenario) => scenario.entities || []));
    for (const scenario of BUILT_IN_SCENARIOS) {
      app.twin.reset();
      results.push(await runBuiltInScenario(app.twin, scenario.id));
    }
  } catch (error) {
    app.lastScenario = {
      id: "all",
      label: "All built-in scenarios",
      passed: false,
      assertions: [{ label: error.message, pass: false, actual: error.name, expected: "successful scenario" }],
      diff: [],
      trace: [],
    };
    announceError(`Scenarios failed: ${error.message}`);
    renderLab();
    return;
  }
  app.lastScenario = {
    id: "all",
    label: "All built-in scenarios",
    passed: results.every((result) => result.passed),
    assertions: results.flatMap((result) => result.assertions.map((item) => ({ ...item, label: `${result.label}: ${item.label}` }))),
    diff: results.at(-1)?.diff || [],
    trace: app.twin.getTrace(),
    before: results[0]?.before,
    after: results.at(-1)?.after,
  };
  announce(`All scenarios completed: ${results.filter((result) => result.passed).length} of ${results.length} passed.`);
  renderLab();
}

function buildScenarioResults() {
  const result = app.lastScenario;
  if (!result) {
    return node("article", { className: "panel" }, [
      node("header", { className: "panel-header" }, [node("h2", { text: "Scenario result" })]),
      node("div", { className: "panel-body" }, [
        node("p", { text: "Run a built-in scenario to see assertions, before/after digests, and a canonical state diff." }),
      ]),
    ]);
  }
  const assertions = result.assertions.map((item) => node("li", {}, [
    node("span", { className: `assert-icon ${item.pass ? "pass" : "fail"}`, text: item.pass ? "✓" : "✕" }),
    node("span", {}, [
      node("strong", { text: item.label }),
      node("small", { className: "read-value", text: `actual: ${String(item.actual)} · expected: ${String(item.expected)}` }),
    ]),
  ]));
  const diffs = result.diff?.length
    ? result.diff.map((change) => node("li", {}, [
      node("strong", { text: `${change.kind.toLocaleUpperCase()} ${change.entity}` }),
      node("code", { text: change.id }),
      change.fields ? node("span", { className: "read-value", text: change.fields.map((field) => field.field).join(", ") }) : null,
    ]))
    : [node("li", {}, [node("span", { text: "No canonical state changes." })])];
  return node("article", { className: "panel" }, [
    node("header", { className: "panel-header" }, [
      node("h2", { text: result.label }),
      node("span", { className: `badge ${result.passed ? "pass" : "fail"}`, text: result.passed ? "Passed" : "Failed" }),
    ]),
    node("div", { className: "panel-body" }, [
      node("h3", { text: "Assertions" }),
      node("ul", { className: "assertions" }, assertions),
      node("h3", { text: "State diff" }),
      node("ul", { className: "diff-list" }, diffs),
      result.before && result.after ? node("details", {}, [
        node("summary", { text: "Before / after digests and raw diff" }),
        rawJson({
          before: { at: result.before.at, stateDigest: result.before.stateDigest, traceDigest: result.before.traceDigest },
          after: { at: result.after.at, stateDigest: result.after.stateDigest, traceDigest: result.after.traceDigest },
          diff: result.diff,
        }, "diff-json"),
      ]) : null,
    ]),
  ]);
}

function buildTracePanel() {
  const trace = app.twin.getTrace().slice(-120).reverse();
  const rows = trace.map((event) => {
    const detail = rawJson(event, "trace-detail");
    detail.hidden = true;
    const button = node("button", {
      type: "button",
      text: event.type,
      on: {
        click: () => {
          detail.hidden = !detail.hidden;
          button.setAttribute("aria-expanded", String(!detail.hidden));
        },
      },
      "aria-expanded": "false",
    });
    return [
      node("tr", { className: "trace-row" }, [
        node("td", { text: event.sequence }),
        node("td", { className: "trace-type" }, [button]),
        node("td", { text: event.requestId || event.recordId || "—" }),
        node("td", { text: event.at }),
      ]),
      node("tr", {}, [node("td", { colspan: "4" }, [detail])]),
    ];
  }).flat();
  return node("article", { className: "panel" }, [
    node("header", { className: "panel-header" }, [
      node("h2", { text: `Append-only event/request trace · ${app.twin.getTrace().length}` }),
      node("code", { text: app.twin.traceDigest().slice(0, 16) }),
    ]),
    node("div", { className: "panel-body grid-wrap" }, [
      trace.length
        ? node("table", { className: "trace-table" }, [
          node("thead", {}, [node("tr", {}, [
            node("th", { text: "#" }), node("th", { text: "Event" }),
            node("th", { text: "Request / record" }), node("th", { text: "Virtual UTC" }),
          ])]),
          node("tbody", {}, rows),
        ])
        : node("p", { text: "No trace events yet." }),
    ]),
  ]);
}

function advanceClock(milliseconds) {
  app.twin.advanceTime(milliseconds, "ui.manual");
  updateClock();
  announce(`Virtual clock advanced to ${app.twin.now()}.`);
  if (app.currentRoute?.view === "lab") renderLab();
}

function resetTwin() {
  app.twin.reset();
  app.lastScenario = null;
  app.lastManualResponse = null;
  updateClock();
  announce("Twin state reset to the immutable seed snapshot.");
  navigate();
}

async function replayCurrentRun() {
  const replay = app.twin.exportReplay();
  try {
    const reproduced = await app.twin.constructor.replay(replay);
    const matches = reproduced.stateDigest() === app.twin.stateDigest()
      && reproduced.traceDigest() === app.twin.traceDigest();
    app.lastManualResponse = {
      replayedActions: replay.actions.length,
      stateDigest: reproduced.stateDigest(),
      traceDigest: reproduced.traceDigest(),
      matches,
    };
    announce(matches ? "Replay reproduced state and trace digests." : "Replay digest mismatch.");
  } catch (error) {
    app.lastManualResponse = { replayError: error.message };
    announceError(`Replay failed: ${error.message}`);
  }
  renderLab();
}

function renderAbout() {
  setBreadcrumb([{ label: "Service Hub", href: "#/dashboard" }, { label: "API & simulation" }]);
  setCommands([
    command("Open metadata", "↗", () => openExternal(new URL("$metadata.json", API_ROOT)), {
      disabled: !safeHttpUrl(new URL("$metadata.json", API_ROOT)),
    }),
    command("Twin Lab", "⚗", () => { window.location.hash = "#/lab"; }, { primary: true }),
  ]);
  const endpoints = [...app.counts.entries()].map(([entity, count]) => node("div", { className: "endpoint" }, [
    node("code", { text: `GET /api/data/v9.2/${entity}.json` }),
    node("span", { text: `${count.toLocaleString()} immutable seed records · loaded only when routed` }),
  ]));
  replace(ui.root,
    pageHeader("Dynamics 365 API & digital twin", "A deterministic browser-local Service Hub over immutable generated JSON"),
    localNotice(),
    node("aside", { className: "callout" }, [
      node("strong", { text: "Honest simulation boundary: " }),
      "GitHub Pages serves read-only seed JSON. The reusable core simulates POST, PATCH, DELETE, faults, retries, ETags, concurrency, and time only in memory.",
    ]),
    node("section", { className: "panel" }, [
      node("header", { className: "panel-header" }, [node("h2", { text: "Lazy OData-shaped seed endpoints" })]),
      node("div", { className: "panel-body endpoint-list" }, endpoints),
    ]),
    node("section", { className: "dashboard-columns" }, [
      node("article", { className: "panel" }, [
        node("header", { className: "panel-header" }, [node("h2", { text: "Deterministic invariants" })]),
        node("div", { className: "panel-body" }, [
          node("ul", {}, [
            node("li", { text: "Injected virtual UTC clock; no wall-time sleeps." }),
            node("li", { text: "Stable request IDs, GUIDs, ETags, event order, state digest, and trace digest." }),
            node("li", { text: "If-Match returns 412 on stale writes; failed validation and transport do not commit." }),
            node("li", { text: "Post-commit response loss retries by logical request ID without double apply." }),
            node("li", { text: "Connections are fetched only on navigation; metadata supplies counts." }),
          ]),
        ]),
      ]),
      node("article", { className: "panel" }, [
        node("header", { className: "panel-header" }, [node("h2", { text: "Snapshot identity" })]),
        node("div", { className: "panel-body" }, [
          node("p", { text: app.metadata?._snapshot || "No snapshot identity loaded." }),
          externalLink("https://github.com/kody-w/rappterbook", "View Rappterbook source"),
          rawJson(app.metadata),
        ]),
      ]),
    ]),
  );
}

function renderNotFound(path) {
  setBreadcrumb([{ label: "Service Hub", href: "#/dashboard" }, { label: "Not found" }]);
  setCommands([command("Dashboard", "←", () => { window.location.hash = "#/dashboard"; })]);
  replace(ui.root, node("section", { className: "empty-state" }, [
    node("div", {}, [
      node("h2", { text: "Service Hub route not found" }),
      node("p", { text: `No deterministic twin view exists for “${path}”.` }),
      node("a", { href: "#/dashboard", text: "Return to dashboard" }),
    ]),
  ]));
}

function toggleSitemap() {
  const opening = !ui.sitemap.classList.contains("open");
  ui.sitemap.classList.toggle("open", opening);
  ui.scrim.classList.toggle("open", opening);
  ui.sitemapToggle.setAttribute("aria-expanded", String(opening));
}

async function boot() {
  ui.mainContent = document.querySelector("#main-content");
  ui.sitemapToggle.addEventListener("click", toggleSitemap);
  ui.scrim.addEventListener("click", closeSitemap);
  document.querySelector("#header-reset").addEventListener("click", resetTwin);
  window.addEventListener("hashchange", navigate);
  window.addEventListener("unhandledrejection", (event) => {
    announceError(`Unexpected twin error: ${event.reason?.message || event.reason}`);
  });
  updateClock();
  try {
    await loadMetadata();
  } catch (error) {
    showLoadError("Failed to load D365 metadata", error, async () => {
      showLoading("Retrying D365 metadata…");
      try {
        await loadMetadata();
        await navigate();
      } catch (retryError) {
        showLoadError("Failed to load D365 metadata", retryError, boot);
      }
    });
    return;
  }
  if (!window.location.hash) window.location.hash = "#/dashboard";
  else await navigate();
}

boot();
