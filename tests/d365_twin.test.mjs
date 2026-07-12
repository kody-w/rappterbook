import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  TwinCore,
  TwinRetryExhaustedError,
  TwinTransportError,
  createTwin,
  deterministicGuid,
  runBuiltInScenario,
} from "../docs/d365/twin-core.mjs";
import {
  gridCodeLabel,
  isActiveEntityRoute,
  newestRelatedEmails,
} from "../docs/d365/app-helpers.mjs";

const EPOCH = "2026-04-05T10:00:00.000Z";

function fixtureSeed() {
  return {
    contacts: {
      value: [{
        contactid: "00000000-0000-0000-0000-000000000001",
        firstname: "Ada",
        lastname: "Lovelace",
        fullname: "Ada Lovelace",
        emailaddress1: "ada@example.test",
        statecode: 0,
        statuscode: 1,
      }],
    },
    tasks: { value: [] },
    incidents: { value: [] },
  };
}

test("runtime WhoAmI matches the committed simulation identity", async () => {
  const expected = JSON.parse(
    await readFile(new URL("../docs/api/data/v9.2/WhoAmI.json", import.meta.url), "utf8"),
  );
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  const result = await twin.request({
    method: "GET",
    path: "/api/data/v9.2/WhoAmI",
    logicalRequestId: "who-am-i",
  });

  assert.equal(result.status, 200);
  assert.deepEqual(result.body, expected);
});

test("related emails sort by newest valid date, stable ID, and a 25-record cap", () => {
  const emails = [
    { activityid: "same-b", createdon: "2026-07-10T10:00:00Z" },
    { activityid: "invalid-a", createdon: "not-a-date" },
    { activityid: "old", createdon: "2026-07-09T10:00:00Z" },
    { activityid: "null-b", createdon: null },
    { activityid: "new", createdon: "2026-07-11T10:00:00Z" },
    { activityid: "same-a", createdon: "2026-07-10T10:00:00Z" },
  ];
  const originalOrder = emails.map((email) => email.activityid);

  assert.deepEqual(
    newestRelatedEmails(emails).map((email) => email.activityid),
    ["new", "same-a", "same-b", "old", "invalid-a", "null-b"],
  );
  assert.deepEqual(
    newestRelatedEmails([...emails].reverse()).map((email) => email.activityid),
    ["new", "same-a", "same-b", "old", "invalid-a", "null-b"],
  );
  assert.deepEqual(emails.map((email) => email.activityid), originalOrder);
  const thirty = Array.from({ length: 30 }, (_, index) => ({
    activityid: String(index).padStart(2, "0"),
    createdon: new Date(Date.UTC(2026, 0, index + 1)).toISOString(),
  }));
  assert.equal(newestRelatedEmails(thirty).length, 25);
  assert.equal(newestRelatedEmails(thirty)[0].activityid, "29");
});

test("grid code labels remain entity-specific", () => {
  assert.deepEqual(
    [0, 1, 2].map((value) => gridCodeLabel("tasks", "statecode", value)),
    ["Open", "Completed", "Canceled"],
  );
  assert.deepEqual(
    [0, 1, 2].map((value) => gridCodeLabel("tasks", "prioritycode", value)),
    ["Low", "Normal", "High"],
  );
  assert.deepEqual(
    [1, 2, 3].map((value) => gridCodeLabel("incidents", "prioritycode", value)),
    ["High", "Normal", "Low"],
  );
  assert.deepEqual(
    [0, 1, 2].map((value) => gridCodeLabel("incidents", "statecode", value)),
    ["Active", "Resolved", "Canceled"],
  );
  assert.equal(gridCodeLabel("contacts", "statecode", 1), "Inactive");
  assert.equal(gridCodeLabel("accounts", "statecode", 1), "Inactive");
});

test("entity route guard rejects stale refresh completions", () => {
  const route = { view: "entity", entity: "contacts" };
  assert.equal(isActiveEntityRoute(7, route, 7, "contacts"), true);
  assert.equal(isActiveEntityRoute(8, route, 7, "contacts"), false);
  assert.equal(isActiveEntityRoute(7, { ...route, entity: "accounts" }, 7, "contacts"), false);
  assert.equal(isActiveEntityRoute(7, { view: "dashboard" }, 7, "contacts"), false);
});

