import {
  BUILT_IN_SCENARIOS,
  ENTITY_DEFINITIONS,
  createTwin,
  parsePath,
  runBuiltInScenario,
} from "./twin-core.mjs?v=6";
import {
  PAGE_SIZE,
  SYSTEM_VIEWS,
  applySystemView,
  captureRouteGuard,
  combineActivities,
  contactStatusLabel,
  createNavigationHistory,
  dashboardRenderCompletion,
  deriveDashboardMetrics,
  editableSnapshotsEqual,
  gridCodeLabel,
  isRecordEditable,
  isTaskOverdue,
  nextRovingTabIndex,
  normalizeEditableSnapshot,
  paginateRows,
  preflightAccountDeletion,
  preflightContactDeletion,
  pushNavigationHistory,
  relatedConnectionsForContact,
  relatedEmailsForAccount,
  relatedEmailsForContact,
  recordCommandActions,
  replaceDialogState,
  routeGuardMatches,
  savedFormRenderTarget,
  searchRows,
  shouldInterceptSpaNavigation,
  stableSortRows,
  transitionHistoryPop,
  transitionHistoryPrompt,
  transitionPatch,
  updateSelection,
} from "./app-helpers.mjs?v=6";

const API_ROOT = new URL("../api/data/v9.2/", import.meta.url);
const RUNTIME_EPOCH = "2026-07-01T09:00:00.000Z";
const DASHBOARD_ENTITIES = Object.freeze(["incidents", "emails", "tasks", "contacts", "accounts"]);
const HISTORY_INDEX_KEY = "customerServiceHistoryIndex";

const ui = {
  root: document.querySelector("#view-root"),
  commands: document.querySelector("#command-bar"),
  main: document.querySelector("#main-content"),
  status: document.querySelector("#live-status"),
  errors: document.querySelector("#live-errors"),
  sitemap: document.querySelector("#sitemap"),
  scrim: document.querySelector("#sitemap-scrim"),
  navigationToggle: document.querySelector("#navigation-toggle"),
  navigationClose: document.querySelector("#navigation-close"),
  launcher: document.querySelector("#app-launcher"),
  selector: document.querySelector("#app-selector"),
  launcherMenu: document.querySelector("#app-launcher-menu"),
  quickCreate: document.querySelector("#quick-create"),
  quickCreateMenu: document.querySelector("#quick-create-menu"),
  areaSwitcher: document.querySelector("#area-switcher"),
  areaMenu: document.querySelector("#area-menu"),
  globalSearch: document.querySelector("#global-search"),
  globalSearchInput: document.querySelector("#global-search-input"),
  dialog: document.querySelector("#app-dialog"),
  dialogTitle: document.querySelector("#dialog-title"),
  dialogContent: document.querySelector("#dialog-content"),
  dialogActions: document.querySelector("#dialog-actions"),
  dialogClose: document.querySelector("#dialog-close"),
};

const app = {
  twin: createTwin({ epoch: RUNTIME_EPOCH, seedName: "customer-service-hub-data" }),
  metadata: null,
  loadedEntities: new Set(),
  entityPromises: new Map(),
  seedInstallTail: Promise.resolve(),
  navigationToken: 0,
  requestCounter: 0,
  currentRoute: null,
  currentHash: "",
  navigationHistory: createNavigationHistory(),
  grid: new Map(),
  associatedGrid: new Map(),
  bpfStages: new Map(),
  dashboardView: "customer-service",
  dirty: false,
  activeForm: null,
  activeDialog: null,
  historyPromptPromise: null,
  lastScenario: null,
  lastManualResponse: null,
  activePopup: null,
  shellListenersReady: false,
};

const ICON_PATHS = Object.freeze({
  add: "M12 5v14M5 12h14",
  back: "m14 6-6 6 6 6M8 12h11",
  cancel: "m6 6 12 12M18 6 6 18",
  check: "m5 12 4 4L19 6",
  delete: "M6 7h12M9 7V4h6v3M8 7l1 13h6l1-13M11 10v7M14 10v7",
  edit: "m5 16-1 4 4-1L18 9l-3-3zM13 8l3 3",
  external: "M13 5h6v6M19 5l-8 8M17 13v6H5V7h6",
  refresh: "M19 8V4l-2 2a8 8 0 1 0 2 9M19 4h-4",
  reopen: "M8 8H4V4M4 8a8 8 0 1 1 1 9",
  save: "M5 4h12l2 2v14H5zM8 4v6h8V4M8 20v-6h8v6",
  search: "M10.5 5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11m4.5 10 5 5",
  state: "M12 4v16M5 12h14",
  time: "M12 4a8 8 0 1 0 8 8 8 8 0 0 0-8-8m0 4v5l3 2",
});

const CHOICES = Object.freeze({
  taskPriority: Object.freeze([[0, "Low"], [1, "Normal"], [2, "High"]]),
  casePriority: Object.freeze([[1, "High"], [2, "Normal"], [3, "Low"]]),
  caseOrigin: Object.freeze([[1, "Phone"], [2, "Email"], [3, "Web"]]),
  caseType: Object.freeze([[1, "Question"], [2, "Problem"], [3, "Request"]]),
});

function field(key, label, options = {}) {
  return { key, label, type: "text", ...options };
}

const ENTITY_UI = Object.freeze({
  contacts: {
    label: "Contacts",
    singular: "Contact",
    route: "contacts",
    primaryKey: "contactid",
    nameField: "fullname",
    creatable: true,
    editable: true,
    deletable: true,
    defaultView: "active",
    columns: [
      field("fullname", "Full Name"),
      field("emailaddress1", "Email"),
      field("jobtitle", "Job Title"),
      field("new_status", "Customer Status", { type: "contact-status" }),
      field("new_karma", "Engagement Score", { type: "number" }),
      field("modifiedon", "Modified On", { type: "date" }),
    ],
    headerFields: [
      field("emailaddress1", "Email"),
      field("jobtitle", "Job title"),
      field("new_status", "Customer status", { type: "contact-status" }),
      field("new_karma", "Engagement score", { type: "number" }),
    ],
    sections: [
      {
        tab: "summary", title: "Contact Information", fields: [
          field("firstname", "First name", { editable: true, required: true }),
          field("lastname", "Last name", { editable: true }),
          field("emailaddress1", "Email", { editable: true, type: "email" }),
          field("description", "Description", { editable: true, type: "textarea", full: true }),
        ],
      },
      {
        tab: "summary", title: "Professional Information", fields: [
          field("jobtitle", "Job title", { editable: true }),
          field("department", "Department", { editable: true }),
          field("new_archetype", "Role category"),
          field("new_status", "Customer status", { type: "contact-status" }),
        ],
      },
      {
        tab: "summary", title: "Engagement", fields: [
          field("new_karma", "Engagement score", { type: "number" }),
          field("new_karmabalance", "Engagement balance", { type: "number" }),
          field("new_postcount", "Contributions", { type: "number" }),
          field("new_commentcount", "Interactions", { type: "number" }),
          field("new_subscribedchannels", "Topics of interest", { full: true }),
        ],
      },
      {
        tab: "details", title: "Administration", fields: [
          field("statecode", "Status", { type: "state" }),
          field("statuscode", "Status reason", { type: "status-reason" }),
          field("createdon", "Created on", { type: "date" }),
          field("modifiedon", "Modified on", { type: "date" }),
        ],
      },
    ],
  },
  accounts: {
    label: "Accounts",
    singular: "Account",
    route: "accounts",
    primaryKey: "accountid",
    nameField: "name",
    creatable: true,
    editable: true,
    deletable: true,
    defaultView: "active",
    columns: [
      field("name", "Account Name"),
      field("new_slug", "Topic"),
      field("new_postcount", "Activity Volume", { type: "number" }),
      field("statecode", "Status", { type: "state" }),
      field("createdon", "Created On", { type: "date" }),
    ],
    headerFields: [
      field("new_slug", "Topic"),
      field("new_postcount", "Activity volume", { type: "number" }),
      field("statecode", "Status", { type: "state" }),
      field("createdon", "Created on", { type: "date" }),
    ],
    sections: [
      {
        tab: "summary", title: "Account Information", fields: [
          field("name", "Account name", { editable: true, required: true }),
          field("websiteurl", "Website", { editable: true, type: "url" }),
          field("description", "Description", { editable: true, type: "textarea", full: true }),
        ],
      },
      {
        tab: "summary", title: "Engagement Profile", fields: [
          field("new_slug", "Topic"),
          field("new_postcount", "Activity volume", { type: "number" }),
          field("new_topicaffinity", "Topic affinity", { editable: true }),
          field("new_constitution", "Service notes", { editable: true, type: "textarea", full: true }),
        ],
      },
      {
        tab: "details", title: "Administration", fields: [
          field("statecode", "Status", { type: "state" }),
          field("statuscode", "Status reason", { type: "status-reason" }),
          field("createdon", "Created on", { type: "date" }),
          field("modifiedon", "Modified on", { type: "date" }),
        ],
      },
    ],
  },
  emails: {
    label: "Email Activities",
    singular: "Email",
    route: "emails",
    primaryKey: "activityid",
    nameField: "subject",
    creatable: false,
    editable: false,
    deletable: true,
    columns: [],
    headerFields: [
      field("sender", "From"),
      field("torecipients", "To"),
      field("actualend", "Sent on", { type: "date" }),
      field("new_channel", "Topic"),
    ],
    sections: [
      {
        tab: "summary", title: "Message", fields: [
          field("subject", "Subject", { full: true }),
          field("sender", "From"),
          field("torecipients", "To"),
          field("description", "Message", { type: "multiline", full: true }),
        ],
      },
      {
        tab: "summary", title: "Regarding", fields: [
          field("new_channel", "Topic"),
          field("new_posttopic", "Subject category"),
          field("new_url", "Source", { type: "url", full: true }),
        ],
      },
      {
        tab: "summary", title: "Interaction Summary", fields: [
          field("new_upvotes", "Positive responses", { type: "number" }),
          field("new_downvotes", "Negative responses", { type: "number" }),
          field("new_commentcount", "Responses", { type: "number" }),
        ],
      },
      {
        tab: "details", title: "Administration", fields: [
          field("statecode", "Status", { type: "state" }),
          field("statuscode", "Status reason", { type: "status-reason" }),
          field("createdon", "Created on", { type: "date" }),
          field("modifiedon", "Modified on", { type: "date" }),
          field("actualend", "Sent on", { type: "date" }),
        ],
      },
    ],
  },
  tasks: {
    label: "Tasks",
    singular: "Task",
    route: "tasks",
    primaryKey: "activityid",
    nameField: "subject",
    creatable: true,
    editable: true,
    deletable: true,
    columns: [],
    headerFields: [
      field("statecode", "Status", { type: "task-state" }),
      field("prioritycode", "Priority", { type: "priority" }),
      field("scheduledend", "Due", { type: "date" }),
      field("actualend", "Completed on", { type: "date" }),
    ],
    sections: [
      {
        tab: "summary", title: "Task Details", fields: [
          field("subject", "Subject", { editable: true, required: true, full: true }),
          field("prioritycode", "Priority", { editable: true, type: "choice", choices: CHOICES.taskPriority, defaultValue: 1 }),
          field("description", "Description", { editable: true, type: "textarea", full: true }),
        ],
      },
      {
        tab: "summary", title: "Scheduling", fields: [
          field("scheduledend", "Due", { editable: true, type: "datetime" }),
          field("actualend", "Completed on", { type: "date" }),
          field("new_poketype", "Interaction type"),
        ],
      },
      {
        tab: "details", title: "Administration", fields: [
          field("statecode", "Status", { type: "task-state" }),
          field("statuscode", "Status reason", { type: "status-reason" }),
          field("createdon", "Created on", { type: "date" }),
          field("modifiedon", "Modified on", { type: "date" }),
        ],
      },
    ],
  },
  incidents: {
    label: "Cases",
    singular: "Case",
    route: "cases",
    primaryKey: "incidentid",
    nameField: "title",
    creatable: true,
    editable: true,
    deletable: true,
    defaultView: "active",
    columns: [
      field("title", "Case Title"),
      field("new_category", "Category"),
      field("prioritycode", "Priority", { type: "priority" }),
      field("new_sla_status", "SLA Status", { type: "service-status" }),
      field("statecode", "Status", { type: "state" }),
      field("createdon", "Created On", { type: "date" }),
    ],
    headerFields: [
      field("statecode", "Status", { type: "state" }),
      field("prioritycode", "Priority", { type: "priority" }),
      field("new_category", "Category"),
      field("new_sla_status", "SLA status", { type: "service-status" }),
    ],
    sections: [
      {
        tab: "summary", title: "Case Summary", fields: [
          field("title", "Case title", { editable: true, required: true, full: true }),
        ],
      },
      {
        tab: "summary", title: "Classification", fields: [
          field("prioritycode", "Priority", { editable: true, type: "choice", choices: CHOICES.casePriority, defaultValue: 2 }),
          field("caseorigincode", "Origin", { editable: true, type: "choice", choices: CHOICES.caseOrigin, defaultValue: 3 }),
          field("casetypecode", "Case type", { editable: true, type: "choice", choices: CHOICES.caseType, defaultValue: 2 }),
          field("new_category", "Category", { editable: true }),
          field("severitycode", "Severity", { type: "number" }),
        ],
      },
      {
        tab: "summary", title: "Service Level", fields: [
          field("new_sla_status", "SLA status", { type: "service-status" }),
          field("new_sla_due", "SLA due", { editable: true, type: "datetime" }),
          field("new_score", "Service score", { type: "number" }),
          field("new_overallscore", "Overall score", { type: "number" }),
          field("new_grade", "Service grade"),
        ],
      },
      {
        tab: "details", title: "Description", fields: [
          field("description", "Detailed description", { editable: true, type: "textarea", full: true }),
        ],
      },
      {
        tab: "details", title: "Administration", fields: [
          field("statecode", "Status", { type: "state" }),
          field("statuscode", "Status reason", { type: "status-reason" }),
          field("createdon", "Created on", { type: "date" }),
          field("modifiedon", "Modified on", { type: "date" }),
        ],
      },
    ],
  },
});

