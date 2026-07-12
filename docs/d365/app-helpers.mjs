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

function codeUnitCompare(left, right) {
  const first = String(left ?? "");
  const second = String(right ?? "");
  return first < second ? -1 : first > second ? 1 : 0;
}

function parsedCreatedOn(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : null;
}

export function newestRelatedEmails(emails, limit = 25) {
  const maximum = Number.isFinite(limit) ? Math.max(0, Math.floor(limit)) : 25;
  return [...emails].sort((left, right) => {
    const leftTimestamp = parsedCreatedOn(left?.createdon);
    const rightTimestamp = parsedCreatedOn(right?.createdon);
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

export function gridCodeLabel(entity, field, value) {
  if (value === undefined || value === null || value === "") return null;
  const code = Number(value);
  if (field === "statecode") {
    if (entity === "tasks") return TASK_STATE_LABELS[code] ?? String(value);
    if (entity === "incidents") return INCIDENT_STATE_LABELS[code] ?? String(value);
    return code === 0 ? "Active" : "Inactive";
  }
  if (field === "prioritycode") {
    const labels = entity === "tasks" ? TASK_PRIORITY_LABELS : INCIDENT_PRIORITY_LABELS;
    return labels[code] ?? String(value);
  }
  return null;
}

export function isActiveEntityRoute(currentToken, currentRoute, expectedToken, expectedEntity) {
  return currentToken === expectedToken
    && currentRoute?.view === "entity"
    && currentRoute.entity === expectedEntity;
}