async function deterministicRun() {
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH, seedName: "test-seed" });
  const created = await twin.request({
    method: "POST",
    path: "/api/data/v9.2/tasks",
    logicalRequestId: "det-create",
    headers: { Prefer: "return=representation" },
    body: { subject: "Deterministic callback", scheduledend: "2026-04-05T10:05:00.000Z" },
  });
  const patched = await twin.request({
    method: "PATCH",
    path: `/tasks(${created.body.activityid})`,
    logicalRequestId: "det-patch",
    headers: { "If-Match": created.headers.ETag, Prefer: "return=representation" },
    body: { description: "Updated exactly once." },
  });
  twin.advanceTime(300_000, "test.due");
  return { twin, created, patched };
}

test("same seed, epoch, and requests produce identical complete runs", async () => {
  const first = await deterministicRun();
  const second = await deterministicRun();

  assert.deepEqual(first.created, second.created);
  assert.deepEqual(first.patched, second.patched);
  assert.deepEqual(first.twin.getTrace(), second.twin.getTrace());
  assert.deepEqual(first.twin.getState(), second.twin.getState());
  assert.equal(first.twin.stateDigest(), second.twin.stateDigest());
  assert.equal(first.twin.traceDigest(), second.twin.traceDigest());
  assert.equal(first.twin.digest(), second.twin.digest());
});

test("happy CRUD is idempotent and each mutation traces one commit", async () => {
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  const createSpec = {
    method: "POST",
    path: "/contacts",
    logicalRequestId: "crud-create",
    headers: { Prefer: "return=representation" },
    body: { firstname: "Grace", lastname: "Hopper", emailaddress1: "grace@example.test" },
  };
  const created = await twin.request(createSpec);
  const duplicate = await twin.request(createSpec);
  assert.equal(created.status, 201);
  assert.equal(duplicate.replayed, true);
  assert.equal(created.body.contactid, deterministicGuid("rappterbook-d365|contacts|crud-create"));

  const read = await twin.request({
    method: "GET",
    path: `/contacts(${created.body.contactid})`,
    logicalRequestId: "crud-read",
  });
  const patched = await twin.request({
    method: "PATCH",
    path: `/contacts(${created.body.contactid})`,
    logicalRequestId: "crud-patch",
    headers: { "If-Match": read.headers.ETag, Prefer: "return=representation" },
    body: { jobtitle: "Rear Admiral" },
  });
  const removed = await twin.request({
    method: "DELETE",
    path: `/contacts(${created.body.contactid})`,
    logicalRequestId: "crud-delete",
    headers: { "If-Match": patched.headers.ETag },
  });

  assert.equal(read.status, 200);
  assert.equal(patched.body.jobtitle, "Rear Admiral");
  assert.equal(removed.status, 204);
  assert.deepEqual(
    twin.getTrace().filter((event) => event.type.startsWith("commit.")).map((event) => event.type),
    ["commit.created", "commit.updated", "commit.deleted"],
  );
});

test("invalid JSON, fields, and types return 400 without state mutation", async () => {
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  const before = twin.stateDigest();
  const requests = [
    { logicalRequestId: "bad-json", body: '{"firstname":' },
    { logicalRequestId: "bad-field", body: { firstname: "Lin", surprise_admin: true } },
    { logicalRequestId: "bad-type", body: { firstname: "Lin", new_karma: "many" } },
  ];

  for (const request of requests) {
    const result = await twin.request({ method: "POST", path: "/contacts", ...request });
    assert.equal(result.status, 400);
    assert.match(result.body.error.code, /^0x/);
    assert.equal(twin.stateDigest(), before);
  }
  assert.equal(twin.getTrace().filter((event) => event.type.startsWith("commit.")).length, 0);
});