const ACTIVITIES_GRID = Object.freeze({
  label: "Activities",
  singular: "Activity",
  primaryKey: "_key",
  defaultView: "open",
  creatable: true,
  editable: true,
  deletable: true,
  columns: [
    field("subject", "Subject"),
    field("_activityType", "Activity Type"),
    field("_status", "Status", { type: "activity-status" }),
    field("_regarding", "Regarding"),
    field("_dueOrSent", "Due or Sent", { type: "date" }),
    field("prioritycode", "Priority", { type: "activity-priority" }),
  ],
});

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
    else if (key === "selected") element.selected = Boolean(value);
    else if (key === "hidden") element.hidden = Boolean(value);
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

function svgElement(tag, attributes = {}, children = []) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  for (const child of children) element.append(child);
  return element;
}

function icon(name, className = "ui-icon") {
  const svg = svgElement("svg", {
    class: className,
    viewBox: "0 0 24 24",
    "aria-hidden": "true",
    focusable: "false",
  });
  svg.append(svgElement("path", { d: ICON_PATHS[name] || ICON_PATHS.state }));
  return svg;
}

function replace(target, ...children) {
  target.replaceChildren(...children.flat(Infinity).filter((child) => child !== null && child !== undefined));
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

function requestId(prefix) {
  app.requestCounter += 1;
  return `ui-${prefix}-${String(app.requestCounter).padStart(5, "0")}`;
}

function currentRouteGuard() {
  return captureRouteGuard(app.navigationToken, app.currentRoute);
}

function routeGuardIsCurrent(guard) {
  return routeGuardMatches(guard, app.navigationToken, app.currentRoute);
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
  if (!safe) return node("span", { className: "field-value", text: value || "" });
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
    showErrorDialog("Link could not be opened", "Only HTTP and HTTPS links can be opened.");
    return;
  }
  const opened = window.open(safe, "_blank", "noopener,noreferrer");
  if (opened) opened.opener = null;
}

