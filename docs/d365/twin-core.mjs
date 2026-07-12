const DEFAULT_EPOCH = "2026-01-01T09:00:00.000Z";
const API_PREFIX = "/api/data/v9.2/";
const EXPLICIT_DATETIME_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,9})?)?(?:Z|[+-](\d{2}):(\d{2}))$/;
const WHO_AM_I = Object.freeze({
  BusinessUnitId: "9f3e3206-3a93-ab81-e047-c4888a7ff2a3",
  UserId: "eaca6de9-77e4-0315-ac33-905849c43b21",
  OrganizationId: "36bd0f72-17ac-917b-6b87-226cf1edcd20",
  OrganizationName: "Rappterbook",
});

export const ENTITY_DEFINITIONS = Object.freeze({
  contacts: {
    primaryKey: "contactid",
    required: ["firstname"],
    defaults: { statecode: 0, statuscode: 1, new_status: "active" },
    fields: {
      contactid: "string", firstname: "string", lastname: "string", fullname: "string",
      emailaddress1: "string", jobtitle: "string", description: "string", department: "string",
      statecode: "number", statuscode: "number", createdon: "datetime", modifiedon: "datetime",
      new_agentid: "string", new_karma: "number", new_karmabalance: "number",
      new_postcount: "number", new_commentcount: "number", new_archetype: "string",
      new_status: "string", new_subscribedchannels: "string",
    },
  },
  accounts: {
    primaryKey: "accountid",
    required: ["name"],
    defaults: { statecode: 0, statuscode: 1 },
    fields: {
      accountid: "string", name: "string", description: "string", websiteurl: "string",
      statecode: "number", statuscode: "number", createdon: "datetime", modifiedon: "datetime",
      new_slug: "string", new_postcount: "number", new_icon: "string",
      new_constitution: "string", new_topicaffinity: "string",
    },
  },
  emails: {
    primaryKey: "activityid",
    required: ["subject"],
    defaults: { statecode: 1, statuscode: 3, directioncode: true },
    fields: {
      activityid: "string", subject: "string", description: "string", statecode: "number",
      statuscode: "number", createdon: "datetime", modifiedon: "datetime",
      directioncode: "boolean", actualend: "datetime", sender: "string", torecipients: "string",
      _regardingobjectid_value: "string", "regardingobjectid_account@odata.bind": "string",
      new_discussionnumber: "number", new_channel: "string", new_author: "string",
      new_authorid: "string", new_upvotes: "number", new_downvotes: "number",
      new_commentcount: "number", new_url: "string", new_posttopic: "string",
    },
  },
  tasks: {
    primaryKey: "activityid",
    required: ["subject"],
    defaults: { statecode: 0, statuscode: 2, prioritycode: 1 },
    fields: {
      activityid: "string", subject: "string", description: "string", statecode: "number",
      statuscode: "number", prioritycode: "number", createdon: "datetime", modifiedon: "datetime",
      scheduledend: "datetime", actualend: "datetime", new_fromid: "string",
      new_toid: "string", new_poketype: "string",
    },
  },
  connections: {
    primaryKey: "connectionid",
    required: ["name", "_record1id_value", "_record2id_value"],
    defaults: { statecode: 0, statuscode: 1 },
    fields: {
      connectionid: "string", name: "string", _record1id_value: "string",
      _record2id_value: "string", record1objecttypecode: "string",
      record2objecttypecode: "string", statecode: "number", statuscode: "number",
    },
  },
  incidents: {
    primaryKey: "incidentid",
    required: ["title"],
    defaults: { statecode: 0, statuscode: 1, prioritycode: 2, severitycode: 2 },
    fields: {
      incidentid: "string", title: "string", description: "string", caseorigincode: "number",
      casetypecode: "number", prioritycode: "number", severitycode: "number",
      statecode: "number", statuscode: "number", createdon: "datetime", modifiedon: "datetime",
      new_category: "string", new_score: "number", new_overallscore: "number",
      new_grade: "string", new_sla_due: "datetime", new_sla_status: "string",
    },
  },
});

const ERROR_CODES = Object.freeze({
  badRequest: "0x80048d19",
  notFound: "0x80040217",
  precondition: "0x80060882",
  conflict: "0x8004A101",
  tooMany: "0x80072321",
  unavailable: "0x80072EE7",
});

function utf8Bytes(input) {
  return new TextEncoder().encode(input);
}

function rotateRight(value, count) {
  return (value >>> count) | (value << (32 - count));
}

export function sha256(input) {
  const source = utf8Bytes(String(input));
  const bitLength = source.length * 8;
  const paddedLength = Math.ceil((source.length + 9) / 64) * 64;
  const bytes = new Uint8Array(paddedLength);
  bytes.set(source);
  bytes[source.length] = 0x80;
  const view = new DataView(bytes.buffer);
  view.setUint32(paddedLength - 8, Math.floor(bitLength / 0x100000000), false);
  view.setUint32(paddedLength - 4, bitLength >>> 0, false);
  const constants = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
    0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ];
  const hash = [
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ];
  const words = new Uint32Array(64);
  for (let offset = 0; offset < bytes.length; offset += 64) {
    for (let index = 0; index < 16; index += 1) {
      words[index] = view.getUint32(offset + index * 4, false);
    }
    for (let index = 16; index < 64; index += 1) {
      const s0 = rotateRight(words[index - 15], 7) ^ rotateRight(words[index - 15], 18) ^ (words[index - 15] >>> 3);
      const s1 = rotateRight(words[index - 2], 17) ^ rotateRight(words[index - 2], 19) ^ (words[index - 2] >>> 10);
      words[index] = (words[index - 16] + s0 + words[index - 7] + s1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = hash;
    for (let index = 0; index < 64; index += 1) {
      const sum1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
      const choice = (e & f) ^ (~e & g);
      const temp1 = (h + sum1 + choice + constants[index] + words[index]) >>> 0;
      const sum0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (sum0 + majority) >>> 0;
      h = g; g = f; f = e; e = (d + temp1) >>> 0;
      d = c; c = b; b = a; a = (temp1 + temp2) >>> 0;
    }
    hash[0] = (hash[0] + a) >>> 0;
    hash[1] = (hash[1] + b) >>> 0;
    hash[2] = (hash[2] + c) >>> 0;
    hash[3] = (hash[3] + d) >>> 0;
    hash[4] = (hash[4] + e) >>> 0;
    hash[5] = (hash[5] + f) >>> 0;
    hash[6] = (hash[6] + g) >>> 0;
    hash[7] = (hash[7] + h) >>> 0;
  }
  return hash.map((value) => value.toString(16).padStart(8, "0")).join("");
}

export function canonicalStringify(value) {
  if (value === null) return "null";
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError("Canonical JSON requires finite numbers");
    return Object.is(value, -0) ? "0" : JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalStringify).join(",")}]`;
  if (typeof value === "object") {
    const entries = Object.keys(value)
      .filter((key) => value[key] !== undefined)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalStringify(value[key])}`);
    return `{${entries.join(",")}}`;
  }
  throw new TypeError(`Unsupported canonical value: ${typeof value}`);
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function compareCodeUnits(left, right) {
  const first = String(left);
  const second = String(right);
  return first < second ? -1 : first > second ? 1 : 0;
}