test("two clients sharing an ETag yield one update and one 412", async () => {
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  const id = fixtureSeed().contacts.value[0].contactid;
  const readerA = await twin.request({ method: "GET", path: `/contacts(${id})`, clientId: "a", logicalRequestId: "read-a" });
  const readerB = await twin.request({ method: "GET", path: `/contacts(${id})`, clientId: "b", logicalRequestId: "read-b" });
  assert.equal(readerA.headers.ETag, readerB.headers.ETag);

  const winner = await twin.request({
    method: "PATCH", path: `/contacts(${id})`, clientId: "a", logicalRequestId: "write-a",
    headers: { "If-Match": readerA.headers.ETag, Prefer: "return=representation" },
    body: { description: "Client A won." },
  });
  const stale = await twin.request({
    method: "PATCH", path: `/contacts(${id})`, clientId: "b", logicalRequestId: "write-b",
    headers: { "If-Match": readerB.headers.ETag },
    body: { description: "Client B lost." },
  });

  assert.equal(winner.status, 200);
  assert.equal(stale.status, 412);
  assert.equal(stale.body.error.code, "0x80060882");
  assert.equal(twin.getTrace().filter((event) => event.type === "commit.updated").length, 1);
});

test("runtime ETags reject an original stale writer after an ABA value cycle", async () => {
  const seed = fixtureSeed();
  seed.contacts.value[0].description = "A";
  seed.contacts.value[0].modifiedon = EPOCH;
  const twin = createTwin({ seed, epoch: EPOCH });
  const id = seed.contacts.value[0].contactid;
  const original = await twin.request({
    method: "GET", path: `/contacts(${id})`, logicalRequestId: "aba-read",
  });
  const changed = await twin.request({
    method: "PATCH", path: `/contacts(${id})`, logicalRequestId: "aba-b",
    headers: { "If-Match": original.headers.ETag, Prefer: "return=representation" },
    body: { description: "B" },
  });
  const restored = await twin.request({
    method: "PATCH", path: `/contacts(${id})`, logicalRequestId: "aba-a",
    headers: { "If-Match": changed.headers.ETag, Prefer: "return=representation" },
    body: { description: "A" },
  });
  const stale = await twin.request({
    method: "PATCH", path: `/contacts(${id})`, logicalRequestId: "aba-stale",
    headers: { "If-Match": original.headers.ETag },
    body: { jobtitle: "Stale writer" },
  });

  assert.equal(restored.body.description, original.body.description);
  assert.equal(restored.body.modifiedon, original.body.modifiedon);
  assert.notEqual(restored.headers.ETag, original.headers.ETag);
  assert.equal(stale.status, 412);
  assert.equal(twin.getTrace().filter((event) => event.type === "commit.updated").length, 2);
});

test("PATCH validates required fields against the merged record before commit", async () => {
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  const contactId = fixtureSeed().contacts.value[0].contactid;
  const contact = await twin.request({
    method: "GET", path: `/contacts(${contactId})`, logicalRequestId: "required-contact-read",
  });
  const beforeContact = twin.stateDigest();
  const emptyContact = await twin.request({
    method: "PATCH", path: `/contacts(${contactId})`, logicalRequestId: "required-contact-empty",
    headers: { "If-Match": contact.headers.ETag },
    body: { firstname: "" },
  });
  assert.equal(emptyContact.status, 400);
  assert.equal(twin.stateDigest(), beforeContact);

  const task = await twin.request({
    method: "POST", path: "/tasks", logicalRequestId: "required-task-create",
    headers: { Prefer: "return=representation" }, body: { subject: "Required subject" },
  });
  const beforeTask = twin.stateDigest();
  const nullTask = await twin.request({
    method: "PATCH", path: `/tasks(${task.body.activityid})`, logicalRequestId: "required-task-null",
    headers: { "If-Match": task.headers.ETag },
    body: { subject: null },
  });
  assert.equal(nullTask.status, 400);
  assert.equal(twin.stateDigest(), beforeTask);
  assert.equal(twin.getTrace().filter((event) => event.type === "commit.updated").length, 0);
});

test("malformed percent-encoded paths return deterministic 400 responses", async () => {
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  const before = twin.stateDigest();
  const first = await twin.request({
    method: "GET", path: "/tasks(%E0%A4%A)", logicalRequestId: "bad-path-1",
  });
  const second = await twin.request({
    method: "GET", path: "/tasks(%E0%A4%A)", logicalRequestId: "bad-path-2",
  });
  const malformedQuery = await twin.request({
    method: "GET", path: "/tasks?$filter=%E0%A4%A", logicalRequestId: "bad-path-query",
  });

  assert.equal(first.status, 400);
  assert.deepEqual(first.body, second.body);
  assert.deepEqual(malformedQuery.body, first.body);
  assert.match(first.body.error.message, /malformed URL encoding/);
  assert.equal(twin.stateDigest(), before);
});