function rawJson(value, className = "json-block") {
  const output = node("pre", { className });
  output.textContent = JSON.stringify(value, null, 2);
  return output;
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
  if (!Array.isArray(metadata.EntitySets)) throw new Error("Entity set metadata is unavailable.");
  app.metadata = metadata;
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

function decodeSegment(value) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function parseRoute() {
  const hash = window.location.hash || "#/dashboard";
  const [rawPath, rawQuery = ""] = hash.replace(/^#\/?/, "").split("?");
  const segments = rawPath.split("/").filter(Boolean).map(decodeSegment);
  const query = new URLSearchParams(rawQuery);
  if (!segments.length || segments[0] === "dashboard") return { view: "dashboard" };
  if (segments[0] === "activities") return { view: "grid", entity: "activities" };
  if (segments[0] === "emails") {
    return segments[1]
      ? { view: "record", entity: "emails", id: segments[1] }
      : { view: "grid", entity: "activities", initialView: "sent-email" };
  }
  if (segments[0] === "tasks") {
    return segments[1]
      ? { view: "record", entity: "tasks", id: segments[1] }
      : { view: "grid", entity: "activities", initialView: "open" };
  }
  if (segments[0] === "contacts" || segments[0] === "accounts") {
    return segments[1]
      ? { view: "record", entity: segments[0], id: segments[1], initialTab: segments[2] === "related" ? "related" : null }
      : { view: "grid", entity: segments[0] };
  }
  if (segments[0] === "cases" || segments[0] === "incidents") {
    return segments[1]
      ? { view: "record", entity: "incidents", id: segments[1] }
      : { view: "grid", entity: "incidents" };
  }
  if (segments[0] === "queues") return { view: "queues" };
  if (segments[0] === "knowledge-articles") return { view: "knowledge-articles" };
  if (segments[0] === "knowledge-search") return { view: "knowledge-search", query: query.get("q") || "" };
  if (segments[0] === "search") return { view: "search", query: query.get("q") || "" };
  if (segments[0] === "lab") return { view: "simulation-settings", scenario: query.get("scenario") };
  if (segments[0] === "about") return { view: "api-simulation" };
  if (segments[0] === "service-management" && segments[1] === "simulation-settings") {
    return { view: "simulation-settings", scenario: query.get("scenario") };
  }
  if (segments[0] === "service-management" && segments[1] === "api-simulation") {
    return { view: "api-simulation" };
  }
  return { view: "not-found", path: rawPath };
}

function routeHref(entity, id = null) {
  const route = entity === "incidents" ? "cases" : entity;
  return id ? `#/${route}/${encodeURIComponent(id)}` : `#/${route}`;
}

function routeNavKey(route) {
  if (route.view === "record") {
    if (route.entity === "emails" || route.entity === "tasks") return "activities";
    return route.entity === "incidents" ? "cases" : route.entity;
  }
  if (route.view === "grid") return route.entity === "incidents" ? "cases" : route.entity;
  return route.view;
}

function setActiveNavigation(route) {
  const active = routeNavKey(route);
  for (const link of document.querySelectorAll("[data-nav]")) {
    const selected = link.dataset.nav === active;
    link.classList.toggle("active", selected);
    if (selected) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  const management = ["simulation-settings", "api-simulation"].includes(active);
  ui.sitemap.classList.toggle("management-area", management);
  ui.areaSwitcher.querySelector("span").textContent = management ? "Service Management" : "Customer Service";
}

function showLoading(message) {
  setBusy(true);
  setCommands([]);
  replace(ui.root, node("div", { className: "loading-state", role: "status" }, [
    node("span", { className: "spinner", "aria-hidden": "true" }),
    node("span", { text: message }),
  ]));
}

function showLoadError(title, error, retry) {
  setBusy(false);
  setCommands([]);
  replace(ui.root, node("section", { className: "error-state", role: "alert" }, [
    icon("cancel", "state-icon"),
    node("h1", { text: title }),
    node("p", { text: error.message }),
    node("button", { className: "primary-button", type: "button", text: "Try again", on: { click: retry } }),
  ]));
  announceError(`${title}: ${error.message}`);
}

function pageHeading(title, subtitle = "") {
  return node("header", { className: "page-heading" }, [
    node("div", {}, [
      node("h1", { text: title }),
      subtitle ? node("p", { text: subtitle }) : null,
    ]),
  ]);
}

function command(label, iconName, handler, options = {}) {
  return node("button", {
    id: options.id,
    type: "button",
    className: `command${options.primary ? " primary" : ""}${options.danger ? " danger" : ""}`,
    disabled: options.disabled,
    title: options.title || label,
    "aria-label": options.ariaLabel || label,
    "data-action": options.action,
    on: { click: handler },
  }, [icon(iconName), node("span", { text: label })]);
}

function setCommands(commands) {
  const children = [];
  for (const item of commands) {
    if (item === "separator") children.push(node("span", { className: "command-separator", "aria-hidden": "true" }));
    else if (item) children.push(item);
  }
  replace(ui.commands, children);
  ui.commands.hidden = children.length === 0;
}

function closePopup(restoreFocus = false) {
  if (!app.activePopup) return;
  const { button, panel } = app.activePopup;
  panel.hidden = true;
  button.setAttribute("aria-expanded", "false");
  app.activePopup = null;
  if (restoreFocus) button.focus();
}

function togglePopup(button, panel) {
  const alreadyOpen = app.activePopup?.panel === panel;
  closePopup();
  if (alreadyOpen) return;
  panel.hidden = false;
  button.setAttribute("aria-expanded", "true");
  app.activePopup = { button, panel };
  panel.querySelector("a, button")?.focus();
}

function openSitemap() {
  closePopup();
  ui.sitemap.classList.add("open");
  ui.scrim.classList.add("open");
  ui.navigationToggle.setAttribute("aria-expanded", "true");
  ui.sitemap.querySelector("a[aria-current='page']")?.focus();
}

function closeSitemap(restoreFocus = false) {
  const wasOpen = ui.sitemap.classList.contains("open");
  ui.sitemap.classList.remove("open");
  ui.scrim.classList.remove("open");
  ui.navigationToggle.setAttribute("aria-expanded", "false");
  if (wasOpen && restoreFocus) ui.navigationToggle.focus();
}

function focusableElements(container) {
  return [...container.querySelectorAll(
    "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
  )].filter((element) => !element.hidden && element.getAttribute("aria-hidden") !== "true");
}

function showDialog({ title, content, actions, cancelValue = "cancel" }) {
  const dialog = { cancelValue, finish: null };
  const replacement = replaceDialogState(app.activeDialog, dialog);
  app.activeDialog = replacement.activeDialog;
  if (replacement.replacement) {
    replacement.replacement.dialog.finish(replacement.replacement.value);
  }
  const previousFocus = document.activeElement;
  ui.dialogTitle.textContent = title;
  replace(ui.dialogContent, ...(Array.isArray(content) ? content : [node("p", { text: content })]));
  replace(ui.dialogActions);
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      if (app.activeDialog === dialog) app.activeDialog = null;
      ui.dialog.removeEventListener("cancel", handleCancel);
      ui.dialog.removeEventListener("keydown", trapFocus);
      ui.dialogClose.removeEventListener("click", handleClose);
      if (ui.dialog.open) ui.dialog.close();
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
      resolve(value);
    };
    const handleCancel = (event) => {
      event.preventDefault();
      finish(cancelValue);
    };
    const handleClose = () => finish(cancelValue);
    const trapFocus = (event) => {
      if (event.key !== "Tab") return;
      const focusable = focusableElements(ui.dialog);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    for (const action of actions) {
      ui.dialogActions.append(node("button", {
        type: "button",
        className: `${action.primary ? "primary-button" : "secondary-button"}${action.danger ? " danger" : ""}`,
        text: action.label,
        on: { click: () => finish(action.value) },
      }));
    }
    dialog.finish = finish;
    ui.dialogClose.addEventListener("click", handleClose);
    ui.dialog.addEventListener("cancel", handleCancel);
    ui.dialog.addEventListener("keydown", trapFocus);
    ui.dialog.showModal();
    ui.dialogActions.querySelector(".primary-button")?.focus()
      || ui.dialogActions.querySelector("button")?.focus();
  });
}

function showErrorDialog(title, message) {
  announceError(`${title}: ${message}`);
  return showDialog({
    title,
    content: message,
    actions: [{ label: "Close", value: "close", primary: true }],
    cancelValue: "close",
  });
}

function confirmAction(title, message, confirmLabel, danger = false) {
  return showDialog({
    title,
    content: message,
    actions: [
      { label: "Cancel", value: false },
      { label: confirmLabel, value: true, primary: true, danger },
    ],
    cancelValue: false,
  });
}

function setDirty(dirty) {
  app.dirty = Boolean(dirty);
  document.body.classList.toggle("record-dirty", app.dirty);
}

async function resolveDirtyState() {
  if (!app.dirty) return true;
  const choice = await showDialog({
    title: "Unsaved changes",
    content: "Your changes have not been saved. What would you like to do?",
    actions: [
      { label: "Cancel", value: "cancel" },
      { label: "Discard changes", value: "discard", danger: true },
      { label: "Save", value: "save", primary: true },
    ],
  });
  if (choice === "cancel") return false;
  if (choice === "discard") {
    setDirty(false);
    return true;
  }
  const activeForm = app.activeForm;
  if (!activeForm) return false;
  const selectedTab = activeForm.form.closest(".record-shell")
    ?.querySelector(".form-tab[aria-selected='true']")
    ?.id.replace(/^tab-/, "") || "summary";
  const savedRecord = await saveRecord(
    activeForm.entity,
    activeForm.record,
    activeForm.form,
    { render: false },
  );
  const renderTarget = savedFormRenderTarget(activeForm, savedRecord, selectedTab);
  if (!renderTarget) return false;
  renderRecordForm(renderTarget.entity, renderTarget.record, renderTarget.initialTab);
  return true;
}

async function requestNavigation(href) {
  const target = String(href || "#/dashboard");
  if (!(await resolveDirtyState())) return;
  closePopup();
  closeSitemap();
  if (window.location.hash === target) {
    app.currentHash = target;
    await navigate();
  } else {
    app.navigationHistory = pushNavigationHistory(app.navigationHistory);
    window.history.pushState({
      ...(window.history.state || {}),
      [HISTORY_INDEX_KEY]: app.navigationHistory.currentIndex,
    }, "", target);
    app.currentHash = target;
    await navigate();
  }
}

function indexedHistoryPosition(state) {
  const index = state?.[HISTORY_INDEX_KEY];
  return Number.isInteger(index) ? index : null;
}

async function runHistoryPrompt() {
  const proceed = await resolveDirtyState();
  const transition = transitionHistoryPrompt(app.navigationHistory, proceed);
  app.navigationHistory = transition.state;
  if (transition.effect.type === "traverse") window.history.go(transition.effect.delta);
}

function serializedHistoryPrompt() {
  if (app.historyPromptPromise) return app.historyPromptPromise;
  const prompt = runHistoryPrompt();
  const serialized = prompt.finally(() => {
    if (app.historyPromptPromise === serialized) app.historyPromptPromise = null;
  });
  app.historyPromptPromise = serialized;
  return serialized;
}

async function handlePopState(event) {
  const transition = transitionHistoryPop(
    app.navigationHistory,
    indexedHistoryPosition(event.state),
    app.dirty,
  );
  app.navigationHistory = transition.state;
  if (transition.effect.type === "traverse") {
    window.history.go(transition.effect.delta);
    return;
  }
  if (transition.effect.type === "prompt") {
    await serializedHistoryPrompt();
    return;
  }
  if (transition.effect.type === "navigate" || transition.effect.type === "unknown") {
    app.currentHash = window.location.hash || "#/dashboard";
    await navigate();
  }
}

function formatUtcDate(value) {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return String(value || "");
  const date = new Date(timestamp);
  const pad = (part, length = 2) => String(part).padStart(length, "0");
  return `${pad(date.getUTCFullYear(), 4)}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())} ${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())} UTC`;
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

function choiceLabel(descriptor, value) {
  const match = descriptor.choices?.find(([choice]) => String(choice) === String(value));
  return match ? match[1] : String(value ?? "");
}

function formattedValue(value, descriptor, entity = null, record = null) {
  if (value === undefined || value === null || value === "") return "";
  if (descriptor.type === "date" || descriptor.type === "datetime") return formatUtcDate(value);
  if (descriptor.type === "number") {
    const number = Number(value);
    return Number.isFinite(number) ? number.toLocaleString("en-US") : String(value);
  }
  if (descriptor.type === "choice") return choiceLabel(descriptor, value);
  if (descriptor.type === "status-reason") {
    const labels = {
      contacts: { 1: "Active", 2: "Inactive" },
      accounts: { 1: "Active", 2: "Inactive" },
      emails: { 3: "Sent" },
      tasks: { 2: "Not Started", 5: "Completed", 6: "Canceled" },
      incidents: { 1: "In Progress", 5: "Problem Solved", 6: "Canceled" },
    };
    return labels[entity]?.[Number(value)] || String(value);
  }
  if (descriptor.type === "state") return gridCodeLabel(entity, "statecode", value, app.twin.now(), record) || "";
  if (descriptor.type === "task-state") return gridCodeLabel("tasks", "statecode", value, app.twin.now(), record) || "";
  if (descriptor.type === "priority") return gridCodeLabel(entity, "prioritycode", value) || "";
  if (descriptor.type === "activity-priority") {
    return record?._entity === "tasks" ? gridCodeLabel("tasks", "prioritycode", value) || "" : "";
  }
  if (descriptor.type === "contact-status") {
    return contactStatusLabel(value);
  }
  return String(value);
}

function statusClass(label) {
  const normalized = String(label).toLowerCase();
  if (["active", "open", "sent", "completed", "met"].includes(normalized)) return "positive";
  if (["inactive", "canceled", "cancelled", "resolved"].includes(normalized)) return "neutral";
  if (["overdue", "breached"].includes(normalized)) return "negative";
  return "neutral";
}

function valueNode(record, descriptor, entity) {
  const value = record[descriptor.key];
  const label = formattedValue(value, descriptor, entity, record);
  if (["state", "task-state", "activity-status", "service-status", "contact-status"].includes(descriptor.type)) {
    return label ? node("span", { className: `status-badge ${statusClass(label)}`, text: label }) : document.createTextNode("");
  }
  return document.createTextNode(label);
}

function createBarChart(title, data, ariaLabel) {
  const width = 520;
  const rowHeight = 34;
  const height = Math.max(82, data.length * rowHeight + 26);
  const maximum = Math.max(1, ...data.map((item) => Number(item.value) || 0));
  const svg = svgElement("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": ariaLabel,
    preserveAspectRatio: "xMinYMin meet",
  });
  data.forEach((item, index) => {
    const y = index * rowHeight + 8;
    const barWidth = Math.max(0, (Number(item.value) || 0) / maximum * 300);
    const label = svgElement("text", { x: 0, y: y + 18, class: "chart-label" });
    label.textContent = item.label;
    const background = svgElement("rect", { x: 150, y, width: 300, height: 22, rx: 2, class: "chart-track" });
    const bar = svgElement("rect", { x: 150, y, width: barWidth, height: 22, rx: 2, class: "chart-bar" });
    const count = svgElement("text", { x: 462, y: y + 17, class: "chart-value" });
    count.textContent = String(item.value);
    svg.append(label, background, bar, count);
  });
  return node("figure", { className: "chart-figure" }, [
    node("figcaption", { text: title }),
    svg,
    node("ul", { className: "sr-only" }, data.map((item) =>
      node("li", { text: `${item.label}: ${item.value}` }))),
  ]);
}

function recordLink(entity, record, text) {
  const config = ENTITY_UI[entity];
  return node("a", {
    href: routeHref(entity, record[config.primaryKey]),
    text: text || record[config.nameField] || "",
  });
}

function dashboardChartPanel(title, data) {
  return node("article", { className: "dashboard-panel" }, [
    createBarChart(
      title,
      data,
      data.map((item) => `${item.label} ${item.value}`).join(", "),
    ),
  ]);
}

function customerServiceDashboardPanels(metrics) {
  const activeCases = metrics.activeCases.slice(0, 8);
  const accountChart = metrics.accountActivity.slice(0, 8);
  return [
    dashboardListPanel("Active Cases", activeCases, (record) => ({
      href: routeHref("incidents", record.incidentid),
      title: record.title,
      meta: `${gridCodeLabel("incidents", "prioritycode", record.prioritycode) || ""} priority`,
    }), "There are no active cases."),
    dashboardListPanel("Recent Activities", metrics.recentActivities, (record) => ({
      href: routeHref(record._entity, record._id),
      title: record.subject,
      meta: `${record._activityType} · ${record._status}`,
    }), "There are no recent activities."),
    dashboardChartPanel("Cases by Priority", metrics.casePriority),
    dashboardChartPanel("Contacts by Status", metrics.contactStatus),
    node("article", { className: "dashboard-panel wide" }, [
      createBarChart(
        "Accounts by Activity Volume",
        accountChart,
        accountChart.map((item) => `${item.label} ${item.value}`).join(", "),
      ),
      node("ol", { className: "ranked-list" }, accountChart.map((item) => node("li", {}, [
        node("a", { href: routeHref("accounts", item.id), text: item.label }),
        node("span", { text: item.value.toLocaleString("en-US") }),
      ]))),
    ]),
    dashboardListPanel("Open Activities", metrics.openActivities.slice(0, 8), (record) => ({
      href: routeHref(record._entity, record._id),
      title: record.subject,
      meta: record._status,
    }), "There are no open activities."),
  ];
}

function serviceActivityDashboardPanels(metrics) {
  return [
    dashboardListPanel("Recent Activities", metrics.recentActivities, (record) => ({
      href: routeHref(record._entity, record._id),
      title: record.subject,
      meta: `${record._activityType} · ${record._status}`,
    }), "There are no recent activities."),
    dashboardListPanel("Open Activities", metrics.openActivities.slice(0, 8), (record) => ({
      href: routeHref(record._entity, record._id),
      title: record.subject,
      meta: `${record._activityType} · ${record._status}`,
    }), "There are no open activities."),
    dashboardListPanel("Sent Email", metrics.sentEmails.slice(0, 8), (record) => ({
      href: routeHref(record._entity, record._id),
      title: record.subject,
      meta: formatUtcDate(record._dueOrSent),
    }), "There is no sent email."),
    dashboardChartPanel("Activities by Type", metrics.activitiesByType),
    dashboardChartPanel("Activities by Status", metrics.activitiesByStatus),
    dashboardListPanel("Tasks", metrics.taskActivities.slice(0, 8), (record) => ({
      href: routeHref(record._entity, record._id),
      title: record.subject,
      meta: record._dueOrSent
        ? `${record._status} · Due ${formatUtcDate(record._dueOrSent)}`
        : record._status,
    }), "There are no tasks."),
  ];
}

async function renderDashboard(expectedToken = app.navigationToken, focusTarget = null) {
  const routeGuard = captureRouteGuard(expectedToken, app.currentRoute);
  if (focusTarget) setBusy(true);
  else showLoading("Loading dashboard");
  try {
    await ensureEntities(DASHBOARD_ENTITIES);
    if (!routeGuardIsCurrent(routeGuard)) return;
    const metrics = deriveDashboardMetrics({
      incidents: app.twin.getState("incidents"),
      emails: app.twin.getState("emails"),
      tasks: app.twin.getState("tasks"),
      contacts: app.twin.getState("contacts"),
      accounts: app.twin.getState("accounts"),
    }, app.twin.now());
    setCommands([
      command("Refresh", "refresh", async () => {
        const refreshGuard = currentRouteGuard();
        await renderDashboard(refreshGuard.navigationToken, "refresh");
        if (!routeGuardIsCurrent(refreshGuard)) return;
        announce("Dashboard refreshed.");
      }, { id: "dashboard-refresh", action: "refresh-dashboard" }),
    ]);
    const dashboardChoices = [
      ["customer-service", "Customer Service Dashboard"],
      ["service-activity", "Service Activity Dashboard"],
    ];
    const dashboardTitle = dashboardChoices.find(([value]) => value === app.dashboardView)?.[1]
      || dashboardChoices[0][1];
    const selector = node("select", {
      id: "dashboard-selector",
      "data-action": "select-dashboard",
      "aria-label": "Dashboard",
      on: {
        change: async (event) => {
          app.dashboardView = event.currentTarget.value;
          await renderDashboard(app.navigationToken, "selector");
        },
      },
    }, dashboardChoices.map(([value, label]) =>
      node("option", { value, text: label, selected: app.dashboardView === value })));
    const panels = app.dashboardView === "service-activity"
      ? serviceActivityDashboardPanels(metrics)
      : customerServiceDashboardPanels(metrics);
    replace(ui.root,
      pageHeading(dashboardTitle),
      node("div", { className: "dashboard-selector" }, [
        node("label", { for: "dashboard-selector", text: "Dashboard" }),
        selector,
      ]),
      node("div", { className: "dashboard-layout" }, panels),
    );
  } finally {
    if (routeGuardIsCurrent(routeGuard)) {
      const completion = dashboardRenderCompletion(focusTarget);
      setBusy(completion.busy);
      if (completion.focusTargetId) {
        document.getElementById(completion.focusTargetId)?.focus();
      }
    }
  }
}

function dashboardListPanel(title, records, describe, emptyMessage) {
  return node("article", { className: "dashboard-panel" }, [
    node("header", { className: "panel-heading" }, [node("h2", { text: title })]),
    records.length
      ? node("ul", { className: "record-list" }, records.map((record) => {
        const item = describe(record);
        return node("li", {}, [
          node("a", { href: item.href, text: item.title || "" }),
          node("span", { text: item.meta || "" }),
        ]);
      }))
      : node("div", { className: "component-empty" }, [
        icon("search", "empty-icon"),
        node("p", { text: emptyMessage }),
      ]),
  ]);
}

function getGridState(entity, initialView = null) {
  const config = entity === "activities" ? ACTIVITIES_GRID : ENTITY_UI[entity];
  if (!app.grid.has(entity)) {
    app.grid.set(entity, {
      view: initialView || config.defaultView,
      search: "",
      sort: config.columns[0].key,
      direction: "asc",
      page: 1,
      selected: new Set(),
    });
  }
  const state = app.grid.get(entity);
  if (initialView && state.view !== initialView) {
    state.view = initialView;
    state.page = 1;
    state.selected.clear();
  }
  return state;
}

async function gridRecords(entity) {
  if (entity === "activities") {
    await ensureEntities(["emails", "tasks"]);
    return combineActivities(
      app.twin.getState("emails"),
      app.twin.getState("tasks"),
      app.twin.now(),
    ).map((record) => ({ ...record, _key: `${record._entity}:${record._id}` }));
  }
  await ensureEntity(entity);
  return app.twin.getState(entity);
}

function gridRecordKey(entity, record) {
  const config = entity === "activities" ? ACTIVITIES_GRID : ENTITY_UI[entity];
  return String(record[config.primaryKey]);
}

function gridRecordHref(entity, record) {
  return entity === "activities"
    ? routeHref(record._entity, record._id)
    : routeHref(entity, record[ENTITY_UI[entity].primaryKey]);
}

async function renderGridRoute(route, expectedToken) {
  const config = route.entity === "activities" ? ACTIVITIES_GRID : ENTITY_UI[route.entity];
  const routeGuard = captureRouteGuard(expectedToken, route);
  showLoading(`Loading ${config.label}`);
  const records = await gridRecords(route.entity);
  if (!routeGuardIsCurrent(routeGuard)) return;
  renderGrid(route.entity, records, route.initialView);
}

function renderGrid(entity, records, initialView = null, focusTarget = null) {
  const config = entity === "activities" ? ACTIVITIES_GRID : ENTITY_UI[entity];
  const state = getGridState(entity, initialView);
  const viewed = applySystemView(records, entity, state.view);
  const columns = new Map(config.columns.map((column) => [column.key, column]));
  const searched = searchRows(
    viewed,
    config.columns.map((column) => column.key),
    state.search,
    (record, key) => formattedValue(
      record[key],
      columns.get(key),
      entity === "activities" ? record._entity : entity,
      record,
    ),
  );
  const sorted = stableSortRows(searched, state.sort, state.direction, config.primaryKey);
  const page = paginateRows(sorted, state.page, PAGE_SIZE);
  state.page = page.page;
  const recordMap = new Map(records.map((record) => [gridRecordKey(entity, record), record]));
  const selected = [...state.selected].map((key) => recordMap.get(key)).filter(Boolean);
  setGridCommands(entity, state, records, selected);

  const viewSelector = node("select", {
    id: "system-view",
    className: "view-selector",
    "aria-label": `${config.label} system view`,
    value: state.view,
    on: {
      change: (event) => {
        state.view = event.target.value;
        state.page = 1;
        state.selected.clear();
        renderGrid(entity, records, null, "system-view");
      },
    },
  }, (SYSTEM_VIEWS[entity] || []).map((view) =>
    node("option", { value: view.id, text: view.label, selected: state.view === view.id })));

  const searchInput = node("input", {
    id: "view-search",
    type: "search",
    value: state.search,
    placeholder: "Search this view",
    "aria-label": "Search this view",
    on: {
      keydown: (event) => {
        if (event.key === "Enter") event.preventDefault();
      },
      input: (event) => {
        state.search = event.target.value;
        state.page = 1;
        state.selected.clear();
        renderGrid(entity, records, null, "view-search");
        const next = document.querySelector("#view-search");
        next?.focus();
        next?.setSelectionRange(state.search.length, state.search.length);
      },
    },
  });

  const pageKeys = page.rows.map((record) => gridRecordKey(entity, record));
  const allPageSelected = pageKeys.length > 0 && pageKeys.every((key) => state.selected.has(key));
  const headerCells = [
    node("th", { scope: "col", className: "selection-column" }, [
      node("input", {
        type: "checkbox",
        checked: allPageSelected,
        "aria-label": allPageSelected ? "Clear page selection" : "Select page",
        on: {
          change: (event) => {
            state.selected = updateSelection(state.selected, pageKeys, event.target.checked);
            renderGrid(entity, records);
          },
        },
      }),
    ]),
    ...config.columns.map((column) => {
      const active = state.sort === column.key;
      return node("th", {
        scope: "col",
        "aria-sort": active ? (state.direction === "asc" ? "ascending" : "descending") : "none",
      }, [
        node("button", {
          type: "button",
          className: "sort-button",
          on: {
            click: () => {
              if (active) state.direction = state.direction === "asc" ? "desc" : "asc";
              else {
                state.sort = column.key;
                state.direction = "asc";
              }
              state.page = 1;
              renderGrid(entity, records);
            },
          },
        }, [
          node("span", { text: column.label }),
          active ? icon(state.direction === "asc" ? "back" : "back", `sort-icon ${state.direction}`) : null,
        ]),
      ]);
    }),
  ];

  const bodyRows = page.rows.map((record) => {
    const key = gridRecordKey(entity, record);
    return node("tr", { className: state.selected.has(key) ? "selected" : "" }, [
      node("td", { className: "selection-column" }, [
        node("input", {
          id: `select-${key.replace(/[^a-zA-Z0-9_-]/g, "-")}`,
          type: "checkbox",
          checked: state.selected.has(key),
          "aria-label": `Select ${record[config.columns[0].key] || config.singular}`,
          on: {
            change: (event) => {
              state.selected = updateSelection(state.selected, [key], event.target.checked);
              renderGrid(entity, records, null, `select-${key.replace(/[^a-zA-Z0-9_-]/g, "-")}`);
            },
          },
        }),
      ]),
      ...config.columns.map((column, index) => node("td", {
        dataset: { label: column.label },
        title: formattedValue(record[column.key], column, entity === "activities" ? record._entity : entity, record),
      }, [
        index === 0
          ? node("a", {
            className: "record-link",
            href: gridRecordHref(entity, record),
            text: formattedValue(record[column.key], column, entity === "activities" ? record._entity : entity, record),
          })
          : valueNode(record, column, entity === "activities" ? record._entity : entity),
      ])),
    ]);
  });

  const columnCount = config.columns.length + 1;
  const body = bodyRows.length
    ? node("tbody", {}, bodyRows)
    : node("tbody", {}, [
      node("tr", {}, [
        node("td", { className: "grid-empty", colspan: String(columnCount) }, [
          icon("search", "empty-icon"),
          node("strong", { text: "No records found" }),
          node("span", { text: state.search ? "Try a different search." : "This view has no records." }),
        ]),
      ]),
    ]);
  replace(ui.root,
    pageHeading(config.label),
    node("div", { className: "view-toolbar" }, [
      node("div", { className: "view-choice" }, [
        node("label", { for: "system-view", text: "View" }),
        viewSelector,
      ]),
      node("div", { className: "view-search" }, [icon("search"), searchInput]),
    ]),
    node("div", { className: "grid-surface" }, [
      node("div", { className: "grid-scroll" }, [
        node("table", { className: "data-grid", "aria-label": `${config.label} — ${viewLabel(entity, state.view)}` }, [
          node("thead", {}, [node("tr", {}, headerCells)]),
          body,
        ]),
      ]),
      gridFooter(page, () => {
        state.page -= 1;
        renderGrid(entity, records);
      }, () => {
        state.page += 1;
        renderGrid(entity, records);
      }),
    ]),
  );
  if (focusTarget) document.getElementById(focusTarget)?.focus();
}

function viewLabel(entity, viewId) {
  return SYSTEM_VIEWS[entity]?.find((view) => view.id === viewId)?.label || "Records";
}

function gridFooter(page, previous, next) {
  return node("footer", { className: "grid-footer" }, [
    node("span", { text: `${page.start}-${page.end} of ${page.total}` }),
    node("span", { text: `Page ${page.page} of ${page.pageCount}` }),
    node("div", { className: "pager-buttons" }, [
      node("button", {
        type: "button",
        disabled: !page.hasPrevious,
        "aria-label": "Previous page",
        title: "Previous page",
        on: { click: previous },
      }, [icon("back")]),
      node("button", {
        type: "button",
        disabled: !page.hasNext,
        "aria-label": "Next page",
        title: "Next page",
        on: { click: next },
      }, [icon("back", "ui-icon next")]),
    ]),
  ]);
}

function setGridCommands(entity, state, records, selected) {
  const config = entity === "activities" ? ACTIVITIES_GRID : ENTITY_UI[entity];
  const commands = [];
  if (config.creatable) {
    commands.push(command(entity === "activities" ? "New Task" : "New", "add", () => {
      requestNavigation(entity === "activities" ? "#/tasks/new" : routeHref(entity, "new"));
    }, { primary: true }));
  }
  commands.push(command("Refresh", "refresh", () => {
    renderGrid(entity, records);
    announce(`${config.label} refreshed.`);
  }));
  commands.push("separator");
  const editableSelection = selected.length === 1
    && (entity !== "activities" || selected[0]._entity === "tasks");
  commands.push(command("Edit", "edit", () => {
    if (selected[0]) requestNavigation(gridRecordHref(entity, selected[0]));
  }, { disabled: !editableSelection }));
  commands.push(command("Delete", "delete", () => bulkDelete(entity, state, records, selected), {
    disabled: selected.length === 0,
    danger: true,
  }));
  if (entity === "contacts" || entity === "accounts") {
    commands.push(command("Activate", "state", () => bulkTransition(entity, state, records, selected, "activate"), {
      disabled: !selected.length || selected.some((record) => Number(record.statecode) === 0),
    }));
    commands.push(command("Deactivate", "cancel", () => bulkTransition(entity, state, records, selected, "deactivate"), {
      disabled: !selected.length || selected.some((record) => Number(record.statecode) !== 0),
    }));
  } else if (entity === "incidents") {
    commands.push(command("Resolve Case", "check", () => bulkTransition(entity, state, records, selected, "resolve"), {
      disabled: !selected.length || selected.some((record) => Number(record.statecode) !== 0),
    }));
    commands.push(command("Cancel Case", "cancel", () => bulkTransition(entity, state, records, selected, "cancel"), {
      disabled: !selected.length || selected.some((record) => Number(record.statecode) !== 0),
    }));
    commands.push(command("Reopen", "reopen", () => bulkTransition(entity, state, records, selected, "reopen"), {
      disabled: !selected.length || selected.some((record) => Number(record.statecode) === 0),
    }));
  } else if (entity === "activities") {
    const unavailable = !selected.length || selected.some((record) => record._entity !== "tasks" || Number(record.statecode) !== 0);
    commands.push(command("Mark Complete", "check", () => bulkTransition(entity, state, records, selected, "complete"), {
      disabled: unavailable,
    }));
    commands.push(command("Cancel Task", "cancel", () => bulkTransition(entity, state, records, selected, "cancel"), {
      disabled: unavailable,
    }));
  }
  setCommands(commands);
}

function contactDeletionBlockedMessage(preflight) {
  const names = preflight.blockers.map((blocker) => `“${blocker.contactName}”`).join(", ");
  const connectionCount = new Set(
    preflight.blockers.flatMap((blocker) => blocker.connectionIds),
  ).size;
  return `${names} cannot be deleted because ${connectionCount} Connection ${
    connectionCount === 1 ? "record references" : "records reference"
  } the selected contact${preflight.blockers.length === 1 ? "" : "s"}. Deactivate instead.`;
}

function accountDeletionBlockedMessage(preflight) {
  const names = preflight.blockers.map((blocker) => `“${blocker.accountName}”`).join(", ");
  const emailCount = new Set(
    preflight.blockers.flatMap((blocker) => blocker.emailIds),
  ).size;
  return `${names} cannot be deleted because ${emailCount} Email ${
    emailCount === 1 ? "record references" : "records reference"
  } the selected account${preflight.blockers.length === 1 ? "" : "s"}. Deactivate instead.`;
}

async function bulkDelete(entity, state, records, selected) {
  const routeGuard = currentRouteGuard();
  const confirmed = await confirmAction(
    "Delete selected records",
    `Delete ${selected.length} selected ${selected.length === 1 ? "record" : "records"}?`,
    "Delete",
    true,
  );
  if (confirmed !== true || !routeGuardIsCurrent(routeGuard)) return;
  if (entity === "contacts") {
    await ensureEntities(["contacts", "connections"]);
    if (!routeGuardIsCurrent(routeGuard)) return;
    const preflight = preflightContactDeletion(
      selected.map((record) => record.contactid),
      app.twin.getState("contacts"),
      app.twin.getState("connections"),
    );
    if (!preflight.allowed) {
      await showErrorDialog("Contacts cannot be deleted", contactDeletionBlockedMessage(preflight));
      return;
    }
  }
  if (entity === "accounts") {
    await ensureEntities(["accounts", "emails"]);
    if (!routeGuardIsCurrent(routeGuard)) return;
    const preflight = preflightAccountDeletion(
      selected.map((record) => record.accountid),
      app.twin.getState("accounts"),
      app.twin.getState("emails"),
    );
    if (!preflight.allowed) {
      await showErrorDialog("Accounts cannot be deleted", accountDeletionBlockedMessage(preflight));
      return;
    }
  }
  for (const record of selected) {
    if (!routeGuardIsCurrent(routeGuard)) return;
    const actualEntity = entity === "activities" ? record._entity : entity;
    const config = ENTITY_UI[actualEntity];
    const result = await app.twin.request({
      method: "DELETE",
      path: `/${actualEntity}(${record[config.primaryKey]})`,
      logicalRequestId: requestId(`delete-${actualEntity}`),
      headers: { "If-Match": record["@odata.etag"] },
    });
    if (!routeGuardIsCurrent(routeGuard)) return;
    if (!result.ok) {
      await showErrorDialog("Delete failed", result.body.error.message);
      return;
    }
  }
  if (!routeGuardIsCurrent(routeGuard)) return;
  state.selected.clear();
  const current = await gridRecords(entity);
  if (!routeGuardIsCurrent(routeGuard)) return;
  renderGrid(entity, current);
  announce("Selected records deleted.");
}

async function bulkTransition(entity, state, records, selected, action) {
  const routeGuard = currentRouteGuard();
  const label = {
    activate: "Activate",
    deactivate: "Deactivate",
    complete: "Mark Complete",
    cancel: entity === "incidents" ? "Cancel Case" : "Cancel",
    resolve: "Resolve Case",
    reopen: "Reopen",
  }[action];
  const confirmed = await confirmAction(
    label,
    `${label} for ${selected.length} selected ${selected.length === 1 ? "record" : "records"}?`,
    label,
  );
  if (confirmed !== true || !routeGuardIsCurrent(routeGuard)) return;
  for (const record of selected) {
    if (!routeGuardIsCurrent(routeGuard)) return;
    const actualEntity = entity === "activities" ? record._entity : entity;
    const config = ENTITY_UI[actualEntity];
    const result = await app.twin.request({
      method: "PATCH",
      path: `/${actualEntity}(${record[config.primaryKey]})`,
      logicalRequestId: requestId(`${action}-${actualEntity}`),
      headers: { "If-Match": record["@odata.etag"], Prefer: "return=representation" },
      body: transitionPatch(actualEntity, action, app.twin.now()),
    });
    if (!routeGuardIsCurrent(routeGuard)) return;
    if (!result.ok) {
      await showErrorDialog(`${label} failed`, result.body.error.message);
      return;
    }
  }
  if (!routeGuardIsCurrent(routeGuard)) return;
  state.selected.clear();
  const current = await gridRecords(entity);
  if (!routeGuardIsCurrent(routeGuard)) return;
  renderGrid(entity, current);
  announce(`${label} completed.`);
}

async function renderRecordRoute(route, token) {
  const config = ENTITY_UI[route.entity];
  const routeGuard = captureRouteGuard(token, route);
  showLoading(`Loading ${config.singular}`);
  await ensureEntity(route.entity);
  if (!routeGuardIsCurrent(routeGuard)) return;
  if (route.id === "new") {
    if (!config.creatable) throw new Error(`New ${config.singular.toLowerCase()} records are not supported.`);
    renderRecordForm(route.entity, null, route.initialTab);
    return;
  }
  const result = await app.twin.request({
    method: "GET",
    path: `/${route.entity}(${route.id})`,
    logicalRequestId: requestId(`open-${route.entity}`),
    clientId: "customer-service-hub",
  });
  if (!routeGuardIsCurrent(routeGuard)) return;
  if (!result.ok) throw new Error(result.body.error.message);
  renderRecordForm(route.entity, result.body, route.initialTab);
}

function recordTitle(config, record) {
  return record ? record[config.nameField] || config.singular : `New ${config.singular}`;
}

function editableControl(descriptor, record) {
  const current = record?.[descriptor.key];
  let control;
  if (descriptor.type === "textarea") {
    control = node("textarea", { name: descriptor.key, text: current ?? "", rows: "4" });
  } else if (descriptor.type === "choice") {
    const selectedValue = current ?? descriptor.defaultValue ?? descriptor.choices?.[0]?.[0];
    control = node("select", { name: descriptor.key }, (descriptor.choices || []).map(([value, label]) =>
      node("option", { value, text: label, selected: String(value) === String(selectedValue) })));
  } else {
    let type = descriptor.type;
    let value = current ?? "";
    if (type === "datetime") {
      type = "datetime-local";
      value = current ? formatUtcDateTimeLocal(current) : "";
    }
    control = node("input", {
      name: descriptor.key,
      type: ["email", "url", "number", "datetime-local"].includes(type) ? type : "text",
      value,
      step: type === "datetime-local" ? "0.001" : null,
    });
  }
  control.id = `field-${descriptor.key}`;
  if (descriptor.required) {
    control.required = true;
    control.setAttribute("aria-required", "true");
  }
  return control;
}

function readOnlyField(descriptor, record, entity) {
  const value = record?.[descriptor.key];
  if (descriptor.type === "url" && value) return externalLink(value);
  return node("span", {
    className: "field-value",
    text: formattedValue(value, descriptor, entity, record),
  });
}

function formField(descriptor, record, entity, editable) {
  const label = node("label", { for: `field-${descriptor.key}` }, [
    node("span", { text: descriptor.label }),
    descriptor.required ? node("span", { className: "required-marker", "aria-hidden": "true", text: "*" }) : null,
  ]);
  return node("div", { className: `form-field${descriptor.full ? " full" : ""}` }, [
    label,
    editable && descriptor.editable
      ? editableControl(descriptor, record)
      : readOnlyField(descriptor, record, entity),
  ]);
}

function formSection(section, record, entity, editable) {
  return node("section", { className: "form-section" }, [
    node("h2", { text: section.title }),
    node("div", { className: "form-grid" }, section.fields.map((descriptor) =>
      formField(descriptor, record, entity, editable))),
  ]);
}

function recordNavigation(entity, record) {
  const config = ENTITY_UI[entity];
  const backHref = entity === "emails" || entity === "tasks" ? "#/activities" : routeHref(entity);
  if (!record) {
    return node("nav", { className: "record-navigation", "aria-label": "Record navigation" }, [
      node("a", { href: backHref }, [icon("back"), node("span", { text: `Back to ${entity === "incidents" ? "Cases" : config.label}` })]),
    ]);
  }
  const records = app.twin.getState(entity);
  const index = records.findIndex((item) => item[config.primaryKey] === record[config.primaryKey]);
  const previous = index > 0 ? records[index - 1] : null;
  const next = index >= 0 && index < records.length - 1 ? records[index + 1] : null;
  return node("nav", { className: "record-navigation", "aria-label": "Record navigation" }, [
    node("a", { href: backHref }, [icon("back"), node("span", { text: "Back" })]),
    previous ? node("a", {
      href: routeHref(entity, previous[config.primaryKey]),
      title: `Previous ${config.singular.toLowerCase()}`,
    }, [icon("back"), node("span", { className: "sr-only", text: "Previous record" })]) : null,
    next ? node("a", {
      href: routeHref(entity, next[config.primaryKey]),
      title: `Next ${config.singular.toLowerCase()}`,
    }, [icon("back", "ui-icon next"), node("span", { className: "sr-only", text: "Next record" })]) : null,
  ]);
}

function buildBusinessProcess(record, editable) {
  const key = record?.incidentid || "new";
  const stages = ["Identify", "Research", "Resolve"];
  const active = Math.min(2, app.bpfStages.get(key) || 0);
  return node("section", { className: "business-process", "aria-label": "Case process" }, [
    node("span", { className: "process-label", text: "Case process" }),
    node("ol", {}, stages.map((stage, index) => node("li", { className: index < active ? "complete" : index === active ? "active" : "" }, [
      node("button", {
        type: "button",
        disabled: !editable,
        "aria-current": index === active ? "step" : null,
        on: {
          click: () => {
            app.bpfStages.set(key, index);
            document.querySelector(".business-process")?.replaceWith(buildBusinessProcess(record, editable));
            announce(`${stage} stage selected.`);
          },
        },
      }, [
        node("span", { className: "stage-marker", text: String(index + 1) }),
        node("span", { text: stage }),
      ]),
    ]))),
  ]);
}

function renderRecordForm(entity, record, initialTab = null) {
  const config = ENTITY_UI[entity];
  const creating = !record;
  const editable = isRecordEditable(entity, record, config.editable);
  const title = recordTitle(config, record);
  let baseline = {};
  const markFormDirty = (event) => {
    if (event.target instanceof HTMLElement && event.target.getAttribute("name")) {
      setDirty(!editableSnapshotsEqual(baseline, formPayload(form, entity)));
    }
  };
  const form = node("form", {
    id: "record-form",
    novalidate: "novalidate",
    on: {
      submit: (event) => {
        event.preventDefault();
        saveRecord(entity, record, event.currentTarget);
      },
      input: markFormDirty,
      change: markFormDirty,
    },
  });
  const summaryPanel = node("div", {
    id: "form-panel-summary", className: "form-panel", role: "tabpanel", "aria-labelledby": "tab-summary",
  },
    config.sections.filter((section) => section.tab === "summary").map((section) =>
      formSection(section, record, entity, editable)));
  const detailsPanel = node("div", {
    id: "form-panel-details",
    className: "form-panel",
    role: "tabpanel",
    "aria-labelledby": "tab-details",
    hidden: true,
  }, config.sections.filter((section) => section.tab === "details").map((section) =>
    formSection(section, record, entity, editable)));
  const relatedPanel = node("div", {
    id: "form-panel-related",
    className: "form-panel",
    role: "tabpanel",
    "aria-labelledby": "tab-related",
    hidden: true,
  });
  form.append(summaryPanel, detailsPanel, relatedPanel);
  baseline = normalizeEditableSnapshot(formPayload(form, entity));

  const tabs = ["Summary", "Details", "Related"].map((label) => {
    const tab = label.toLowerCase();
    return node("button", {
      type: "button",
      className: "form-tab",
      role: "tab",
      id: `tab-${tab}`,
      "aria-controls": `form-panel-${tab}`,
      "aria-selected": "false",
      disabled: tab === "related" && creating,
      on: {
        click: () => selectFormTab(tab, form, entity, record),
        keydown: (event) => handleFormTabKeydown(event, form, entity, record),
      },
      text: label,
    });
  });
  const keyFields = config.headerFields.slice(0, 4).map((descriptor) => node("div", { className: "header-field" }, [
    node("span", { text: descriptor.label }),
    valueNode(record || {}, descriptor, entity),
  ]));
  setRecordCommands(entity, record, form);
  setDirty(false);
  app.activeForm = { entity, record, form, baseline };
  replace(ui.root,
    recordNavigation(entity, record),
    node("article", { className: "record-shell" }, [
      node("header", { className: "record-header" }, [
        node("div", { className: "record-symbol", "aria-hidden": "true" }, [icon(entity === "incidents" ? "state" : "edit")]),
        node("div", { className: "record-title" }, [
          node("span", { text: creating ? `New ${config.singular}` : config.singular }),
          node("h1", { text: title }),
        ]),
        node("div", { className: "record-header-fields" }, keyFields),
      ]),
      entity === "incidents" ? buildBusinessProcess(record, editable) : null,
      node("div", { className: "form-tabs", role: "tablist", "aria-label": `${config.singular} form tabs` }, tabs),
      form,
    ]),
  );
  selectFormTab(initialTab || "summary", form, entity, record);
}

function selectFormTab(tab, form, entity, record) {
  const buttons = [...form.closest(".record-shell").querySelectorAll(".form-tab")];
  const requested = buttons.find((button) => button.id === `tab-${tab}` && !button.disabled);
  const selectedButton = requested || buttons.find((button) => !button.disabled);
  const selectedTab = selectedButton?.id.replace(/^tab-/, "") || "summary";
  for (const button of buttons) {
    const selected = button === selectedButton;
    button.classList.toggle("active", selected);
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  }
  for (const panel of form.querySelectorAll(".form-panel")) {
    panel.hidden = panel.id !== `form-panel-${selectedTab}`;
  }
  if (selectedTab === "related" && record) {
    loadRelatedPanel(entity, record, form.querySelector("#form-panel-related"));
  }
  return selectedButton;
}

function handleFormTabKeydown(event, form, entity, record) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  const tabs = [...form.closest(".record-shell").querySelectorAll(".form-tab")];
  const nextIndex = nextRovingTabIndex(tabs, tabs.indexOf(event.currentTarget), event.key);
  if (nextIndex < 0) return;
  event.preventDefault();
  const nextTab = tabs[nextIndex];
  selectFormTab(nextTab.id.replace(/^tab-/, ""), form, entity, record)?.focus();
}

