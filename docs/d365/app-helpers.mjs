export const PAGE_SIZE = 50;
export const RELATED_EMAIL_LIMIT = 25;

const DASHBOARD_FOCUS_TARGETS = Object.freeze({
  selector: "dashboard-selector",
  refresh: "dashboard-refresh",
});

export function replaceDialogState(activeDialog, incomingDialog) {
  return {
    activeDialog: incomingDialog,
    replacement: activeDialog
      ? { dialog: activeDialog, value: activeDialog.cancelValue }
      : null,
  };
}

export function dashboardRenderCompletion(focusTarget = null) {
  return {
    busy: false,
    focusTargetId: DASHBOARD_FOCUS_TARGETS[focusTarget] || null,
  };
}

export function savedFormRenderTarget(activeForm, savedRecord, selectedTab = "summary") {
  if (!activeForm?.entity || !savedRecord) return null;
  const initialTab = ["summary", "details", "related"].includes(selectedTab)
    ? selectedTab
    : "summary";
  return {
    entity: activeForm.entity,
    record: savedRecord,
    initialTab,
  };
}

export function createNavigationHistory(currentIndex = 0) {
  return {
    currentIndex: Number.isInteger(currentIndex) ? currentIndex : 0,
    pending: null,
  };
}

export function pushNavigationHistory(history) {
  return {
    currentIndex: history.currentIndex + 1,
    pending: null,
  };
}

export function transitionHistoryPop(history, targetIndex, dirty) {
  const pending = history.pending;
  if (!Number.isInteger(targetIndex)) {
    return {
      state: history,
      effect: { type: pending ? "stay" : "unknown" },
    };
  }
  if (pending) {
    const anchorIndex = pending.phase === "proceeding"
      ? pending.targetIndex
      : pending.originIndex;
    if (targetIndex !== anchorIndex) {
      return {
        state: history,
        effect: { type: "traverse", delta: anchorIndex - targetIndex },
      };
    }
    if (pending.phase === "restoring") {
      return {
        state: { ...history, pending: { ...pending, phase: "prompting" } },
        effect: { type: "prompt" },
      };
    }
    if (pending.phase === "prompting") {
      return { state: history, effect: { type: "stay" } };
    }
    if (pending.phase === "proceeding") {
      return {
        state: { currentIndex: targetIndex, pending: null },
        effect: { type: "navigate" },
      };
    }
    return { state: history, effect: { type: "stay" } };
  }
  if (targetIndex === history.currentIndex) {
    return { state: history, effect: { type: "stay" } };
  }
  if (!dirty) {
    return {
      state: { currentIndex: targetIndex, pending: null },
      effect: { type: "navigate" },
    };
  }
  return {
    state: {
      ...history,
      pending: {
        originIndex: history.currentIndex,
        targetIndex,
        phase: "restoring",
      },
    },
    effect: {
      type: "traverse",
      delta: history.currentIndex - targetIndex,
    },
  };
}

export function transitionHistoryPrompt(history, proceed) {
  const pending = history.pending;
  if (pending?.phase !== "prompting") {
    return { state: history, effect: { type: "stay" } };
  }
  if (!proceed) {
    return {
      state: { currentIndex: pending.originIndex, pending: null },
      effect: { type: "stay" },
    };
  }
  return {
    state: { ...history, pending: { ...pending, phase: "proceeding" } },
    effect: {
      type: "traverse",
      delta: pending.targetIndex - pending.originIndex,
    },
  };
}

export function nextRovingTabIndex(tabs, currentIndex, key) {
  const enabled = tabs
    .map((tab, index) => ({ tab, index }))
    .filter(({ tab }) => !tab.disabled)
    .map(({ index }) => index);
  if (!enabled.length) return -1;
  if (key === "Home") return enabled[0];
  if (key === "End") return enabled.at(-1);
  if (key !== "ArrowLeft" && key !== "ArrowRight") return currentIndex;
  const position = enabled.indexOf(currentIndex);
  const offset = key === "ArrowRight" ? 1 : -1;
  const nextPosition = position < 0
    ? (offset > 0 ? 0 : enabled.length - 1)
    : (position + offset + enabled.length) % enabled.length;
  return enabled[nextPosition];
}