test("timestamps require explicit offsets and remain deterministic across host timezones", () => {
  assert.throws(
    () => createTwin({ seed: fixtureSeed(), epoch: "2026-04-05T10:00:00" }),
    /Invalid virtual epoch/,
  );
  const coreUrl = new URL("../docs/d365/twin-core.mjs", import.meta.url).href;
  const script = `
    import { createTwin } from ${JSON.stringify(coreUrl)};
    const twin = createTwin({ epoch: "2026-04-05T10:00:00+02:00", seed: { tasks: { value: [] } } });
    const before = twin.stateDigest();
    const rejected = await twin.request({
      method: "POST", path: "/tasks", logicalRequestId: "tz-reject",
      body: { subject: "No offset", scheduledend: "2026-04-05T12:00:00" }
    });
    const afterRejected = twin.stateDigest();
    const accepted = await twin.request({
      method: "POST", path: "/tasks", logicalRequestId: "tz-accept",
      headers: { Prefer: "return=representation" },
      body: { subject: "Explicit offset", scheduledend: "2026-04-05T12:00:00+02:00" }
    });
    console.log(JSON.stringify({
      now: twin.now(), before, afterRejected,
      rejectedStatus: rejected.status,
      acceptedStatus: accepted.status,
      scheduledend: accepted.body.scheduledend,
      digest: twin.stateDigest()
    }));
  `;
  const run = (timezone) => spawnSync(process.execPath, ["--input-type=module", "--eval", script], {
    encoding: "utf8",
    env: { ...process.env, TZ: timezone },
  });
  const honolulu = run("Pacific/Honolulu");
  const tokyo = run("Asia/Tokyo");
  assert.equal(honolulu.status, 0, honolulu.stderr);
  assert.equal(tokyo.status, 0, tokyo.stderr);
  assert.equal(honolulu.stdout, tokyo.stdout);
  const result = JSON.parse(honolulu.stdout);
  assert.equal(result.rejectedStatus, 400);
  assert.equal(result.before, result.afterRejected);
  assert.equal(result.acceptedStatus, 201);
  assert.equal(result.scheduledend, "2026-04-05T12:00:00+02:00");
});

test("503 and 429 retries occur at exact virtual times and exhaust explicitly", async () => {
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  const result = await twin.requestWithRetry({
    method: "POST",
    path: "/tasks",
    logicalRequestId: "retry-success",
    headers: { Prefer: "return=representation" },
    body: { subject: "Retry at deterministic times" },
  }, {
    baseDelayMs: 100,
    maxDelayMs: 500,
    maxAttempts: 4,
    faults: [{ type: "503" }, { type: "429", retryAfterMs: 2000 }],
  });
  assert.equal(result.status, 201);
  const starts = twin.getTrace()
    .filter((event) => event.type === "request.received" && event.requestId === "retry-success")
    .map((event) => event.at);
  assert.deepEqual(starts, [
    "2026-04-05T10:00:00.000Z",
    "2026-04-05T10:00:00.100Z",
    "2026-04-05T10:00:02.100Z",
  ]);
  assert.deepEqual(
    twin.getTrace().filter((event) => event.type === "retry.scheduled").map((event) => event.delayMs),
    [100, 2000],
  );
  assert.equal(twin.getTrace().filter((event) => event.type === "commit.created").length, 1);

  const exhausted = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  await assert.rejects(
    exhausted.requestWithRetry({
      method: "POST", path: "/tasks", logicalRequestId: "retry-exhaust",
      body: { subject: "Never commits" },
    }, {
      baseDelayMs: 100, maxDelayMs: 150, maxAttempts: 3,
      faults: [{ type: "503" }, { type: "503" }, { type: "503" }],
    }),
    (error) => error instanceof TwinRetryExhaustedError && error.attempts === 3,
  );
  assert.equal(exhausted.getTrace().filter((event) => event.type === "commit.created").length, 0);
});