function setRecordCommands(entity, record, form) {
  const config = ENTITY_UI[entity];
  const actions = new Set(recordCommandActions(entity, record, {
    editable: config.editable,
    deletable: config.deletable,
    hasSafeSource: Boolean(record?.new_url && safeHttpUrl(record.new_url)),
  }));
  const commands = [];
  if (actions.has("save")) {
    commands.push(command("Save", "save", () => form.requestSubmit(), { primary: true }));
    commands.push(command("Save & Close", "check", async () => {
      const saved = await saveRecord(entity, record, form, { render: false });
      if (saved) requestNavigation(entity === "tasks" ? "#/activities" : routeHref(entity));
    }));
    commands.push("separator");
  }
  if (actions.has("activate") || actions.has("deactivate")) {
    const action = actions.has("activate") ? "activate" : "deactivate";
    commands.push(command(action === "activate" ? "Activate" : "Deactivate", action === "activate" ? "state" : "cancel",
      () => transitionRecord(entity, action)));
  }
  if (actions.has("complete")) {
    commands.push(command("Mark Complete", "check", () => transitionRecord(entity, "complete")));
    commands.push(command("Cancel", "cancel", () => transitionRecord(entity, "cancel")));
  }
  if (actions.has("resolve")) {
    commands.push(command("Resolve Case", "check", () => transitionRecord(entity, "resolve")));
    commands.push(command("Cancel Case", "cancel", () => transitionRecord(entity, "cancel")));
  }
  if (actions.has("reopen")) {
    commands.push(command("Reopen", "reopen", () => transitionRecord(entity, "reopen")));
  }
  if (actions.has("open-source")) {
    commands.push(command("Open source", "external", () => openExternal(record.new_url)));
  }
  if (actions.has("delete")) {
    commands.push(command("Delete", "delete", () => deleteCurrentRecord(entity), { danger: true }));
  }
  if (actions.has("refresh")) {
    commands.push(command("Refresh", "refresh", () => refreshCurrentRecord(entity)));
  }
  commands.push(command("Back", "back", () => requestNavigation(
    entity === "emails" || entity === "tasks" ? "#/activities" : routeHref(entity),
  )));
  setCommands(commands);
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

async function saveRecord(entity, record, form, options = {}) {
  const routeGuard = currentRouteGuard();
  const config = ENTITY_UI[entity];
  if (!isRecordEditable(entity, record, config.editable) || !form.reportValidity()) return false;
  if (!routeGuardIsCurrent(routeGuard)) return false;
  const creating = !record;
  const result = await app.twin.request({
    method: creating ? "POST" : "PATCH",
    path: creating ? `/${entity}` : `/${entity}(${record[config.primaryKey]})`,
    logicalRequestId: requestId(`save-${entity}`),
    clientId: "customer-service-form",
    headers: {
      Prefer: "return=representation",
      ...(creating ? {} : { "If-Match": record["@odata.etag"] }),
    },
    body: formPayload(form, entity),
  });
  if (!routeGuardIsCurrent(routeGuard)) return false;
  if (!result.ok) {
    const message = result.status === 412
      ? "This record changed after the form was opened. Refresh the record, review the latest values, and save again."
      : result.body.error.message;
    await showErrorDialog("Save failed", message);
    return false;
  }
  setDirty(false);
  app.activeForm = {
    entity,
    record: result.body,
    form,
    baseline: normalizeEditableSnapshot(formPayload(form, entity)),
  };
  announce(`${config.singular} saved.`);
  if (options.render === false) return result.body;
  if (creating) {
    await requestNavigation(routeHref(entity, result.body[config.primaryKey]));
  } else {
    renderRecordForm(entity, result.body);
  }
  return result.body;
}

async function refreshCurrentRecord(entity) {
  const routeGuard = currentRouteGuard();
  if (!(await resolveDirtyState())) return;
  if (!routeGuardIsCurrent(routeGuard)) return;
  const current = app.activeForm?.record;
  if (!current) return;
  const config = ENTITY_UI[entity];
  const result = await app.twin.request({
    method: "GET",
    path: `/${entity}(${current[config.primaryKey]})`,
    logicalRequestId: requestId(`refresh-${entity}`),
  });
  if (!routeGuardIsCurrent(routeGuard)) return;
  if (!result.ok) {
    await showErrorDialog("Refresh failed", result.body.error.message);
    return;
  }
  renderRecordForm(entity, result.body);
  announce(`${config.singular} refreshed.`);
}

async function transitionRecord(entity, action) {
  const routeGuard = currentRouteGuard();
  if (!(await resolveDirtyState())) return;
  if (!routeGuardIsCurrent(routeGuard)) return;
  const record = app.activeForm?.record;
  if (!record) return;
  const config = ENTITY_UI[entity];
  const labels = {
    activate: "Activate",
    deactivate: "Deactivate",
    complete: "Mark Complete",
    cancel: entity === "incidents" ? "Cancel Case" : "Cancel Task",
    resolve: "Resolve Case",
    reopen: "Reopen Case",
  };
  const label = labels[action];
  const confirmed = await confirmAction(
    label,
    `${label} for “${recordTitle(config, record)}”?`,
    label,
    action === "cancel",
  );
  if (confirmed !== true || !routeGuardIsCurrent(routeGuard)) return;
  const result = await app.twin.request({
    method: "PATCH",
    path: `/${entity}(${record[config.primaryKey]})`,
    logicalRequestId: requestId(`${action}-${entity}`),
    headers: { "If-Match": record["@odata.etag"], Prefer: "return=representation" },
    body: transitionPatch(entity, action, app.twin.now()),
  });
  if (!routeGuardIsCurrent(routeGuard)) return;
  if (!result.ok) {
    await showErrorDialog(`${label} failed`, result.body.error.message);
    return;
  }
  renderRecordForm(entity, result.body);
  announce(`${label} completed.`);
}

async function deleteCurrentRecord(entity) {
  const routeGuard = currentRouteGuard();
  if (!(await resolveDirtyState())) return;
  if (!routeGuardIsCurrent(routeGuard)) return;
  const record = app.activeForm?.record;
  if (!record) return;
  const config = ENTITY_UI[entity];
  const confirmed = await confirmAction(
    `Delete ${config.singular.toLowerCase()}`,
    `Delete “${recordTitle(config, record)}”? This action cannot be undone.`,
    "Delete",
    true,
  );
  if (confirmed !== true || !routeGuardIsCurrent(routeGuard)) return;
  if (entity === "contacts") {
    await ensureEntities(["contacts", "connections"]);
    if (!routeGuardIsCurrent(routeGuard)) return;
    const preflight = preflightContactDeletion(
      [record.contactid],
      app.twin.getState("contacts"),
      app.twin.getState("connections"),
    );
    if (!preflight.allowed) {
      await showErrorDialog("Contact cannot be deleted", contactDeletionBlockedMessage(preflight));
      return;
    }
  }
  if (entity === "accounts") {
    await ensureEntities(["accounts", "emails"]);
    if (!routeGuardIsCurrent(routeGuard)) return;
    const preflight = preflightAccountDeletion(
      [record.accountid],
      app.twin.getState("accounts"),
      app.twin.getState("emails"),
    );
    if (!preflight.allowed) {
      await showErrorDialog("Account cannot be deleted", accountDeletionBlockedMessage(preflight));
      return;
    }
  }
  if (!routeGuardIsCurrent(routeGuard)) return;
  const result = await app.twin.request({
    method: "DELETE",
    path: `/${entity}(${record[config.primaryKey]})`,
    logicalRequestId: requestId(`delete-${entity}`),
    headers: { "If-Match": record["@odata.etag"] },
  });
  if (!routeGuardIsCurrent(routeGuard)) return;
  if (!result.ok) {
    await showErrorDialog("Delete failed", result.body.error.message);
    return;
  }
  setDirty(false);
  announce(`${config.singular} deleted.`);
  await requestNavigation(entity === "emails" || entity === "tasks" ? "#/activities" : routeHref(entity));
}

async function loadRelatedPanel(entity, record, container) {
  const routeGuard = currentRouteGuard();
  replace(container, node("div", { className: "loading-state compact", role: "status" }, [
    node("span", { className: "spinner", "aria-hidden": "true" }),
    node("span", { text: "Loading related records" }),
  ]));
  try {
    if (entity === "contacts") {
      await ensureEntities(["emails", "connections", "contacts"]);
      if (!routeGuardIsCurrent(routeGuard)) return;
      renderContactRelated(record, container);
      return;
    }
    if (entity === "accounts") {
      await ensureEntity("emails");
      if (!routeGuardIsCurrent(routeGuard)) return;
      const emails = relatedEmailsForAccount(app.twin.getState("emails"), record.accountid);
      replace(container, relatedEmailSection(emails));
      return;
    }
    replace(container, honestRelatedEmpty());
  } catch (error) {
    if (!routeGuardIsCurrent(routeGuard)) return;
    replace(container, node("section", { className: "inline-error", role: "alert" }, [
      node("h2", { text: "Related records could not be loaded" }),
      node("p", { text: error.message }),
    ]));
  }
}

function renderContactRelated(record, container) {
  const connections = relatedConnectionsForContact(
    app.twin.getState("connections"),
    record.contactid,
    app.twin.getState("contacts"),
  ).map((connection) => {
    return {
      ...connection,
      _status: Number(connection.statecode) === 0 ? "Active" : "Inactive",
    };
  });
  const emails = relatedEmailsForContact(app.twin.getState("emails"), record);
  const state = associatedState(record.contactid);
  const viewed = applySystemView(connections, "connections", state.view);
  const searched = searchRows(viewed, ["_relatedName", "_relationship", "_status"], state.search);
  const sorted = stableSortRows(searched, state.sort, state.direction, "connectionid");
  const page = paginateRows(sorted, state.page, PAGE_SIZE);
  state.page = page.page;
  const pageKeys = page.rows.map((connection) => connection.connectionid);
  const allPageSelected = pageKeys.length > 0 && pageKeys.every((key) => state.selected.has(key));
  const selected = connections.filter((connection) => state.selected.has(connection.connectionid));
  const viewSelector = node("select", {
    id: "connection-view",
    "aria-label": "Connections system view",
    on: {
      change: (event) => {
        state.view = event.target.value;
        state.page = 1;
        state.selected.clear();
        renderContactRelated(record, container);
      },
    },
  }, SYSTEM_VIEWS.connections.map((view) =>
    node("option", { value: view.id, text: view.label, selected: view.id === state.view })));
  const searchInput = node("input", {
    id: "connection-search",
    type: "search",
    value: state.search,
    placeholder: "Search this view",
    "aria-label": "Search this view",
    on: {
      keydown: (event) => {
        if (event.key === "Enter") event.preventDefault();
      },
      input: (event) => {
        state.search = event.target.value;
        state.page = 1;
        state.selected.clear();
        renderContactRelated(record, container);
        const next = document.querySelector("#connection-search");
        next?.focus();
        next?.setSelectionRange(state.search.length, state.search.length);
      },
    },
  });
  const sortHeader = (key, label) => {
    const active = state.sort === key;
    return node("th", {
      scope: "col",
      "aria-sort": active ? (state.direction === "asc" ? "ascending" : "descending") : "none",
    }, [
      node("button", {
        type: "button",
        className: "sort-button",
        on: {
          click: () => {
            if (active) state.direction = state.direction === "asc" ? "desc" : "asc";
            else {
              state.sort = key;
              state.direction = "asc";
            }
            state.page = 1;
            renderContactRelated(record, container);
          },
        },
      }, [
        node("span", { text: label }),
        active ? icon("back", `sort-icon ${state.direction}`) : null,
      ]),
    ]);
  };
  const rows = page.rows.map((connection) => {
    return node("tr", {}, [
      node("td", { className: "selection-column" }, [
        node("input", {
          type: "checkbox",
          checked: state.selected.has(connection.connectionid),
          "aria-label": `Select connection with ${connection._relatedName}`,
          on: {
            change: (event) => {
              state.selected = updateSelection(state.selected, [connection.connectionid], event.target.checked);
              renderContactRelated(record, container);
            },
          },
        }),
      ]),
      node("td", { dataset: { label: "Related Contact" } }, [
        node("a", { className: "record-link", href: routeHref("contacts", connection._relatedId), text: connection._relatedName }),
      ]),
      node("td", { dataset: { label: "Relationship" }, text: connection._relationship }),
      node("td", { dataset: { label: "Status" } }, [
        node("span", { className: `status-badge ${statusClass(connection._status)}`, text: connection._status }),
      ]),
    ]);
  });
  replace(container,
    node("section", { className: "related-section" }, [
      node("div", { className: "related-heading" }, [
        node("h2", { text: "Connections" }),
      ]),
      node("div", { className: "associated-toolbar" }, [
        node("div", { className: "view-choice" }, [
          node("label", { for: "connection-view", text: "View" }),
          viewSelector,
        ]),
        node("div", { className: "view-search" }, [icon("search"), searchInput]),
        node("button", {
          type: "button",
          className: "secondary-button",
          disabled: selected.length !== 1,
          text: "Open related contact",
          on: { click: () => selected[0] && requestNavigation(routeHref("contacts", selected[0]._relatedId)) },
        }),
        node("button", {
          type: "button",
          className: "secondary-button",
          text: "Refresh",
          on: {
            click: () => {
              renderContactRelated(record, container);
              announce("Connections refreshed.");
            },
          },
        }),
      ]),
      node("div", { className: "grid-surface related-grid" }, [
        node("div", { className: "grid-scroll" }, [
          node("table", { className: "data-grid", "aria-label": "Contact connections" }, [
            node("thead", {}, [node("tr", {}, [
              node("th", { scope: "col", className: "selection-column" }, [
                node("input", {
                  type: "checkbox",
                  checked: allPageSelected,
                  "aria-label": allPageSelected ? "Clear page selection" : "Select page",
                  on: {
                    change: (event) => {
                      state.selected = updateSelection(state.selected, pageKeys, event.target.checked);
                      renderContactRelated(record, container);
                    },
                  },
                }),
              ]),
              sortHeader("_relatedName", "Related Contact"),
              sortHeader("_relationship", "Relationship"),
              sortHeader("_status", "Status"),
            ])]),
            rows.length
              ? node("tbody", {}, rows)
              : node("tbody", {}, [node("tr", {}, [node("td", {
                colspan: "4", className: "grid-empty", text: "No connections are available in this view.",
              })])]),
          ]),
        ]),
        gridFooter(page, () => {
          state.page -= 1;
          renderContactRelated(record, container);
        }, () => {
          state.page += 1;
          renderContactRelated(record, container);
        }),
      ]),
    ]),
    relatedEmailSection(emails),
  );
}

function associatedState(contactId) {
  if (!app.associatedGrid.has(contactId)) {
    app.associatedGrid.set(contactId, {
      view: "active",
      search: "",
      sort: "_relatedName",
      direction: "asc",
      page: 1,
      selected: new Set(),
    });
  }
  return app.associatedGrid.get(contactId);
}

function relatedEmailSection(emails) {
  return node("section", { className: "related-section" }, [
    node("h2", { text: "Email Activities" }),
    emails.length
      ? node("ol", { className: "timeline" }, emails.map((email) => node("li", {}, [
        node("span", { className: "timeline-marker", "aria-hidden": "true" }),
        node("div", {}, [
          node("a", { href: routeHref("emails", email.activityid), text: email.subject || "" }),
          node("span", { text: `${email.sender || ""}${email.new_channel ? ` · ${email.new_channel}` : ""}` }),
          node("time", { datetime: email.createdon || "", text: formatUtcDate(email.createdon) }),
        ]),
      ])))
      : node("div", { className: "component-empty" }, [
        icon("search", "empty-icon"),
        node("p", { text: "There are no related email activities." }),
      ]),
  ]);
}

function honestRelatedEmpty() {
  return node("section", { className: "related-section component-empty" }, [
    icon("search", "empty-icon"),
    node("h2", { text: "Related records" }),
    node("p", { text: "There are no related activities for this record." }),
  ]);
}

function renderEmptyCollection(kind) {
  const definitions = {
    queues: {
      title: "Queues",
      views: [["active", "Active Queues"], ["all", "All Queues"]],
      singular: "queue",
      message: "No queues are available.",
    },
    "knowledge-articles": {
      title: "Knowledge Articles",
      views: [["active", "Active Knowledge Articles"], ["all", "All Knowledge Articles"]],
      singular: "knowledge article",
      message: "No knowledge articles are available.",
    },
  };
  const definition = definitions[kind];
  const searchKey = `empty-${kind}`;
  if (!app.grid.has(searchKey)) {
    app.grid.set(searchKey, { search: "", view: "active", sort: "name", direction: "asc" });
  }
  const state = app.grid.get(searchKey);
  setCommands([command("Refresh", "refresh", () => {
    renderEmptyCollection(kind);
    announce(`${definition.title} refreshed.`);
  })]);
  const sortHeader = (key, label) => {
    const active = state.sort === key;
    return node("th", {
      scope: "col",
      "aria-sort": active ? (state.direction === "asc" ? "ascending" : "descending") : "none",
    }, [
      node("button", {
        type: "button",
        className: "sort-button",
        on: {
          click: () => {
            if (active) state.direction = state.direction === "asc" ? "desc" : "asc";
            else {
              state.sort = key;
              state.direction = "asc";
            }
            renderEmptyCollection(kind);
          },
        },
      }, [
        node("span", { text: label }),
        active ? icon("back", `sort-icon ${state.direction}`) : null,
      ]),
    ]);
  };
  const searchInput = node("input", {
    id: "view-search",
    type: "search",
    value: state.search,
    placeholder: "Search this view",
    "aria-label": "Search this view",
    on: {
      input: (event) => {
        state.search = event.target.value;
        renderEmptyCollection(kind);
        const next = document.querySelector("#view-search");
        next?.focus();
        next?.setSelectionRange(event.target.value.length, event.target.value.length);
      },
    },
  });
  replace(ui.root,
    pageHeading(definition.title),
    node("div", { className: "view-toolbar" }, [
      node("div", { className: "view-choice" }, [
        node("label", { for: "empty-view", text: "View" }),
        node("select", {
          id: "empty-view",
          "aria-label": `${definition.title} system view`,
          on: {
            change: (event) => {
              state.view = event.target.value;
              renderEmptyCollection(kind);
            },
          },
        }, definition.views.map(([value, label]) =>
          node("option", { text: label, value, selected: state.view === value }))),
      ]),
      node("div", { className: "view-search" }, [icon("search"), searchInput]),
    ]),
    node("div", { className: "grid-surface" }, [
      node("table", { className: "data-grid empty-collection-grid", "aria-label": definition.title }, [
        node("thead", {}, [node("tr", {}, [
          sortHeader("name", "Name"),
          sortHeader("status", "Status"),
          sortHeader("modifiedon", "Modified On"),
        ])]),
        node("tbody", {}, [node("tr", {}, [
          node("td", { colspan: "3", className: "grid-empty" }, [
            icon("search", "empty-icon"),
            node("strong", { text: state.search ? `No ${definition.singular}s match this search.` : definition.message }),
          ]),
        ])]),
      ]),
      gridFooter(paginateRows([], 1), () => {}, () => {}),
    ]),
  );
}

function renderKnowledgeSearch(query) {
  setCommands([]);
  const input = node("input", {
    id: "knowledge-query",
    type: "search",
    value: query,
    placeholder: "Search knowledge",
    "aria-label": "Search knowledge",
  });
  const form = node("form", {
    className: "knowledge-search-form",
    on: {
      submit: (event) => {
        event.preventDefault();
        requestNavigation(`#/knowledge-search?q=${encodeURIComponent(input.value.trim())}`);
      },
    },
  }, [
    icon("search"),
    input,
    node("button", { className: "primary-button", type: "submit", text: "Search" }),
  ]);
  replace(ui.root,
    pageHeading("Knowledge Search", "Find published knowledge articles."),
    form,
    query
      ? node("section", { className: "large-empty-state" }, [
        icon("search", "state-icon"),
        node("h2", { text: "No results found" }),
        node("p", { text: `No knowledge articles match “${query}”.` }),
      ])
      : node("section", { className: "large-empty-state" }, [
        icon("search", "state-icon"),
        node("h2", { text: "Search knowledge" }),
        node("p", { text: "Enter words or a phrase to search published articles." }),
      ]),
  );
}

async function renderGlobalSearch(query, expectedToken = app.navigationToken) {
  const routeGuard = captureRouteGuard(expectedToken, app.currentRoute);
  setCommands([]);
  if (!query.trim()) {
    replace(ui.root,
      pageHeading("Search"),
      node("section", { className: "large-empty-state" }, [
        icon("search", "state-icon"),
        node("h2", { text: "Search Dynamics 365" }),
        node("p", { text: "Enter a name, subject, email, topic, or case title in the header search box." }),
      ]),
    );
    return;
  }
  showLoading("Searching");
  await ensureEntities(["contacts", "accounts", "incidents", "emails", "tasks"]);
  if (!routeGuardIsCurrent(routeGuard)) return;
  const activities = combineActivities(app.twin.getState("emails"), app.twin.getState("tasks"), app.twin.now());
  const groups = [
    {
      title: "Contacts", entity: "contacts", records: app.twin.getState("contacts"),
      fields: ["fullname", "emailaddress1", "jobtitle", "description"], key: "contactid", name: "fullname",
    },
    {
      title: "Accounts", entity: "accounts", records: app.twin.getState("accounts"),
      fields: ["name", "description", "new_slug"], key: "accountid", name: "name",
    },
    {
      title: "Cases", entity: "incidents", records: app.twin.getState("incidents"),
      fields: ["title", "description", "new_category"], key: "incidentid", name: "title",
    },
    {
      title: "Activities", entity: "activities", records: activities,
      fields: ["subject", "description", "_regarding", "sender"], key: "_id", name: "subject",
    },
  ];
  const resultGroups = groups.map((group) => ({
    ...group,
    matches: searchRows(group.records, group.fields, query).slice(0, 25),
  })).filter((group) => group.matches.length);
  replace(ui.root,
    pageHeading("Search", `Results for “${query}”`),
    resultGroups.length
      ? node("div", { className: "search-results" }, resultGroups.map((group) => node("section", {}, [
        node("h2", { text: `${group.title} (${group.matches.length})` }),
        node("ul", {}, group.matches.map((record) => node("li", {}, [
          node("a", {
            href: group.entity === "activities"
              ? routeHref(record._entity, record._id)
              : routeHref(group.entity, record[group.key]),
            text: record[group.name] || "",
          }),
          node("span", {
            text: group.entity === "activities"
              ? `${record._activityType} · ${record._status}`
              : formattedValue(record.statecode, field("statecode", "", { type: "state" }), group.entity, record),
          }),
        ]))),
      ])))
      : node("section", { className: "large-empty-state" }, [
        icon("search", "state-icon"),
        node("h2", { text: "No results found" }),
        node("p", { text: "Try different words or check the spelling." }),
      ]),
  );
}

function simulationDisclosure() {
  return node("aside", { className: "simulation-disclosure" }, [
    node("strong", { text: "Simulation boundary" }),
    node("p", {
      text: "Generated OData files are read-only. Changes, faults, retries, ETags, replay, and virtual UTC time run only in memory in this browser tab; no Dataverse service receives them.",
    }),
  ]);
}

function renderSimulationSettings() {
  setCommands([
    command("Run selected", "check", () => document.querySelector("#scenario-run")?.click(), { primary: true }),
    command("Reset", "refresh", resetRuntime),
    command("Advance 1 minute", "time", () => advanceClock(60_000)),
    command("Advance 1 hour", "time", () => advanceClock(3_600_000)),
    command("Replay", "reopen", replayCurrentRun),
  ]);
  const selectedFromRoute = app.currentRoute?.scenario;
  const scenarioSelect = node("select", { id: "scenario-select", "aria-label": "Built-in scenario" },
    BUILT_IN_SCENARIOS.map((scenario) => node("option", {
      value: scenario.id,
      text: `${scenario.label} — ${scenario.description}`,
      selected: scenario.id === selectedFromRoute,
    })));
  replace(ui.root,
    pageHeading("Simulation settings", "Deterministic runtime controls and verification"),
    simulationDisclosure(),
    node("div", { className: "management-layout" }, [
      node("div", { className: "management-stack" }, [
        node("article", { className: "management-panel" }, [
          node("h2", { text: "Built-in scenarios" }),
          node("label", { for: "scenario-select", text: "Scenario" }),
          scenarioSelect,
          node("div", { className: "button-row" }, [
            node("button", {
              id: "scenario-run", className: "primary-button", type: "button", text: "Run scenario",
              on: { click: () => runScenario(scenarioSelect.value) },
            }),
            node("button", { className: "secondary-button", type: "button", text: "Run all", on: { click: runAllScenarios } }),
          ]),
        ]),
        node("article", { className: "management-panel" }, [
          node("h2", { text: "Virtual UTC clock" }),
          node("output", { className: "clock-output", text: app.twin.now() }),
          node("div", { className: "button-row" }, [
            node("button", { className: "secondary-button", type: "button", text: "Add 1 minute", on: { click: () => advanceClock(60_000) } }),
            node("button", { className: "secondary-button", type: "button", text: "Add 1 hour", on: { click: () => advanceClock(3_600_000) } }),
            node("button", { className: "secondary-button", type: "button", text: "Add 1 day", on: { click: () => advanceClock(86_400_000) } }),
          ]),
        ]),
        buildCustomRequestPanel(),
      ]),
      node("div", { className: "management-stack" }, [
        buildScenarioResults(),
        buildTracePanel(),
      ]),
    ]),
  );
}

function buildCustomRequestPanel() {
  const method = node("select", { id: "request-method" },
    ["GET", "POST", "PATCH", "DELETE"].map((value) => node("option", { value, text: value })));
  const fault = node("select", { id: "request-fault" }, [
    ["none", "No fault"], ["network", "Network error"], ["503", "HTTP 503"],
    ["429", "HTTP 429 with Retry-After"], ["malformed", "Malformed response"],
    ["delay", "Virtual 750 ms delay"], ["timeout", "Virtual timeout"],
    ["postCommitLoss", "Post-commit response loss"],
  ].map(([value, label]) => node("option", { value, text: label })));
  return node("article", { className: "management-panel" }, [
    node("h2", { text: "Request and fault console" }),
    node("div", { className: "management-fields" }, [
      node("label", { for: "request-method", text: "Method" }), method,
      node("label", { for: "request-path", text: "D365 path" }),
      node("input", { id: "request-path", value: "/tasks", spellcheck: "false" }),
      node("label", { for: "request-id", text: "Logical request ID" }),
      node("input", { id: "request-id", value: `console-${String(app.requestCounter + 1).padStart(5, "0")}` }),
      node("label", { for: "request-fault", text: "Injected fault" }), fault,
      node("label", { for: "request-body", text: "Raw JSON body" }),
      node("textarea", {
        id: "request-body",
        rows: "5",
        spellcheck: "false",
        text: '{"subject":"Console probe","scheduledend":"2026-07-01T10:00:00.000Z"}',
      }),
      node("label", { className: "checkbox-label" }, [
        node("input", { id: "request-retry", type: "checkbox", checked: true }),
        node("span", { text: "Use bounded retry" }),
      ]),
      node("button", { className: "primary-button", type: "button", text: "Send request", on: { click: sendManualRequest } }),
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
  const routeGuard = currentRouteGuard();
  const method = document.querySelector("#request-method").value;
  const path = document.querySelector("#request-path").value;
  const logicalRequestId = document.querySelector("#request-id").value || requestId("console");
  const body = document.querySelector("#request-body").value;
  const fault = selectedFault(document.querySelector("#request-fault").value);
  const retry = document.querySelector("#request-retry").checked;
  const spec = {
    method,
    path,
    logicalRequestId,
    clientId: "service-management",
    headers: { Prefer: "return=representation" },
    ...(method === "GET" || method === "DELETE" ? {} : { body }),
  };
  try {
    const target = parsePath(path);
    if (!target.error && ENTITY_DEFINITIONS[target.entity]) {
      if (method === "DELETE" && target.entity === "contacts" && target.id) {
        await ensureEntities(["contacts", "connections"]);
      } else if (method === "DELETE" && target.entity === "accounts" && target.id) {
        await ensureEntities(["accounts", "emails"]);
      } else {
        await ensureEntity(target.entity);
      }
    }
    if (!routeGuardIsCurrent(routeGuard)) return;
    if (method === "DELETE" && target.entity === "contacts" && target.id) {
      const preflight = preflightContactDeletion(
        [target.id],
        app.twin.getState("contacts"),
        app.twin.getState("connections"),
      );
      if (!preflight.allowed) {
        await showErrorDialog("Contact cannot be deleted", contactDeletionBlockedMessage(preflight));
        return;
      }
    }
    if (method === "DELETE" && target.entity === "accounts" && target.id) {
      const preflight = preflightAccountDeletion(
        [target.id],
        app.twin.getState("accounts"),
        app.twin.getState("emails"),
      );
      if (!preflight.allowed) {
        await showErrorDialog("Account cannot be deleted", accountDeletionBlockedMessage(preflight));
        return;
      }
    }
    const response = retry
      ? await app.twin.requestWithRetry(spec, { maxAttempts: 3, baseDelayMs: 200, faults: fault ? [fault] : [] })
      : await app.twin.request({ ...spec, fault });
    if (!routeGuardIsCurrent(routeGuard)) return;
    app.lastManualResponse = response;
    announce(`Request completed with status ${app.lastManualResponse.status}.`);
  } catch (error) {
    if (!routeGuardIsCurrent(routeGuard)) return;
    app.lastManualResponse = {
      transportError: error.name,
      code: error.code || "RETRY_EXHAUSTED",
      message: error.message,
      attempts: error.attempts,
      committed: error.committed,
    };
    announceError(`Request failed: ${error.message}`);
  }
  if (!routeGuardIsCurrent(routeGuard)) return;
  renderSimulationSettings();
}

async function runScenario(id) {
  const routeGuard = currentRouteGuard();
  try {
    const scenario = BUILT_IN_SCENARIOS.find((item) => item.id === id);
    await ensureEntities(scenario?.entities || []);
    if (!routeGuardIsCurrent(routeGuard)) return;
    app.twin.reset();
    const result = await runBuiltInScenario(app.twin, id);
    if (!routeGuardIsCurrent(routeGuard)) return;
    app.lastScenario = result;
    announce(`${app.lastScenario.label} ${app.lastScenario.passed ? "passed" : "failed"}.`);
  } catch (error) {
    if (!routeGuardIsCurrent(routeGuard)) return;
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
  if (!routeGuardIsCurrent(routeGuard)) return;
  renderSimulationSettings();
}

async function runAllScenarios() {
  const routeGuard = currentRouteGuard();
  const results = [];
  try {
    await ensureEntities(BUILT_IN_SCENARIOS.flatMap((scenario) => scenario.entities || []));
    if (!routeGuardIsCurrent(routeGuard)) return;
    for (const scenario of BUILT_IN_SCENARIOS) {
      if (!routeGuardIsCurrent(routeGuard)) return;
      app.twin.reset();
      results.push(await runBuiltInScenario(app.twin, scenario.id));
      if (!routeGuardIsCurrent(routeGuard)) return;
    }
    app.lastScenario = {
      id: "all",
      label: "All built-in scenarios",
      passed: results.every((result) => result.passed),
      assertions: results.flatMap((result) =>
        result.assertions.map((assertion) => ({ ...assertion, label: `${result.label}: ${assertion.label}` }))),
      diff: results.at(-1)?.diff || [],
      trace: app.twin.getTrace(),
      before: results[0]?.before,
      after: results.at(-1)?.after,
    };
    announce(`All scenarios completed: ${results.filter((result) => result.passed).length} of ${results.length} passed.`);
  } catch (error) {
    if (!routeGuardIsCurrent(routeGuard)) return;
    app.lastScenario = {
      label: "All built-in scenarios",
      passed: false,
      assertions: [{ label: error.message, pass: false, actual: error.name, expected: "successful scenarios" }],
      diff: [],
      trace: [],
    };
  }
  if (!routeGuardIsCurrent(routeGuard)) return;
  renderSimulationSettings();
}

function buildScenarioResults() {
  const result = app.lastScenario;
  if (!result) {
    return node("article", { className: "management-panel" }, [
      node("h2", { text: "Scenario result" }),
      node("p", { text: "Run a scenario to inspect assertions and the canonical state difference." }),
    ]);
  }
  return node("article", { className: "management-panel" }, [
    node("div", { className: "result-heading" }, [
      node("h2", { text: result.label }),
      node("span", { className: `status-badge ${result.passed ? "positive" : "negative"}`, text: result.passed ? "Passed" : "Failed" }),
    ]),
    node("ul", { className: "assertion-list" }, result.assertions.map((assertion) => node("li", {}, [
      icon(assertion.pass ? "check" : "cancel", `assertion-icon ${assertion.pass ? "pass" : "fail"}`),
      node("span", {}, [
        node("strong", { text: assertion.label }),
        node("small", { text: `Actual: ${String(assertion.actual)} · Expected: ${String(assertion.expected)}` }),
      ]),
    ]))),
    node("h3", { text: "State difference" }),
    result.diff?.length
      ? node("ul", { className: "diff-list" }, result.diff.map((change) =>
        node("li", { text: `${change.kind} ${change.entity} ${change.id}` })))
      : node("p", { text: "No canonical state changes." }),
    result.before && result.after ? node("details", {}, [
      node("summary", { text: "Digests and raw difference" }),
      rawJson({
        before: { at: result.before.at, stateDigest: result.before.stateDigest, traceDigest: result.before.traceDigest },
        after: { at: result.after.at, stateDigest: result.after.stateDigest, traceDigest: result.after.traceDigest },
        diff: result.diff,
      }),
    ]) : null,
  ]);
}

function buildTracePanel() {
  const trace = app.twin.getTrace().slice(-120).reverse();
  return node("article", { className: "management-panel" }, [
    node("div", { className: "result-heading" }, [
      node("h2", { text: `Append-only trace (${app.twin.getTrace().length})` }),
      node("code", { text: app.twin.traceDigest().slice(0, 16) }),
    ]),
    trace.length
      ? node("div", { className: "grid-scroll" }, [
        node("table", { className: "trace-table", "aria-label": "Runtime trace" }, [
          node("thead", {}, [node("tr", {}, [
            node("th", { text: "Sequence" }),
            node("th", { text: "Event" }),
            node("th", { text: "Request or record" }),
            node("th", { text: "Virtual UTC" }),
          ])]),
          node("tbody", {}, trace.map((event) => {
            const detail = rawJson(event, "trace-detail");
            detail.hidden = true;
            const toggle = node("button", {
              type: "button",
              text: event.type,
              "aria-expanded": "false",
              on: {
                click: () => {
                  detail.hidden = !detail.hidden;
                  toggle.setAttribute("aria-expanded", String(!detail.hidden));
                },
              },
            });
            return node("tr", {}, [
              node("td", { text: event.sequence }),
              node("td", {}, [toggle, detail]),
              node("td", { text: event.requestId || event.recordId || "" }),
              node("td", { text: event.at }),
            ]);
          })),
        ]),
      ])
      : node("p", { text: "No trace events have been recorded." }),
  ]);
}

function advanceClock(milliseconds) {
  app.twin.advanceTime(milliseconds, "service-management");
  announce(`Virtual clock advanced to ${app.twin.now()}.`);
  renderSimulationSettings();
}

function resetRuntime() {
  app.twin.reset();
  app.lastScenario = null;
  app.lastManualResponse = null;
  announce("Runtime reset to the loaded generated data.");
  renderSimulationSettings();
}

async function replayCurrentRun() {
  const routeGuard = currentRouteGuard();
  const replay = app.twin.exportReplay();
  try {
    const reproduced = await app.twin.constructor.replay(replay);
    if (!routeGuardIsCurrent(routeGuard)) return;
    app.lastManualResponse = {
      replayedActions: replay.actions.length,
      stateDigest: reproduced.stateDigest(),
      traceDigest: reproduced.traceDigest(),
      matches: reproduced.stateDigest() === app.twin.stateDigest()
        && reproduced.traceDigest() === app.twin.traceDigest(),
    };
    announce(app.lastManualResponse.matches ? "Replay reproduced both digests." : "Replay digest mismatch.");
  } catch (error) {
    if (!routeGuardIsCurrent(routeGuard)) return;
    app.lastManualResponse = { replayError: error.message };
    announceError(`Replay failed: ${error.message}`);
  }
  if (!routeGuardIsCurrent(routeGuard)) return;
  renderSimulationSettings();
}

function renderApiSimulation() {
  setCommands([
    command("Open metadata", "external", () => openExternal(new URL("$metadata.json", API_ROOT))),
    command("Simulation settings", "time", () => requestNavigation("#/service-management/simulation-settings"), { primary: true }),
  ]);
  const endpoints = (app.metadata?.EntitySets || []).map((entity) => node("li", {}, [
    node("code", { text: `GET /api/data/v9.2/${entity.name}.json` }),
    node("span", { text: `${Number(entity.recordCount || 0).toLocaleString("en-US")} generated records` }),
  ]));
  replace(ui.root,
    pageHeading("API & simulation", "OData-shaped data and deterministic runtime information"),
    simulationDisclosure(),
    node("div", { className: "management-layout" }, [
      node("article", { className: "management-panel" }, [
        node("h2", { text: "Generated endpoints" }),
        node("ul", { className: "endpoint-list" }, endpoints),
      ]),
      node("article", { className: "management-panel" }, [
        node("h2", { text: "Runtime invariants" }),
        node("ul", {}, [
          node("li", { text: "UTC timestamps require explicit offsets." }),
          node("li", { text: "Stable request IDs, GUIDs, ETags, ordering, and digests." }),
          node("li", { text: "If-Match rejects stale writes without changing state." }),
          node("li", { text: "Logical request IDs prevent double application after response loss." }),
          node("li", { text: "Tasks remain open after their due time until explicitly completed or canceled." }),
        ]),
      ]),
      node("article", { className: "management-panel wide" }, [
        node("h2", { text: "Metadata" }),
        rawJson(app.metadata),
      ]),
    ]),
  );
}

function renderNotFound(path) {
  setCommands([command("Back to dashboard", "back", () => requestNavigation("#/dashboard"))]);
  replace(ui.root, node("section", { className: "large-empty-state" }, [
    icon("search", "state-icon"),
    node("h1", { text: "Page not found" }),
    node("p", { text: `No Customer Service Hub page exists for “${path}”.` }),
    node("a", { href: "#/dashboard", className: "primary-link", text: "Go to Dashboards" }),
  ]));
}

async function navigate() {
  setCommands([]);
  closePopup();
  closeSitemap();
  const route = parseRoute();
  app.currentRoute = route;
  const token = ++app.navigationToken;
  setActiveNavigation(route);
  setBusy(true);
  app.activeForm = null;
  try {
    if (route.view === "dashboard") await renderDashboard(token);
    else if (route.view === "grid") await renderGridRoute(route, token);
    else if (route.view === "record") await renderRecordRoute(route, token);
    else if (route.view === "queues" || route.view === "knowledge-articles") renderEmptyCollection(route.view);
    else if (route.view === "knowledge-search") renderKnowledgeSearch(route.query);
    else if (route.view === "search") await renderGlobalSearch(route.query, token);
    else if (route.view === "simulation-settings") renderSimulationSettings();
    else if (route.view === "api-simulation") renderApiSimulation();
    else renderNotFound(route.path);
  } catch (error) {
    if (token !== app.navigationToken) return;
    showLoadError("This page could not be loaded", error, navigate);
  } finally {
    if (token === app.navigationToken) {
      setBusy(false);
      ui.main.focus();
    }
  }
}

function handleDocumentClick(event) {
  const link = event.target instanceof Element
    ? event.target.closest("a[href^='#/']")
    : null;
  if (link && shouldInterceptSpaNavigation({
    button: event.button,
    defaultPrevented: event.defaultPrevented,
    ctrlKey: event.ctrlKey,
    metaKey: event.metaKey,
    shiftKey: event.shiftKey,
    altKey: event.altKey,
    download: link.hasAttribute("download"),
    target: link.getAttribute("target"),
  })) {
    event.preventDefault();
    requestNavigation(link.getAttribute("href"));
    return;
  }
  if (app.activePopup && !app.activePopup.panel.contains(event.target)
    && !app.activePopup.button.contains(event.target)
    && event.target !== ui.selector) {
    closePopup();
  }
}

function handleDocumentKeydown(event) {
  if (event.key !== "Escape") return;
  if (ui.sitemap.classList.contains("open")) {
    event.preventDefault();
    closeSitemap(true);
  } else if (app.activePopup) {
    event.preventDefault();
    closePopup(true);
  }
}

function beforeUnload(event) {
  if (!app.dirty) return;
  event.preventDefault();
  event.returnValue = "";
}

async function boot() {
  if (!app.shellListenersReady) {
    ui.navigationToggle.addEventListener("click", openSitemap);
    ui.navigationClose.addEventListener("click", () => closeSitemap(true));
    ui.scrim.addEventListener("click", () => closeSitemap(true));
    ui.launcher.addEventListener("click", () => togglePopup(ui.launcher, ui.launcherMenu));
    ui.selector.addEventListener("click", () => togglePopup(ui.selector, ui.launcherMenu));
    ui.quickCreate.addEventListener("click", () => togglePopup(ui.quickCreate, ui.quickCreateMenu));
    ui.areaSwitcher.addEventListener("click", () => togglePopup(ui.areaSwitcher, ui.areaMenu));
    ui.globalSearch.addEventListener("submit", (event) => {
      event.preventDefault();
      requestNavigation(`#/search?q=${encodeURIComponent(ui.globalSearchInput.value.trim())}`);
    });
    document.addEventListener("click", handleDocumentClick);
    document.addEventListener("keydown", handleDocumentKeydown);
    window.addEventListener("popstate", handlePopState);
    window.addEventListener("beforeunload", beforeUnload);
    window.addEventListener("unhandledrejection", (event) => {
      announceError(`Unexpected error: ${event.reason?.message || event.reason}`);
    });
    app.shellListenersReady = true;
  }
  showLoading("Loading Customer Service Hub");
  try {
    await loadMetadata();
  } catch (error) {
    showLoadError("Customer Service Hub could not start", error, boot);
    return;
  }
  const initialHash = window.location.hash || "#/dashboard";
  const initialIndex = indexedHistoryPosition(window.history.state) ?? 0;
  app.navigationHistory = createNavigationHistory(initialIndex);
  window.history.replaceState({
    ...(window.history.state || {}),
    [HISTORY_INDEX_KEY]: initialIndex,
  }, "", initialHash);
  app.currentHash = initialHash;
  await navigate();
}

boot();