function normalizeSnapshotValue(value) {
  if (value === undefined || value === null) return null;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) return null;
    return Object.is(value, -0) ? 0 : value;
  }
  if (typeof value === "string") return value.replace(/\r\n?/g, "\n");
  return value;
}

export function normalizeEditableSnapshot(values = {}) {
  return Object.fromEntries(
    Object.keys(values).sort().map((key) => [key, normalizeSnapshotValue(values[key])]),
  );
}

export function editableSnapshotsEqual(left, right) {
  return JSON.stringify(normalizeEditableSnapshot(left))
    === JSON.stringify(normalizeEditableSnapshot(right));
}

export function isRecordEditable(entity, record, entityEditable = true) {
  if (!entityEditable) return false;
  if (!record) return true;
  if (!["contacts", "accounts", "tasks", "incidents"].includes(entity)) return true;
  return Number(record.statecode ?? 0) === 0;
}

export function recordCommandActions(entity, record, options = {}) {
  const entityEditable = options.editable ?? true;
  const deletable = options.deletable ?? true;
  const creating = !record;
  const active = Number(record?.statecode ?? 0) === 0;
  const actions = [];
  if (isRecordEditable(entity, record, entityEditable)) actions.push("save", "save-close");
  if (!creating && (entity === "contacts" || entity === "accounts")) {
    actions.push(active ? "deactivate" : "activate");
  } else if (!creating && entity === "tasks" && active) {
    actions.push("complete", "cancel");
  } else if (!creating && entity === "incidents") {
    actions.push(...(active ? ["resolve", "cancel"] : ["reopen"]));
  }
  if (!creating && entity === "emails" && options.hasSafeSource) actions.push("open-source");
  if (!creating && deletable) actions.push("delete");
  if (!creating) actions.push("refresh");
  actions.push("back");
  return actions;
}

export const NAV_GROUPS = Object.freeze([
  Object.freeze({
    label: "My Work",
    items: Object.freeze([
      Object.freeze({ key: "dashboard", label: "Dashboards" }),
      Object.freeze({ key: "activities", label: "Activities" }),
    ]),
  }),
  Object.freeze({
    label: "Customers",
    items: Object.freeze([
      Object.freeze({ key: "accounts", label: "Accounts" }),
      Object.freeze({ key: "contacts", label: "Contacts" }),
    ]),
  }),
  Object.freeze({
    label: "Service",
    items: Object.freeze([
      Object.freeze({ key: "cases", label: "Cases" }),
      Object.freeze({ key: "queues", label: "Queues" }),
    ]),
  }),
  Object.freeze({
    label: "Knowledge",
    items: Object.freeze([
      Object.freeze({ key: "knowledge-articles", label: "Knowledge Articles" }),
      Object.freeze({ key: "knowledge-search", label: "Knowledge Search" }),
    ]),
  }),
  Object.freeze({
    label: "Service Management",
    items: Object.freeze([
      Object.freeze({ key: "simulation-settings", label: "Simulation settings" }),
      Object.freeze({ key: "api-simulation", label: "API & simulation" }),
    ]),
  }),
]);

export const SYSTEM_VIEWS = Object.freeze({
  contacts: Object.freeze([
    Object.freeze({ id: "active", label: "Active Contacts" }),
    Object.freeze({ id: "inactive", label: "Inactive Contacts" }),
    Object.freeze({ id: "all", label: "All Contacts" }),
  ]),
  accounts: Object.freeze([
    Object.freeze({ id: "active", label: "Active Accounts" }),
    Object.freeze({ id: "inactive", label: "Inactive Accounts" }),
    Object.freeze({ id: "all", label: "All Accounts" }),
  ]),
  incidents: Object.freeze([
    Object.freeze({ id: "active", label: "Active Cases" }),
    Object.freeze({ id: "resolved", label: "Resolved Cases" }),
    Object.freeze({ id: "all", label: "All Cases" }),
  ]),
  activities: Object.freeze([
    Object.freeze({ id: "open", label: "Open Activities" }),
    Object.freeze({ id: "closed", label: "Closed Activities" }),
    Object.freeze({ id: "all", label: "All Activities" }),
    Object.freeze({ id: "sent-email", label: "Sent Email" }),
  ]),
  connections: Object.freeze([
    Object.freeze({ id: "active", label: "Active Connections" }),
    Object.freeze({ id: "all", label: "All Connections" }),
  ]),
});