test("post-commit response loss retries one logical request without double apply", async () => {
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  const result = await twin.requestWithRetry({
    method: "POST",
    path: "/tasks",
    logicalRequestId: "lost-response",
    headers: { Prefer: "return=representation" },
    body: { subject: "Commit once despite response loss" },
  }, {
    baseDelayMs: 10,
    maxAttempts: 3,
    faults: [{ type: "postCommitLoss" }],
  });

  assert.equal(result.status, 201);
  assert.equal(result.replayed, true);
  assert.equal(twin.getState("tasks").length, 1);
  assert.equal(twin.getTrace().filter((event) => event.type === "commit.created").length, 1);
  assert.equal(twin.getTrace().filter((event) => event.type === "idempotency.replayed").length, 1);
});

test("per-attempt transport faults run before server idempotency replay", async () => {
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  await assert.rejects(
    twin.requestWithRetry({
      method: "POST",
      path: "/tasks",
      logicalRequestId: "lost-then-network",
      headers: { Prefer: "return=representation" },
      body: { subject: "Second attempt must hit its network fault" },
    }, {
      baseDelayMs: 10,
      maxAttempts: 2,
      faults: [{ type: "postCommitLoss" }, { type: "network" }],
    }),
    (error) => error instanceof TwinRetryExhaustedError
      && error.lastResult?.error?.code === "NETWORK_ERROR",
  );

  assert.equal(twin.getState("tasks").length, 1);
  assert.equal(twin.getTrace().filter((event) => event.type === "commit.created").length, 1);
  assert.equal(twin.getTrace().filter((event) => event.type === "idempotency.replayed").length, 0);
  assert.deepEqual(
    twin.getTrace().filter((event) => event.type === "transport.failed").map((event) => event.code),
    ["POST_COMMIT_RESPONSE_LOSS", "NETWORK_ERROR"],
  );
});

test("network, malformed-response, and timeout faults do not mutate state", async () => {
  for (const fault of [
    { type: "network" },
    { type: "malformed" },
    { type: "timeout", delayMs: 500 },
  ]) {
    const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
    const before = twin.stateDigest();
    await assert.rejects(
      twin.request({
        method: "POST", path: "/tasks", logicalRequestId: `transport-${fault.type}`,
        body: { subject: "Must not commit" }, fault,
      }),
      TwinTransportError,
    );
    assert.equal(twin.stateDigest(), before);
    assert.equal(twin.getTrace().filter((event) => event.type.startsWith("commit.")).length, 0);
  }
});

test("a successful delay advances only virtual time and never sleeps wall time", async () => {
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  const started = performance.now();
  const result = await twin.request({
    method: "GET",
    path: "/contacts",
    logicalRequestId: "virtual-delay",
    fault: { type: "delay", delayMs: 750, timeoutMs: 1000 },
  });
  const elapsed = performance.now() - started;

  assert.equal(result.status, 200);
  assert.equal(result.at, "2026-04-05T10:00:00.750Z");
  assert.ok(elapsed < 100, `delay used ${elapsed}ms of wall time`);
});

test("advancing virtual time completes a due task exactly once", async () => {
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  const created = await twin.request({
    method: "POST",
    path: "/tasks",
    logicalRequestId: "due-task",
    headers: { Prefer: "return=representation" },
    body: { subject: "Due in one minute", scheduledend: "2026-04-05T10:01:00.000Z" },
  });
  twin.advanceTime(60_000, "first tick");
  const afterFirst = await twin.request({
    method: "GET", path: `/tasks(${created.body.activityid})`, logicalRequestId: "due-read-1",
  });
  const firstEtag = afterFirst.headers.ETag;
  twin.advanceTime(60_000, "second tick");
  const afterSecond = await twin.request({
    method: "GET", path: `/tasks(${created.body.activityid})`, logicalRequestId: "due-read-2",
  });

  assert.equal(afterFirst.body.statecode, 1);
  assert.equal(afterFirst.body.statuscode, 5);
  assert.equal(afterSecond.headers.ETag, firstEtag);
  assert.equal(twin.getTrace().filter((event) => event.type === "transition.applied").length, 1);
});