export function deterministicGuid(seed) {
  const hex = sha256(String(seed)).slice(0, 32);
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function recordContent(record) {
  const content = {};
  for (const [key, value] of Object.entries(record)) {
    if (key !== "@odata.etag") content[key] = value;
  }
  return content;
}

export function recordEtag(record) {
  const content = recordContent(record);
  return `W/"${sha256(canonicalStringify(content)).slice(0, 24)}"`;
}

function nextRecordEtag(record, previousEtag) {
  return `W/"${sha256(canonicalStringify({
    content: recordContent(record),
    previousEtag,
  })).slice(0, 24)}"`;
}

export class VirtualClock {
  constructor(epoch = DEFAULT_EPOCH) {
    if (!explicitDateTime(epoch)) throw new TypeError(`Invalid virtual epoch: ${epoch}`);
    const parsed = Date.parse(epoch);
    this.epochMs = parsed;
    this.currentMs = parsed;
  }

  now() {
    return new Date(this.currentMs).toISOString();
  }

  valueOf() {
    return this.currentMs;
  }

  advance(milliseconds) {
    if (!Number.isFinite(milliseconds) || milliseconds < 0) {
      throw new TypeError("Virtual time advances must be non-negative");
    }
    this.currentMs += Math.floor(milliseconds);
    return this.now();
  }

  reset() {
    this.currentMs = this.epochMs;
    return this.now();
  }
}

export class TwinTransportError extends Error {
  constructor(code, message, options = {}) {
    super(message);
    this.name = "TwinTransportError";
    this.code = code;
    this.retryable = options.retryable !== false;
    this.requestId = options.requestId || null;
    this.committed = Boolean(options.committed);
  }
}

export class TwinRetryExhaustedError extends Error {
  constructor(attempts, lastResult) {
    super(`Retry budget exhausted after ${attempts} attempts`);
    this.name = "TwinRetryExhaustedError";
    this.attempts = attempts;
    this.lastResult = lastResult;
  }
}

function normalizeHeaders(headers = {}) {
  const normalized = {};
  for (const [key, value] of Object.entries(headers || {})) {
    normalized[String(key).toLowerCase()] = String(value);
  }
  return normalized;
}

function normalizedRecordId(value) {
  let normalized = String(value ?? "").trim().toLowerCase();
  normalized = normalized.replace(/^['"]|['"]$/g, "").trim();
  if (normalized.startsWith("{") && normalized.endsWith("}")) {
    normalized = normalized.slice(1, -1).trim();
  }
  return normalized;
}

function boundAccountId(value) {
  const match = String(value ?? "").trim().match(
    /(?:^|\/)accounts\s*\(\s*(\{?[^{}()/?#]+\}?)\s*\)(?:[?#].*)?$/i,
  );
  return normalizedRecordId(match?.[1]);
}

function emailReferencesAccount(email, accountId) {
  const normalized = normalizedRecordId(accountId);
  return Boolean(normalized)
    && (
      normalizedRecordId(email?._regardingobjectid_value) === normalized
      || boundAccountId(email?.["regardingobjectid_account@odata.bind"]) === normalized
    );
}

function normalizeSeed(seed = {}) {
  const state = {};
  for (const entity of Object.keys(ENTITY_DEFINITIONS).sort()) {
    const source = seed[entity];
    const records = Array.isArray(source) ? source : source?.value;
    state[entity] = normalizeRecords(entity, Array.isArray(records) ? records : []);
  }
  return state;
}

function normalizeRecords(entity, records) {
  const definition = ENTITY_DEFINITIONS[entity];
  return records
    .filter((record) => record && typeof record === "object" && !Array.isArray(record))
    .map((source) => {
      const record = clone(source);
      record["@odata.etag"] = recordEtag(record);
      return record;
    })
    .sort((left, right) => compareCodeUnits(left[definition.primaryKey] || "", right[definition.primaryKey] || ""));
}

export function parsePath(path) {
  try {
    const source = String(path || "");
    decodeURIComponent(source);
    const parsed = new URL(source, "https://twin.local");
    let pathname = decodeURIComponent(parsed.pathname);
    const apiIndex = pathname.indexOf(API_PREFIX);
    if (apiIndex >= 0) pathname = pathname.slice(apiIndex + API_PREFIX.length);
    pathname = pathname.replace(/^\/+/, "").replace(/\.json$/, "");
    const match = pathname.match(/^([A-Za-z$][\w$]*)(?:\(([^)]+)\)|\/([^/]+))?$/);
    if (!match) return { error: `Unsupported D365 path: ${source}` };
    const id = (match[2] || match[3] || "").replace(/^['"]|['"]$/g, "");
    return { entity: match[1], id: id || null, query: parsed.searchParams };
  } catch {
    return { error: "The D365 path contains malformed URL encoding." };
  }
}

function errorResponse(status, code, message, requestId, at, target = null) {
  const error = { code, message };
  if (target) error.target = target;
  return {
    status,
    ok: false,
    headers: { "Content-Type": "application/json" },
    body: { error },
    requestId,
    at,
  };
}

function response(status, body, headers, requestId, at) {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { ...headers },
    body: body === undefined ? null : body,
    requestId,
    at,
  };
}

function parseBody(body) {
  if (body === undefined || body === null || body === "") return {};
  let value = body;
  if (typeof body === "string") {
    try {
      value = JSON.parse(body);
    } catch {
      return { error: "The request body is not valid JSON." };
    }
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { error: "The request body must be a JSON object." };
  }
  return { value: clone(value) };
}

function explicitDateTime(value) {
  if (typeof value !== "string") return false;
  const match = value.match(EXPLICIT_DATETIME_PATTERN);
  if (!match) return false;
  const [, year, month, day, hour, minute, second = "0", offsetHour = "0", offsetMinute = "0"] = match;
  const yearNumber = Number(year);
  const monthNumber = Number(month);
  const dayNumber = Number(day);
  const daysInMonth = new Date(Date.UTC(yearNumber, monthNumber, 0)).getUTCDate();
  if (monthNumber < 1 || monthNumber > 12 || dayNumber < 1 || dayNumber > daysInMonth) return false;
  if (Number(hour) > 23 || Number(minute) > 59 || Number(second) > 59) return false;
  if (Number(offsetHour) > 23 || Number(offsetMinute) > 59) return false;
  return Number.isFinite(Date.parse(value));
}

function validDateTime(value) {
  return value === null || explicitDateTime(value);
}

function valueMatchesType(value, type) {
  if (value === null) return true;
  if (type === "datetime") return validDateTime(value);
  return typeof value === type && (type !== "number" || Number.isFinite(value));
}

function validatePayload(entity, body, method) {
  const definition = ENTITY_DEFINITIONS[entity];
  const primaryKey = definition.primaryKey;
  for (const [key, value] of Object.entries(body)) {
    if (key === "@odata.etag" || key === primaryKey) {
      return `${key} is read-only.`;
    }
    if (!Object.hasOwn(definition.fields, key)) return `Unknown field '${key}' for ${entity}.`;
    if (!valueMatchesType(value, definition.fields[key])) {
      return `Field '${key}' must be ${definition.fields[key]}.`;
    }
  }
  if (method === "POST") {
    return validateRequiredFields(entity, body);
  }
  return null;
}

function validateRequiredFields(entity, record) {
  for (const required of ENTITY_DEFINITIONS[entity].required) {
    const value = record[required];
    if (value === undefined || value === null || (typeof value === "string" && value.trim() === "")) {
      return `Required field '${required}' is missing.`;
    }
  }
  return null;
}

function compareValues(left, right) {
  if (left === right) return 0;
  if (left === null || left === undefined) return -1;
  if (right === null || right === undefined) return 1;
  if (typeof left === "number" && typeof right === "number") return left - right;
  return compareCodeUnits(left, right);
}

function parseFilterLiteral(raw) {
  const value = raw.trim();
  if (value === "null") return null;
  if (value === "true") return true;
  if (value === "false") return false;
  if (/^-?\d+(?:\.\d+)?$/.test(value)) return Number(value);
  if (/^'.*'$/.test(value)) return value.slice(1, -1).replace(/''/g, "'");
  return value;
}

function applyFilter(records, rawFilter) {
  if (!rawFilter) return records;
  const contains = rawFilter.match(/^contains\(([\w@.]+),\s*'((?:''|[^'])*)'\)$/i);
  if (contains) {
    const needle = contains[2].replace(/''/g, "'").toLowerCase();
    return records.filter((record) => String(record[contains[1]] ?? "").toLowerCase().includes(needle));
  }
  const equals = rawFilter.match(/^([\w@.]+)\s+eq\s+(.+)$/i);
  if (equals) {
    const expected = parseFilterLiteral(equals[2]);
    return records.filter((record) => record[equals[1]] === expected);
  }
  return records;
}

function selectFields(record, select, primaryKey) {
  if (!select) return clone(record);
  const selected = { "@odata.etag": record["@odata.etag"], [primaryKey]: record[primaryKey] };
  for (const field of select.split(",").map((value) => value.trim()).filter(Boolean)) {
    if (Object.hasOwn(record, field)) selected[field] = record[field];
  }
  return selected;
}

function retryAfterMilliseconds(result, nowMs) {
  const value = result?.headers?.["Retry-After"];
  if (!value) return null;
  if (/^\d+(?:\.\d+)?$/.test(value)) return Math.max(0, Math.round(Number(value) * 1000));
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? Math.max(0, parsed - nowMs) : null;
}

function replayableRequest(spec) {
  const copy = clone({
    method: spec.method,
    path: spec.path,
    body: spec.body,
    headers: spec.headers,
    logicalRequestId: spec.logicalRequestId,
    clientId: spec.clientId,
    fault: spec.fault,
    timeoutMs: spec.timeoutMs,
  });
  return copy;
}

export class TwinCore {
  constructor(options = {}) {
    this.epoch = options.epoch || options.clock?.now?.() || DEFAULT_EPOCH;
    if (!explicitDateTime(this.epoch)) throw new TypeError(`Invalid virtual epoch: ${this.epoch}`);
    this.clock = options.clock || new VirtualClock(this.epoch);
    this.seedName = options.seedName || "rappterbook-d365";
    this._seed = normalizeSeed(options.seed || {});
    this._originSeed = clone(this._seed);
    this._state = clone(this._seed);
    this._trace = [];
    this._replayLog = [];
    this._idempotency = new Map();
    this._eventSequence = 0;
    this._requestSequence = 0;
  }

  now() {
    return this.clock.now();
  }

  installSeedEntity(entity, payload, options = {}) {
    if (!ENTITY_DEFINITIONS[entity]) throw new TypeError(`Unknown entity set: ${entity}`);
    const records = Array.isArray(payload) ? payload : payload?.value;
    if (!Array.isArray(records)) throw new TypeError(`${entity} seed payload must contain a value array`);
    const normalized = normalizeRecords(entity, records);
    this._recordAction({ kind: "install", entity, records: normalized }, options.recordAction !== false);
    const idempotencyEntriesInvalidated = this._idempotency.size;
    this._idempotency.clear();
    this._seed[entity] = clone(normalized);
    this._state[entity] = clone(normalized);
    this._event("seed.installed", { entity, count: normalized.length, idempotencyEntriesInvalidated });
    return normalized.length;
  }

  metadata() {
    return {
      "@odata.context": "https://rappterbook.crm.dynamics.com/api/data/v9.2/$metadata",
      EntitySets: Object.keys(ENTITY_DEFINITIONS).sort().map((name) => ({
        name,
        entityType: `mscrm.${name.replace(/s$/, "")}`,
        recordCount: this._state[name].length,
      })),
      _snapshot: `sha256:${this.stateDigest()}`,
    };
  }

  getState(entity = null) {
    if (entity) return clone(this._state[entity] || []);
    return clone(this._state);
  }

  getTrace() {
    return clone(this._trace);
  }

  getReplayLog() {
    return clone(this._replayLog);
  }

  stateDigest() {
    const canonical = {};
    for (const entity of Object.keys(this._state).sort()) {
      const primaryKey = ENTITY_DEFINITIONS[entity].primaryKey;
      canonical[entity] = [...this._state[entity]].sort((a, b) => compareCodeUnits(a[primaryKey], b[primaryKey]));
    }
    return sha256(canonicalStringify(canonical));
  }

  traceDigest() {
    return sha256(canonicalStringify(this._trace));
  }

  digest() {
    return sha256(canonicalStringify({
      clock: this.now(),
      state: this._state,
      trace: this._trace,
    }));
  }

  snapshot() {
    return {
      at: this.now(),
      state: this.getState(),
      stateDigest: this.stateDigest(),
      traceDigest: this.traceDigest(),
    };
  }

  diff(before, after = this._state) {
    const left = before?.state || before;
    const right = after?.state || after;
    return diffStates(left, right);
  }

  _event(type, fields = {}) {
    const event = {
      sequence: ++this._eventSequence,
      at: this.now(),
      type,
      ...clone(fields),
    };
    this._trace.push(event);
    return event;
  }

  _nextRequestId() {
    this._requestSequence += 1;
    return `req-${String(this._requestSequence).padStart(5, "0")}`;
  }

  _observeRequestId(requestId) {
    const match = String(requestId).match(/^req-(\d+)$/);
    if (!match) return;
    const observed = Number(match[1]);
    if (Number.isSafeInteger(observed)) this._requestSequence = Math.max(this._requestSequence, observed);
  }

  _recordAction(action, enabled) {
    if (enabled) this._replayLog.push(clone(action));
  }

  _findIndex(entity, id) {
    const primaryKey = ENTITY_DEFINITIONS[entity].primaryKey;
    const normalized = String(id).toLowerCase();
    return this._state[entity].findIndex((record) => String(record[primaryKey]).toLowerCase() === normalized);
  }

  _sortEntity(entity) {
    const primaryKey = ENTITY_DEFINITIONS[entity].primaryKey;
    this._state[entity].sort((a, b) => compareCodeUnits(a[primaryKey], b[primaryKey]));
  }

  _fingerprint(spec, parsedBody) {
    return sha256(canonicalStringify({
      method: spec.method,
      path: spec.path,
      body: parsedBody,
      ifMatch: normalizeHeaders(spec.headers)["if-match"] || null,
    }));
  }

  async request(spec) {
    return this._request(spec, true);
  }

  async _request(input, recordAction) {
    const spec = { ...input };
    spec.method = String(spec.method || "GET").toUpperCase();
    spec.path = spec.path || "/";
    spec.logicalRequestId = spec.logicalRequestId || spec.requestId || this._nextRequestId();
    this._observeRequestId(spec.logicalRequestId);
    spec.clientId = spec.clientId || "browser";
    this._recordAction({ kind: "request", spec: replayableRequest(spec) }, recordAction);
    const requestId = spec.logicalRequestId;
    const path = parsePath(spec.path);
    this._event("request.received", {
      requestId,
      clientId: spec.clientId,
      method: spec.method,
      path: spec.path,
    });
    if (path.error) return this._failure(400, ERROR_CODES.badRequest, path.error, spec);
    if (spec.method === "GET" && path.entity === "$metadata") {
      return this._complete(response(200, this.metadata(), { "Content-Type": "application/json" }, requestId, this.now()), spec);
    }
    if (spec.method === "GET" && path.entity.toLowerCase() === "whoami") {
      const body = { ...WHO_AM_I };
      return this._complete(response(200, body, {}, requestId, this.now()), spec);
    }
    if (!ENTITY_DEFINITIONS[path.entity]) {
      return this._failure(404, ERROR_CODES.notFound, `Entity set '${path.entity}' was not found.`, spec);
    }
    const bodyResult = parseBody(spec.body);
    if (bodyResult.error && ["POST", "PATCH"].includes(spec.method)) {
      return this._failure(400, ERROR_CODES.badRequest, bodyResult.error, spec);
    }
    const parsedBody = bodyResult.value || {};
    if (["POST", "PATCH"].includes(spec.method)) {
      const validationError = validatePayload(path.entity, parsedBody, spec.method);
      if (validationError) return this._failure(400, ERROR_CODES.badRequest, validationError, spec);
    }
    const fingerprint = this._fingerprint(spec, parsedBody);
    const faultResult = this._applyPreFault(spec);
    if (faultResult) return this._complete(faultResult, spec);
    if (["POST", "PATCH", "DELETE"].includes(spec.method)) {
      const cached = this._idempotency.get(requestId);
      if (cached) {
        if (cached.fingerprint !== fingerprint) {
          return this._failure(409, ERROR_CODES.conflict, "Logical request ID was reused with different content.", spec);
        }
        this._event("idempotency.replayed", { requestId, entity: path.entity });
        return this._complete(clone(cached.response), spec, true);
      }
    }
    if (spec.method === "GET") return this._get(path, spec);
    if (spec.method === "POST" && !path.id) return this._post(path.entity, parsedBody, fingerprint, spec);
    if (spec.method === "PATCH" && path.id) return this._patch(path.entity, path.id, parsedBody, fingerprint, spec);
    if (spec.method === "DELETE" && path.id) return this._delete(path.entity, path.id, fingerprint, spec);
    return this._failure(400, ERROR_CODES.badRequest, `Unsupported operation ${spec.method} ${spec.path}.`, spec);
  }

  _failure(status, code, message, spec, target = null) {
    this._event("request.failed", {
      requestId: spec.logicalRequestId,
      status,
      code,
      message,
    });
    return errorResponse(status, code, message, spec.logicalRequestId, this.now(), target);
  }

  _complete(result, spec, replayed = false) {
    result.at = this.now();
    if (replayed) result.replayed = true;
    this._event("request.completed", {
      requestId: spec.logicalRequestId,
      status: result.status,
      replayed,
    });
    return result;
  }

  _applyPreFault(spec) {
    const fault = spec.fault;
    if (!fault || fault.type === "none") return null;
    const requestId = spec.logicalRequestId;
    if (fault.type === "delay") {
      const delayMs = Math.max(0, Number(fault.delayMs || 0));
      const timeoutMs = Number(fault.timeoutMs ?? spec.timeoutMs ?? Number.POSITIVE_INFINITY);
      this._event("fault.injected", { requestId, fault: "delay", delayMs, timeoutMs });
      if (delayMs > timeoutMs) {
        this._advanceClock(timeoutMs, "request.timeout", false, false);
        this._event("transport.failed", { requestId, code: "TIMEOUT", committed: false });
        throw new TwinTransportError("TIMEOUT", `Virtual request timed out after ${timeoutMs}ms`, { requestId });
      }
      this._advanceClock(delayMs, "request.delay", false, false);
      return null;
    }
    if (fault.type === "network" || fault.type === "timeout" || fault.type === "malformed") {
      const code = fault.type === "network" ? "NETWORK_ERROR" : fault.type === "timeout" ? "TIMEOUT" : "MALFORMED_RESPONSE";
      if (fault.type === "timeout") this._advanceClock(Number(fault.delayMs || spec.timeoutMs || 1000), "request.timeout", false, false);
      this._event("fault.injected", { requestId, fault: fault.type });
      this._event("transport.failed", { requestId, code, committed: false });
      throw new TwinTransportError(code, fault.message || `Injected ${fault.type} fault`, { requestId });
    }
    const status = Number(fault.status || (fault.type === "429" ? 429 : fault.type === "503" ? 503 : 0));
    if (status === 429 || status === 503) {
      const code = status === 429 ? ERROR_CODES.tooMany : ERROR_CODES.unavailable;
      const message = fault.message || (status === 429 ? "Too many requests." : "Service temporarily unavailable.");
      const headers = { "Content-Type": "application/json" };
      if (fault.retryAfterMs !== undefined) headers["Retry-After"] = String(Number(fault.retryAfterMs) / 1000);
      else if (fault.retryAfter !== undefined) headers["Retry-After"] = String(fault.retryAfter);
      this._event("fault.injected", { requestId, fault: `http-${status}` });
      this._event("request.failed", { requestId, status, code, message });
      const result = errorResponse(status, code, message, requestId, this.now());
      result.headers = headers;
      return result;
    }
    return null;
  }

  _get(path, spec) {
    const records = this._state[path.entity];
    const definition = ENTITY_DEFINITIONS[path.entity];
    if (path.id) {
      const index = this._findIndex(path.entity, path.id);
      if (index < 0) return this._failure(404, ERROR_CODES.notFound, `${path.entity}(${path.id}) was not found.`, spec);
      const record = clone(records[index]);
      const result = response(200, record, { ETag: record["@odata.etag"] }, spec.logicalRequestId, this.now());
      return this._complete(result, spec);
    }
    let selected = applyFilter(records, path.query.get("$filter"));
    const order = (path.query.get("$orderby") || "").trim().match(/^([\w@.]+)(?:\s+(asc|desc))?$/i);
    if (order) {
      const direction = order[2]?.toLowerCase() === "desc" ? -1 : 1;
      selected = [...selected].sort((a, b) => {
        const compared = compareValues(a[order[1]], b[order[1]]) * direction;
        return compared || compareValues(a[definition.primaryKey], b[definition.primaryKey]);
      });
    }
    const count = selected.length;
    const skip = Math.max(0, Number(path.query.get("$skip") || 0));
    const topValue = path.query.get("$top");
    const top = topValue === null ? count : Math.max(0, Number(topValue));
    const select = path.query.get("$select");
    const value = selected.slice(skip, skip + top).map((record) => selectFields(record, select, definition.primaryKey));
    const body = {
      "@odata.context": `https://rappterbook.crm.dynamics.com/api/data/v9.2/$metadata#${path.entity}`,
      "@odata.count": count,
      value,
    };
    return this._complete(response(200, body, {}, spec.logicalRequestId, this.now()), spec);
  }

  _newRecord(entity, body, spec) {
    const definition = ENTITY_DEFINITIONS[entity];
    const primaryKey = definition.primaryKey;
    const now = this.now();
    const record = { ...clone(definition.defaults), ...clone(body) };
    record[primaryKey] = deterministicGuid(`${this.seedName}|${entity}|${spec.logicalRequestId}`);
    if (Object.hasOwn(definition.fields, "createdon") && record.createdon === undefined) record.createdon = now;
    if (Object.hasOwn(definition.fields, "modifiedon") && record.modifiedon === undefined) record.modifiedon = now;
    if (entity === "contacts") {
      record.lastname = record.lastname || "";
      record.fullname = record.fullname || `${record.firstname} ${record.lastname}`.trim();
    }
    record["@odata.etag"] = recordEtag(record);
    return record;
  }

  _post(entity, body, fingerprint, spec) {
    const definition = ENTITY_DEFINITIONS[entity];
    const primaryKey = definition.primaryKey;
    const record = this._newRecord(entity, body, spec);
    if (this._findIndex(entity, record[primaryKey]) >= 0) {
      return this._failure(409, ERROR_CODES.conflict, `A ${entity} record with this deterministic ID already exists.`, spec);
    }
    this._state[entity].push(record);
    this._sortEntity(entity);
    this._event("commit.created", {
      requestId: spec.logicalRequestId,
      entity,
      recordId: record[primaryKey],
      etag: record["@odata.etag"],
    });
    const prefer = normalizeHeaders(spec.headers).prefer || "";
    const representation = /return=representation/i.test(prefer);
    const status = representation ? 201 : 204;
    const result = response(status, representation ? clone(record) : null, {
      ETag: record["@odata.etag"],
      "OData-EntityId": `${API_PREFIX}${entity}(${record[primaryKey]})`,
    }, spec.logicalRequestId, this.now());
    return this._cacheAndComplete(fingerprint, result, spec, entity, record[primaryKey]);
  }

  _checkEtag(record, spec) {
    const ifMatch = normalizeHeaders(spec.headers)["if-match"];
    return !ifMatch || ifMatch === "*" || ifMatch === record["@odata.etag"];
  }

  _patch(entity, id, body, fingerprint, spec) {
    const index = this._findIndex(entity, id);
    if (index < 0) return this._failure(404, ERROR_CODES.notFound, `${entity}(${id}) was not found.`, spec);
    const current = this._state[entity][index];
    if (!this._checkEtag(current, spec)) {
      return this._failure(412, ERROR_CODES.precondition, "The row version does not match the current ETag.", spec);
    }
    const definition = ENTITY_DEFINITIONS[entity];
    const updated = { ...current, ...clone(body) };
    const requiredError = validateRequiredFields(entity, updated);
    if (requiredError) return this._failure(400, ERROR_CODES.badRequest, requiredError, spec);
    if (Object.hasOwn(definition.fields, "modifiedon")) updated.modifiedon = this.now();
    if (entity === "contacts" && (body.firstname !== undefined || body.lastname !== undefined)) {
      updated.fullname = `${updated.firstname || ""} ${updated.lastname || ""}`.trim();
    }
    updated["@odata.etag"] = nextRecordEtag(updated, current["@odata.etag"]);
    this._state[entity][index] = updated;
    this._sortEntity(entity);
    this._event("commit.updated", {
      requestId: spec.logicalRequestId,
      entity,
      recordId: id,
      previousEtag: current["@odata.etag"],
      etag: updated["@odata.etag"],
    });
    const representation = /return=representation/i.test(normalizeHeaders(spec.headers).prefer || "");
    const result = response(representation ? 200 : 204, representation ? clone(updated) : null, {
      ETag: updated["@odata.etag"],
    }, spec.logicalRequestId, this.now());
    return this._cacheAndComplete(fingerprint, result, spec, entity, id);
  }

  _delete(entity, id, fingerprint, spec) {
    const index = this._findIndex(entity, id);
    if (index < 0) return this._failure(404, ERROR_CODES.notFound, `${entity}(${id}) was not found.`, spec);
    const current = this._state[entity][index];
    if (!this._checkEtag(current, spec)) {
      return this._failure(412, ERROR_CODES.precondition, "The row version does not match the current ETag.", spec);
    }
    if (entity === "contacts" && (this._state.connections || []).some((connection) => {
      const contactId = String(id).toLowerCase();
      return String(connection._record1id_value || "").toLowerCase() === contactId
        || String(connection._record2id_value || "").toLowerCase() === contactId;
    })) {
      return this._failure(
        409,
        ERROR_CODES.conflict,
        "The contact cannot be deleted because a Connection record references it. Deactivate the contact instead.",
        spec,
      );
    }
    if (entity === "accounts" && (this._state.emails || []).some((email) =>
      emailReferencesAccount(email, id))) {
      return this._failure(
        409,
        ERROR_CODES.conflict,
        "The account cannot be deleted because an Email record references it. Deactivate the account instead.",
        spec,
      );
    }
    this._state[entity].splice(index, 1);
    this._event("commit.deleted", { requestId: spec.logicalRequestId, entity, recordId: id });
    const result = response(204, null, {}, spec.logicalRequestId, this.now());
    return this._cacheAndComplete(fingerprint, result, spec, entity, id);
  }

  _cacheAndComplete(fingerprint, result, spec, entity, recordId) {
    this._idempotency.set(spec.logicalRequestId, { fingerprint, response: clone(result) });
    if (spec.fault?.type === "postCommitLoss") {
      this._event("fault.injected", {
        requestId: spec.logicalRequestId,
        fault: "post-commit-response-loss",
        entity,
        recordId,
      });
      this._event("transport.failed", {
        requestId: spec.logicalRequestId,
        code: "POST_COMMIT_RESPONSE_LOSS",
        committed: true,
      });
      throw new TwinTransportError("POST_COMMIT_RESPONSE_LOSS", "The response was lost after commit.", {
        requestId: spec.logicalRequestId,
        committed: true,
      });
    }
    return this._complete(result, spec);
  }

  async requestWithRetry(input, options = {}) {
    const spec = { ...input };
    spec.logicalRequestId = spec.logicalRequestId || spec.requestId || this._nextRequestId();
    spec.clientId = spec.clientId || "browser";
    const policy = {
      maxAttempts: Math.max(1, Number(options.maxAttempts || 4)),
      baseDelayMs: Math.max(0, Number(options.baseDelayMs ?? 250)),
      maxDelayMs: Math.max(0, Number(options.maxDelayMs ?? 8000)),
      faults: clone(options.faults || []),
    };
    this._recordAction({ kind: "retry", spec: replayableRequest(spec), policy }, options.recordAction !== false);
    let lastResult = null;
    for (let attempt = 1; attempt <= policy.maxAttempts; attempt += 1) {
      const fault = policy.faults[attempt - 1] || null;
      try {
        const result = await this._request({ ...spec, fault }, false);
        lastResult = result;
        if (![429, 503].includes(result.status)) return result;
      } catch (error) {
        if (!(error instanceof TwinTransportError) || !error.retryable) throw error;
        lastResult = { error: { code: error.code, message: error.message, committed: error.committed } };
      }
      if (attempt >= policy.maxAttempts) break;
      const retryAfter = retryAfterMilliseconds(lastResult, Number(this.clock.valueOf()));
      const exponential = Math.min(policy.maxDelayMs, policy.baseDelayMs * (2 ** (attempt - 1)));
      const delayMs = retryAfter ?? exponential;
      this._event("retry.scheduled", {
        requestId: spec.logicalRequestId,
        attempt,
        nextAttempt: attempt + 1,
        delayMs,
        reason: lastResult.status || lastResult.error?.code || "retryable",
      });
      this._advanceClock(delayMs, "retry.backoff", false, false);
    }
    this._event("retry.exhausted", {
      requestId: spec.logicalRequestId,
      attempts: policy.maxAttempts,
    });
    throw new TwinRetryExhaustedError(policy.maxAttempts, clone(lastResult));
  }

  advanceTime(milliseconds, reason = "manual", options = {}) {
    this._recordAction({ kind: "advance", milliseconds, reason }, options.recordAction !== false);
    return this._advanceClock(milliseconds, reason, true, true);
  }

  _advanceClock(milliseconds, reason, transitions, traceClock) {
    const from = this.now();
    const to = this.clock.advance(Math.max(0, Number(milliseconds || 0)));
    if (traceClock) this._event("clock.advanced", { from, to, milliseconds, reason });
    if (transitions) this._applyTransitions();
    return to;
  }

  _applyTransitions() {
    const nowMs = Number(this.clock.valueOf());
    const transitionTargets = [];
    for (const incident of this._state.incidents) {
      const due = Date.parse(incident.new_sla_due || "");
      if (incident.statecode === 0 && incident.new_sla_status !== "Breached" && Number.isFinite(due) && due <= nowMs) {
        transitionTargets.push({ entity: "incidents", record: incident, transition: "sla.breached" });
      }
    }
    transitionTargets.sort((a, b) => {
      const aId = a.record[ENTITY_DEFINITIONS[a.entity].primaryKey];
      const bId = b.record[ENTITY_DEFINITIONS[b.entity].primaryKey];
      return compareCodeUnits(`${a.entity}:${aId}`, `${b.entity}:${bId}`);
    });
    for (const target of transitionTargets) this._applyTransition(target);
  }

  _applyTransition(target) {
    const definition = ENTITY_DEFINITIONS[target.entity];
    const primaryKey = definition.primaryKey;
    const index = this._findIndex(target.entity, target.record[primaryKey]);
    if (index < 0) return;
    const updated = { ...this._state[target.entity][index] };
    updated.new_sla_status = "Breached";
    updated.prioritycode = 1;
    if (Object.hasOwn(definition.fields, "modifiedon")) updated.modifiedon = this.now();
    updated["@odata.etag"] = nextRecordEtag(updated, this._state[target.entity][index]["@odata.etag"]);
    this._state[target.entity][index] = updated;
    this._event("transition.applied", {
      entity: target.entity,
      recordId: updated[primaryKey],
      transition: target.transition,
      etag: updated["@odata.etag"],
    });
  }

  reset(options = {}) {
    this._recordAction({ kind: "reset" }, options.recordAction !== false);
    this._state = clone(this._seed);
    this._idempotency.clear();
    this._requestSequence = 0;
    if (typeof this.clock.reset === "function") this.clock.reset();
    this._event("system.reset", { stateDigest: this.stateDigest() });
    return this.snapshot();
  }

  exportReplay() {
    return {
      epoch: this.epoch,
      seedName: this.seedName,
      seed: clone(this._originSeed),
      actions: this.getReplayLog(),
    };
  }

  static async replay(replay) {
    const twin = new TwinCore({ epoch: replay.epoch, seedName: replay.seedName, seed: replay.seed });
    for (const action of replay.actions || []) {
      try {
        if (action.kind === "install") twin.installSeedEntity(action.entity, action.records);
        else if (action.kind === "request") await twin._request(action.spec, true);
        else if (action.kind === "retry") await twin.requestWithRetry(action.spec, { ...action.policy, recordAction: true });
        else if (action.kind === "advance") twin.advanceTime(action.milliseconds, action.reason);
        else if (action.kind === "reset") twin.reset();
      } catch (error) {
        if (!(error instanceof TwinTransportError || error instanceof TwinRetryExhaustedError)) throw error;
      }
    }
    return twin;
  }
}

export function diffStates(before = {}, after = {}) {
  const changes = [];
  const entities = new Set([...Object.keys(before || {}), ...Object.keys(after || {})]);
  for (const entity of [...entities].sort()) {
    const definition = ENTITY_DEFINITIONS[entity];
    if (!definition) continue;
    const primaryKey = definition.primaryKey;
    const left = new Map((before[entity] || []).map((record) => [String(record[primaryKey]), record]));
    const right = new Map((after[entity] || []).map((record) => [String(record[primaryKey]), record]));
    const ids = new Set([...left.keys(), ...right.keys()]);
    for (const id of [...ids].sort()) {
      const previous = left.get(id);
      const current = right.get(id);
      if (!previous) changes.push({ entity, id, kind: "created", before: null, after: clone(current) });
      else if (!current) changes.push({ entity, id, kind: "deleted", before: clone(previous), after: null });
      else if (canonicalStringify(previous) !== canonicalStringify(current)) {
        const fields = [];
        const keys = new Set([...Object.keys(previous), ...Object.keys(current)]);
        for (const field of [...keys].sort()) {
          if (canonicalStringify(previous[field] ?? null) !== canonicalStringify(current[field] ?? null)) {
            fields.push({ field, before: previous[field] ?? null, after: current[field] ?? null });
          }
        }
        changes.push({ entity, id, kind: "updated", fields, before: clone(previous), after: clone(current) });
      }
    }
  }
  return changes;
}

function assertion(label, pass, actual, expected) {
  return { label, pass: Boolean(pass), actual, expected };
}

async function happyScenario(twin) {
  const created = await twin.request({
    method: "POST",
    path: "/api/data/v9.2/contacts",
    logicalRequestId: "scenario-happy-create",
    headers: { Prefer: "return=representation" },
    body: { firstname: "Avery", lastname: "Stone", emailaddress1: "avery@example.test", jobtitle: "Support Engineer" },
  });
  const id = created.body.contactid;
  const read = await twin.request({ method: "GET", path: `/contacts(${id})`, logicalRequestId: "scenario-happy-read" });
  const patched = await twin.request({
    method: "PATCH",
    path: `/contacts(${id})`,
    logicalRequestId: "scenario-happy-update",
    headers: { "If-Match": read.headers.ETag, Prefer: "return=representation" },
    body: { description: "Created by the deterministic happy-path scenario." },
  });
  const removed = await twin.request({
    method: "DELETE",
    path: `/contacts(${id})`,
    logicalRequestId: "scenario-happy-delete",
    headers: { "If-Match": patched.headers.ETag },
  });
  return [
    assertion("Create returns a representation", created.status === 201, created.status, 201),
    assertion("Read uses the same GUID", read.body.contactid === id, read.body.contactid, id),
    assertion("Patch changes the ETag", patched.headers.ETag !== read.headers.ETag, patched.headers.ETag, "new ETag"),
    assertion("Delete succeeds", removed.status === 204, removed.status, 204),
  ];
}

async function malformedScenario(twin) {
  const before = twin.stateDigest();
  const result = await twin.request({
    method: "POST",
    path: "/contacts",
    logicalRequestId: "scenario-malformed",
    body: '{"firstname":',
  });
  return [
    assertion("Malformed JSON returns 400", result.status === 400, result.status, 400),
    assertion("Malformed JSON does not mutate state", twin.stateDigest() === before, twin.stateDigest(), before),
  ];
}

async function retryScenario(twin) {
  const startsBefore = twin.getTrace().length;
  const result = await twin.requestWithRetry({
    method: "POST",
    path: "/tasks",
    logicalRequestId: "scenario-retry",
    headers: { Prefer: "return=representation" },
    body: { subject: "Call the customer after deterministic retries" },
  }, {
    baseDelayMs: 250,
    maxAttempts: 4,
    faults: [{ type: "503" }, { type: "429", retryAfterMs: 2000 }],
  });
  const trace = twin.getTrace().slice(startsBefore);
  return [
    assertion("Retry eventually succeeds", result.status === 201, result.status, 201),
    assertion("Exactly two retries are scheduled", trace.filter((event) => event.type === "retry.scheduled").length === 2,
      trace.filter((event) => event.type === "retry.scheduled").length, 2),
    assertion("Mutation commits once", trace.filter((event) => event.type === "commit.created").length === 1,
      trace.filter((event) => event.type === "commit.created").length, 1),
  ];
}

async function staleScenario(twin) {
  const created = await twin.request({
    method: "POST", path: "/tasks", logicalRequestId: "scenario-stale-create",
    headers: { Prefer: "return=representation" }, body: { subject: "Resolve a two-client conflict" },
  });
  const id = created.body.activityid;
  const etag = created.headers.ETag;
  const first = await twin.request({
    method: "PATCH", path: `/tasks(${id})`, logicalRequestId: "scenario-stale-a",
    headers: { "If-Match": etag, Prefer: "return=representation" }, clientId: "client-a",
    body: { description: "Client A won." },
  });
  const second = await twin.request({
    method: "PATCH", path: `/tasks(${id})`, logicalRequestId: "scenario-stale-b",
    headers: { "If-Match": etag }, clientId: "client-b", body: { description: "Client B was stale." },
  });
  return [
    assertion("First client saves", first.status === 200, first.status, 200),
    assertion("Second client receives 412", second.status === 412, second.status, 412),
  ];
}

async function timeScenario(twin) {
  const due = new Date(Number(twin.clock.valueOf()) + 60_000).toISOString();
  const slaDue = new Date(Number(twin.clock.valueOf()) + 30_000).toISOString();
  const task = await twin.request({
    method: "POST", path: "/tasks", logicalRequestId: "scenario-time-task",
    headers: { Prefer: "return=representation" }, body: { subject: "SLA callback", scheduledend: due },
  });
  const incident = await twin.request({
    method: "POST", path: "/incidents", logicalRequestId: "scenario-time-case",
    headers: { Prefer: "return=representation" }, body: { title: "Response SLA", new_sla_due: slaDue, new_sla_status: "Active" },
  });
  twin.advanceTime(90_000, "scenario.virtual-time");
  const currentTask = await twin.request({ method: "GET", path: `/tasks(${task.body.activityid})`, logicalRequestId: "scenario-time-read-task" });
  const currentCase = await twin.request({ method: "GET", path: `/incidents(${incident.body.incidentid})`, logicalRequestId: "scenario-time-read-case" });
  return [
    assertion("Due task remains open", currentTask.body.statecode === 0, currentTask.body.statecode, 0),
    assertion("SLA breaches", currentCase.body.new_sla_status === "Breached", currentCase.body.new_sla_status, "Breached"),
  ];
}

async function chaosScenario(twin) {
  const traceStart = twin.getTrace().length;
  const result = await twin.requestWithRetry({
    method: "POST", path: "/tasks", logicalRequestId: "scenario-chaos-lost-response",
    headers: { Prefer: "return=representation" }, body: { subject: "Idempotent chaos task" },
  }, {
    baseDelayMs: 100,
    maxAttempts: 3,
    faults: [{ type: "postCommitLoss" }],
  });
  const commits = twin.getTrace().slice(traceStart).filter((event) =>
    event.type === "commit.created" && event.requestId === "scenario-chaos-lost-response");
  return [
    assertion("Lost response retry succeeds", result.status === 201, result.status, 201),
    assertion("Lost response applies once", commits.length === 1, commits.length, 1),
    assertion("Retry reports idempotent replay", result.replayed === true, result.replayed, true),
  ];
}

export const BUILT_IN_SCENARIOS = Object.freeze([
  { id: "happy-crud", label: "Happy CRUD", description: "Create, read, update, and delete one contact.", entities: ["contacts"] },
  { id: "malformed-payload", label: "Malformed payload", description: "Return 400 and prove state is unchanged.", entities: ["contacts"] },
  { id: "transient-retry", label: "503 → 429 → success", description: "Honor exponential backoff and Retry-After.", entities: ["tasks"] },
  { id: "stale-etag", label: "Two-client ETag conflict", description: "Client B receives a deterministic 412.", entities: ["tasks"] },
  { id: "virtual-time", label: "Task and SLA clock", description: "Advance UTC time; keep overdue tasks open and apply the SLA transition once.", entities: ["tasks", "incidents"] },
  { id: "chaos", label: "Lost response chaos", description: "Retry a post-commit response loss without double apply.", entities: ["tasks"] },
]);

export async function runBuiltInScenario(twin, scenarioId) {
  const runners = {
    "happy-crud": happyScenario,
    "malformed-payload": malformedScenario,
    "transient-retry": retryScenario,
    "stale-etag": staleScenario,
    "virtual-time": timeScenario,
    chaos: chaosScenario,
  };
  const runner = runners[scenarioId];
  if (!runner) throw new TypeError(`Unknown scenario: ${scenarioId}`);
  const definition = BUILT_IN_SCENARIOS.find((item) => item.id === scenarioId);
  const before = twin.snapshot();
  const traceStart = twin.getTrace().length;
  const assertions = await runner(twin);
  const after = twin.snapshot();
  return {
    id: scenarioId,
    label: definition.label,
    description: definition.description,
    before,
    after,
    diff: diffStates(before.state, after.state),
    assertions,
    passed: assertions.every((item) => item.pass),
    trace: twin.getTrace().slice(traceStart),
  };
}

export function createTwin(options = {}) {
  return new TwinCore(options);
}