const TASK_STATE_LABELS = Object.freeze({
  0: "Open",
  1: "Completed",
  2: "Canceled",
});

const TASK_PRIORITY_LABELS = Object.freeze({
  0: "Low",
  1: "Normal",
  2: "High",
});

const INCIDENT_PRIORITY_LABELS = Object.freeze({
  1: "High",
  2: "Normal",
  3: "Low",
});

const INCIDENT_STATE_LABELS = Object.freeze({
  0: "Active",
  1: "Resolved",
  2: "Canceled",
});

export function codeUnitCompare(left, right) {
  const first = String(left ?? "");
  const second = String(right ?? "");
  return first < second ? -1 : first > second ? 1 : 0;
}

function parsedDate(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : null;
}

export function newestRelatedEmails(emails, limit = RELATED_EMAIL_LIMIT) {
  const maximum = Number.isFinite(limit)
    ? Math.max(0, Math.floor(limit))
    : RELATED_EMAIL_LIMIT;
  return [...emails].sort((left, right) => {
    const leftTimestamp = parsedDate(left?.createdon);
    const rightTimestamp = parsedDate(right?.createdon);
    if (leftTimestamp !== null && rightTimestamp !== null) {
      return leftTimestamp === rightTimestamp
        ? codeUnitCompare(left?.activityid, right?.activityid)
        : rightTimestamp - leftTimestamp;
    }
    if (leftTimestamp !== null) return -1;
    if (rightTimestamp !== null) return 1;
    return codeUnitCompare(left?.activityid, right?.activityid);
  }).slice(0, maximum);
}

export function relatedEmailsForAccount(emails, accountId) {
  return newestRelatedEmails((emails || []).filter((email) =>
    emailReferencesAccount(email, accountId)));
}

export function relatedEmailsForContact(emails, contact) {
  const contactId = String(contact?.contactid || "").toLowerCase();
  const sourceKey = String(contact?.new_agentid || "").toLowerCase();
  return newestRelatedEmails(emails.filter((email) => {
    const authorId = String(email?.new_authorid || "").toLowerCase();
    const authorKey = String(email?.new_author || "").toLowerCase();
    return (contactId && authorId === contactId) || (sourceKey && authorKey === sourceKey);
  }));
}