test("installing a replacement seed invalidates incompatible idempotency entries", async () => {
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  const spec = {
    method: "POST",
    path: "/tasks",
    logicalRequestId: "seed-replacement-create",
    headers: { Prefer: "return=representation" },
    body: { subject: "Created against each installed seed" },
  };
  const first = await twin.request(spec);
  twin.installSeedEntity("tasks", { value: [] });
  const second = await twin.request(spec);
  const installed = twin.getTrace().find((event) => event.type === "seed.installed");

  assert.equal(first.status, 201);
  assert.equal(second.status, 201);
  assert.equal(second.replayed, undefined);
  assert.equal(installed.idempotencyEntriesInvalidated, 1);
  assert.equal(twin.getState("tasks").length, 1);
  assert.equal(twin.getTrace().filter((event) => event.type === "commit.created").length, 2);
  assert.equal(twin.getTrace().filter((event) => event.type === "idempotency.replayed").length, 0);
});

test("reset restores the seed and replay reproduces state and trace digests", async () => {
  const run = await deterministicRun();
  const expectedState = run.twin.stateDigest();
  const expectedTrace = run.twin.traceDigest();
  const expectedDigest = run.twin.digest();
  const replay = run.twin.exportReplay();
  const seedDigest = createTwin({ seed: fixtureSeed(), epoch: EPOCH, seedName: "test-seed" }).stateDigest();

  run.twin.reset();
  assert.equal(run.twin.stateDigest(), seedDigest);

  const reproduced = await TwinCore.replay(replay);
  assert.equal(reproduced.stateDigest(), expectedState);
  assert.equal(reproduced.traceDigest(), expectedTrace);
  assert.equal(reproduced.digest(), expectedDigest);

  const lazy = createTwin({ epoch: EPOCH });
  lazy.installSeedEntity("contacts", fixtureSeed().contacts);
  await lazy.request({ method: "GET", path: "/contacts", logicalRequestId: "lazy-read" });
  const lazyReplay = await TwinCore.replay(lazy.exportReplay());
  assert.equal(lazyReplay.digest(), lazy.digest());
});

test("replay advances generated request IDs before the next implicit request", async () => {
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  await twin.request({
    method: "GET", path: "/contacts", logicalRequestId: "req-00007",
  });
  const reproduced = await TwinCore.replay(twin.exportReplay());
  const originalNext = await twin.request({ method: "GET", path: "/contacts" });
  const replayedNext = await reproduced.request({ method: "GET", path: "/contacts" });

  assert.equal(originalNext.requestId, "req-00008");
  assert.deepEqual(replayedNext, originalNext);
});

test("built-in virtual-time scenario applies task and SLA transitions once", async () => {
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  const result = await runBuiltInScenario(twin, "virtual-time");
  assert.equal(result.passed, true);
  assert.equal(result.assertions.length, 2);
  assert.equal(result.trace.filter((event) => event.type === "transition.applied").length, 2);
});

test("chaos scenario commit assertions are scoped to each rerun", async () => {
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  const first = await runBuiltInScenario(twin, "chaos");
  twin.reset();
  const second = await runBuiltInScenario(twin, "chaos");

  assert.equal(first.passed, true);
  assert.equal(second.passed, true);
  assert.equal(first.trace.filter((event) => event.type === "commit.created").length, 1);
  assert.equal(second.trace.filter((event) => event.type === "commit.created").length, 1);
});

test("core ordering and casing do not invoke host locale operations", async () => {
  const originalLocaleCompare = String.prototype.localeCompare;
  const originalLocaleLower = String.prototype.toLocaleLowerCase;
  let orderedNames;
  let filteredCount;
  try {
    String.prototype.localeCompare = () => { throw new Error("localeCompare must not be used"); };
    String.prototype.toLocaleLowerCase = () => { throw new Error("toLocaleLowerCase must not be used"); };
    const twin = createTwin({
      epoch: EPOCH,
      seed: {
        contacts: {
          value: [
            { contactid: "z", firstname: "Zulu", fullname: "Zulu" },
            { contactid: "accent", firstname: "Äda", fullname: "Äda" },
          ],
        },
      },
    });
    const ordered = await twin.request({
      method: "GET", path: "/contacts?$orderby=fullname asc", logicalRequestId: "code-unit-order",
    });
    const filtered = await twin.request({
      method: "GET", path: "/contacts?$filter=contains(fullname,'z')", logicalRequestId: "code-unit-filter",
    });
    orderedNames = ordered.body.value.map((record) => record.fullname);
    filteredCount = filtered.body.value.length;
    twin.stateDigest();
  } finally {
    String.prototype.localeCompare = originalLocaleCompare;
    String.prototype.toLocaleLowerCase = originalLocaleLower;
  }

  assert.deepEqual(orderedNames, ["Zulu", "Äda"]);
  assert.equal(filteredCount, 1);
  const core = await readFile(new URL("../docs/d365/twin-core.mjs", import.meta.url), "utf8");
  assert.doesNotMatch(core, /localeCompare|toLocaleLowerCase|toLocaleUpperCase/);
});

test("browser shell is externalized, XSS-safe, and has explicit load failures", async () => {
  const [html, app] = await Promise.all([
    readFile(new URL("../docs/d365/index.html", import.meta.url), "utf8"),
    readFile(new URL("../docs/d365/app.mjs", import.meta.url), "utf8"),
  ]);
  assert.match(html, /d365\.css/);
  assert.match(html, /app\.mjs/);
  assert.match(html, /Content-Security-Policy/);
  for (const directive of [
    "default-src 'self'", "script-src 'self'", "style-src 'self'", "connect-src 'self'",
    "img-src 'self' data:", "object-src 'none'", "base-uri 'none'", "form-action 'none'",
  ]) {
    assert.match(html, new RegExp(directive.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.doesNotMatch(html, /<script>(?!\s*<\/script>)/);
  assert.doesNotMatch(app, /\.innerHTML\s*=/);
  assert.doesNotMatch(app, /insertAdjacentHTML|outerHTML\s*=/);
  assert.match(app, /textContent/);
  assert.match(app, /Failed to load|could not be loaded/i);
  assert.match(app, /noopener/);
  assert.match(app, /noreferrer/);
});

test("browser app serializes seeds, preloads request targets, and guards async tabs", async () => {
  const app = await readFile(new URL("../docs/d365/app.mjs", import.meta.url), "utf8");
  const refreshStart = app.indexOf("async function refreshEntity(entity)");
  const refreshEnd = app.indexOf("\nasync function renderRecord(", refreshStart);
  const refreshSource = app.slice(refreshStart, refreshEnd);

  assert.match(app, /seedInstallTail:\s*Promise\.resolve\(\)/);
  assert.match(app, /if \(app\.entityPromises\.has\(entity\)\) return app\.entityPromises\.get\(entity\)/);
  assert.match(app, /const pending = app\.seedInstallTail\.then/);
  assert.match(app, /app\.seedInstallTail = pending\.catch/);
  assert.match(app, /await ensureScenarioEntities\(id\);\s*app\.twin\.reset\(\)/s);
  assert.match(app, /await ensureEntities\(BUILT_IN_SCENARIOS\.flatMap/);
  assert.match(app, /const target = parsePath\(path\);[\s\S]*await ensureEntity\(target\.entity\);[\s\S]*app\.twin\.request/);
  assert.match(app, /const recordTabSelectionTokens = new WeakMap\(\)/);
  assert.match(app, /if \(!isCurrentSelection\(\)\) return/);
  assert.match(app, /items = newestRelatedEmails\(related\)\.map/);
  assert.match(app, /valueNode\(record\[key\], type, entity, key\)/);
  assert.match(refreshSource, /const navigationToken = app\.navigationToken/);
  assert.match(refreshSource, /const currentEntity = app\.currentRoute\?\.entity/);
  assert.match(refreshSource, /await ensureEntity\(entity\);\s*if \(!refreshIsCurrent\(\)\) return;\s*renderGrid\(entity\)/);
  assert.equal((refreshSource.match(/if \(!refreshIsCurrent\(\)\) return;/g) || []).length, 2);
  assert.match(app, /Date\.UTC\(/);
  assert.match(app, /getUTCFullYear|getUTCHours/);
  assert.doesNotMatch(app, /new Date\(control\.value\)|new Date\(value\)\.toISOString/);
});