function normalizedIdentifier(value) {
  let normalized = String(value ?? "").trim().toLowerCase();
  normalized = normalized.replace(/^['"]|['"]$/g, "").trim();
  if (normalized.startsWith("{") && normalized.endsWith("}")) {
    normalized = normalized.slice(1, -1).trim();
  }
  return normalized;
}

function boundAccountIdentifier(value) {
  const match = String(value ?? "").trim().match(
    /(?:^|\/)accounts\s*\(\s*(\{?[^{}()/?#]+\}?)\s*\)(?:[?#].*)?$/i,
  );
  return normalizedIdentifier(match?.[1]);
}

export function emailReferencesAccount(email, accountId) {
  const normalized = normalizedIdentifier(accountId);
  if (!normalized) return false;
  return normalizedIdentifier(email?._regardingobjectid_value) === normalized
    || boundAccountIdentifier(email?.["regardingobjectid_account@odata.bind"]) === normalized;
}

function routeSignature(route) {
  return JSON.stringify({
    view: route?.view ?? null,
    entity: route?.entity ?? null,
    id: route?.id === undefined || route?.id === null
      ? null
      : normalizedIdentifier(route.id),
    query: route?.query ?? null,
    path: route?.path ?? null,
    initialView: route?.initialView ?? null,
    scenario: route?.scenario ?? null,
  });
}

export function captureRouteGuard(navigationToken, route) {
  return Object.freeze({
    navigationToken,
    routeSignature: routeSignature(route),
  });
}

export function routeGuardMatches(guard, navigationToken, route) {
  return Boolean(guard)
    && guard.navigationToken === navigationToken
    && guard.routeSignature === routeSignature(route);
}

export function preflightContactDeletion(contactIds, contacts, connections) {
  const requested = new Map();
  for (const contactId of contactIds || []) {
    const normalized = normalizedIdentifier(contactId);
    if (normalized && !requested.has(normalized)) requested.set(normalized, String(contactId));
  }
  const names = new Map((contacts || []).map((contact) => [
    normalizedIdentifier(contact?.contactid),
    contact?.fullname
      || [contact?.firstname, contact?.lastname].filter(Boolean).join(" ")
      || String(contact?.contactid || ""),
  ]));
  const blockers = [];
  for (const [normalized, contactId] of requested) {
    const connectionIds = (connections || []).filter((connection) =>
      normalizedIdentifier(connection?._record1id_value) === normalized
      || normalizedIdentifier(connection?._record2id_value) === normalized)
      .map((connection) => String(connection?.connectionid || ""))
      .sort(codeUnitCompare);
    if (connectionIds.length) {
      blockers.push({
        contactId,
        contactName: names.get(normalized) || contactId,
        connectionIds,
      });
    }
  }
  return {
    allowed: blockers.length === 0,
    blockers,
  };
}

export function preflightAccountDeletion(accountIds, accounts, emails) {
  const requested = new Map();
  for (const accountId of accountIds || []) {
    const normalized = normalizedIdentifier(accountId);
    if (normalized && !requested.has(normalized)) requested.set(normalized, String(accountId));
  }
  const names = new Map((accounts || []).map((account) => [
    normalizedIdentifier(account?.accountid),
    account?.name || String(account?.accountid || ""),
  ]));
  const blockers = [];
  for (const [normalized, accountId] of requested) {
    const emailIds = (emails || [])
      .filter((email) => emailReferencesAccount(email, normalized))
      .map((email) => String(email?.activityid || ""))
      .sort(codeUnitCompare);
    if (emailIds.length) {
      blockers.push({
        accountId,
        accountName: names.get(normalized) || accountId,
        emailIds,
      });
    }
  }
  return {
    allowed: blockers.length === 0,
    blockers,
  };
}

export function shouldInterceptSpaNavigation(options = {}) {
  const target = String(options.target || "").trim().toLowerCase();
  return !options.defaultPrevented
    && Number(options.button ?? 0) === 0
    && !options.ctrlKey
    && !options.metaKey
    && !options.shiftKey
    && !options.altKey
    && !options.download
    && (!target || target === "_self");
}

export function isTaskOverdue(task, now) {
  if (Number(task?.statecode) !== 0) return false;
  const due = parsedDate(task?.scheduledend);
  const current = parsedDate(now);
  return due !== null && current !== null && due < current;
}

export function taskStatusLabel(task, now) {
  if (Number(task?.statecode) === 0 && isTaskOverdue(task, now)) return "Overdue";
  return TASK_STATE_LABELS[Number(task?.statecode)] ?? String(task?.statecode ?? "");
}

export function emailStatusLabel(email) {
  const state = Number(email?.statecode);
  if (state === 1 && Number(email?.statuscode) === 3) return "Sent";
  if (state === 0) return "Open";
  if (state === 2) return "Canceled";
  return state === 1 ? "Completed" : String(email?.statuscode ?? "");
}

export function combineActivities(emails = [], tasks = [], now = "") {
  const normalizedEmails = emails.map((email) => ({
    ...email,
    _activityType: "Email",
    _entity: "emails",
    _id: email.activityid,
    _status: emailStatusLabel(email),
    _regarding: email.new_channel || email.torecipients || "",
    _activityDate: email.actualend || email.createdon || "",
    _dueOrSent: email.actualend || email.createdon || "",
  }));
  const normalizedTasks = tasks.map((task) => ({
    ...task,
    _activityType: "Task",
    _entity: "tasks",
    _id: task.activityid,
    _status: taskStatusLabel(task, now),
    _regarding: "",
    _activityDate: task.modifiedon || task.createdon || task.scheduledend || "",
    _dueOrSent: task.scheduledend || "",
  }));
  return [...normalizedEmails, ...normalizedTasks];
}

export function gridCodeLabel(entity, field, value, now = "", record = null) {
  if (value === undefined || value === null || value === "") return null;
  const code = Number(value);
  if (field === "statecode") {
    if (entity === "tasks") return record ? taskStatusLabel(record, now) : TASK_STATE_LABELS[code] ?? String(value);
    if (entity === "emails") return record ? emailStatusLabel(record) : code === 1 ? "Sent" : String(value);
    if (entity === "incidents") return INCIDENT_STATE_LABELS[code] ?? String(value);
    return code === 0 ? "Active" : "Inactive";
  }
  if (field === "prioritycode") {
    const labels = entity === "tasks" ? TASK_PRIORITY_LABELS : INCIDENT_PRIORITY_LABELS;
    return labels[code] ?? String(value);
  }
  return null;
}

export function contactStatusLabel(value) {
  if (value === undefined || value === null || value === "") return "";
  return String(value).toLowerCase() === "active" ? "Active" : "Inactive";
}

export function applySystemView(records, entity, viewId) {
  if (viewId === "all") return [...records];
  if (entity === "contacts" || entity === "accounts") {
    return records.filter((record) => Number(record.statecode) === (viewId === "inactive" ? 1 : 0));
  }
  if (entity === "incidents") {
    if (viewId === "resolved") return records.filter((record) => Number(record.statecode) === 1);
    return records.filter((record) => Number(record.statecode) === 0);
  }
  if (entity === "connections") {
    return records.filter((record) => Number(record.statecode) === 0);
  }
  if (entity === "activities") {
    if (viewId === "sent-email") {
      return records.filter((record) => record._entity === "emails" && record._status === "Sent");
    }
    if (viewId === "open") {
      return records.filter((record) => record._status === "Open" || record._status === "Overdue");
    }
    if (viewId === "closed") {
      return records.filter((record) => !["Open", "Overdue"].includes(record._status));
    }
  }
  return [...records];
}

export function searchRows(records, fields, query, displayValue = null) {
  const term = String(query ?? "").trim().toLowerCase();
  if (!term) return [...records];
  return records.filter((record) => fields.some((field) => {
    const raw = String(record[field] ?? "").toLowerCase();
    const displayed = displayValue
      ? String(displayValue(record, field) ?? "").toLowerCase()
      : "";
    return raw.includes(term) || displayed.includes(term);
  }));
}

function compareGridValues(left, right) {
  if (typeof left === "number" && typeof right === "number") return left - right;
  return codeUnitCompare(String(left).toLowerCase(), String(right).toLowerCase());
}

export function stableSortRows(records, key, direction = "asc", identityKey = null) {
  const multiplier = direction === "desc" ? -1 : 1;
  return records.map((record, index) => ({ record, index })).sort((left, right) => {
    const leftValue = left.record[key];
    const rightValue = right.record[key];
    const leftEmpty = leftValue === undefined || leftValue === null || leftValue === "";
    const rightEmpty = rightValue === undefined || rightValue === null || rightValue === "";
    if (leftEmpty !== rightEmpty) return leftEmpty ? 1 : -1;
    const compared = leftEmpty && rightEmpty ? 0 : compareGridValues(leftValue, rightValue);
    if (compared) return compared * multiplier;
    if (identityKey) {
      const identity = codeUnitCompare(left.record[identityKey], right.record[identityKey]);
      if (identity) return identity;
    }
    return left.index - right.index;
  }).map(({ record }) => record);
}

export function paginateRows(records, requestedPage, pageSize = PAGE_SIZE) {
  const size = Math.max(1, Math.floor(Number(pageSize) || PAGE_SIZE));
  const pageCount = Math.max(1, Math.ceil(records.length / size));
  const page = Math.min(pageCount, Math.max(1, Math.floor(Number(requestedPage) || 1)));
  const startIndex = (page - 1) * size;
  const rows = records.slice(startIndex, startIndex + size);
  return {
    rows,
    page,
    pageCount,
    pageSize: size,
    total: records.length,
    start: rows.length ? startIndex + 1 : 0,
    end: startIndex + rows.length,
    hasPrevious: page > 1,
    hasNext: page < pageCount,
  };
}

export function updateSelection(currentSelection, keys, selected) {
  const next = new Set(currentSelection || []);
  for (const key of keys) {
    if (selected) next.add(key);
    else next.delete(key);
  }
  return next;
}

export function resolveConnectionRows(connections, contacts) {
  const names = new Map(contacts.map((contact) => [
    String(contact.contactid || "").toLowerCase(),
    contact.fullname || [contact.firstname, contact.lastname].filter(Boolean).join(" "),
  ]));
  return connections.map((connection) => ({
    ...connection,
    _record1name: names.get(String(connection._record1id_value || "").toLowerCase()) || "",
    _record2name: names.get(String(connection._record2id_value || "").toLowerCase()) || "",
  }));
}

export function relatedConnectionsForContact(connections, contactId, contacts) {
  const normalized = String(contactId || "").toLowerCase();
  return resolveConnectionRows(connections, contacts).flatMap((connection) => {
    const firstId = String(connection._record1id_value || "").toLowerCase();
    const secondId = String(connection._record2id_value || "").toLowerCase();
    if (firstId !== normalized && secondId !== normalized) return [];
    const currentIsFirst = firstId === normalized;
    return [{
      ...connection,
      _relatedId: currentIsFirst ? connection._record2id_value : connection._record1id_value,
      _relatedName: currentIsFirst ? connection._record2name : connection._record1name,
      _relationship: currentIsFirst ? "Follows" : "Followed by",
    }];
  });
}

function newestFirst(records, dateKey, identityKey) {
  return [...records].sort((left, right) => {
    const leftDate = parsedDate(left[dateKey]);
    const rightDate = parsedDate(right[dateKey]);
    if (leftDate !== null && rightDate !== null && leftDate !== rightDate) return rightDate - leftDate;
    if (leftDate !== null && rightDate === null) return -1;
    if (leftDate === null && rightDate !== null) return 1;
    return codeUnitCompare(left[identityKey], right[identityKey]);
  });
}

function countActivityValues(activities, key) {
  const counts = new Map();
  for (const activity of activities) {
    const label = String(activity[key] ?? "").trim();
    if (label) counts.set(label, (counts.get(label) || 0) + 1);
  }
  return [...counts].map(([label, value]) => ({ label, value }))
    .sort((left, right) => codeUnitCompare(left.label, right.label));
}

export function deriveDashboardMetrics(data, now) {
  const incidents = data.incidents || [];
  const contacts = data.contacts || [];
  const accounts = data.accounts || [];
  const activities = combineActivities(data.emails || [], data.tasks || [], now);
  const activeCases = newestFirst(
    incidents.filter((record) => Number(record.statecode) === 0),
    "createdon",
    "incidentid",
  );
  const recentActivities = newestFirst(activities, "_activityDate", "_id").slice(0, 8);
  const openActivities = newestFirst(
    activities.filter((record) => record._status === "Open" || record._status === "Overdue"),
    "_dueOrSent",
    "_id",
  );
  const sentEmails = newestFirst(
    activities.filter((record) => record._entity === "emails" && record._status === "Sent"),
    "_dueOrSent",
    "_id",
  );
  const taskActivities = newestFirst(
    activities.filter((record) => record._entity === "tasks"),
    "_activityDate",
    "_id",
  );
  const casePriority = [1, 2, 3].map((value) => ({
    label: INCIDENT_PRIORITY_LABELS[value],
    value: incidents.filter((record) => Number(record.prioritycode) === value).length,
  }));
  const contactStatus = [
    { label: "Active", value: contacts.filter((record) => Number(record.statecode) === 0).length },
    { label: "Inactive", value: contacts.filter((record) => Number(record.statecode) !== 0).length },
  ];
  const accountActivity = accounts.map((account) => ({
    id: account.accountid,
    label: account.name || "",
    value: Number(account.new_postcount || 0),
  })).sort((left, right) => right.value - left.value || codeUnitCompare(left.id, right.id));
  return {
    activeCases,
    recentActivities,
    openActivities,
    sentEmails,
    taskActivities,
    activitiesByType: countActivityValues(activities, "_activityType"),
    activitiesByStatus: countActivityValues(activities, "_status"),
    casePriority,
    contactStatus,
    accountActivity,
  };
}

export function transitionPatch(entity, action, now) {
  const transitions = {
    tasks: {
      complete: { statecode: 1, statuscode: 5, actualend: now },
      cancel: { statecode: 2, statuscode: 6, actualend: now },
    },
    incidents: {
      resolve: { statecode: 1, statuscode: 5 },
      cancel: { statecode: 2, statuscode: 6 },
      reopen: { statecode: 0, statuscode: 1 },
    },
    contacts: {
      activate: { statecode: 0, statuscode: 1, new_status: "active" },
      deactivate: { statecode: 1, statuscode: 2, new_status: "inactive" },
    },
    accounts: {
      activate: { statecode: 0, statuscode: 1 },
      deactivate: { statecode: 1, statuscode: 2 },
    },
  };
  const patch = transitions[entity]?.[action];
  if (!patch) throw new TypeError(`Unsupported ${entity} transition: ${action}`);
  return { ...patch };
}
