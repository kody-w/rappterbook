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
  NAV_GROUPS,
  PAGE_SIZE,
  RELATED_EMAIL_LIMIT,
  SYSTEM_VIEWS,
  applySystemView,
  captureRouteGuard,
  combineActivities,
  contactStatusLabel,
  createNavigationHistory,
  dashboardRenderCompletion,
  deriveDashboardMetrics,
  editableSnapshotsEqual,
  emailReferencesAccount,
  gridCodeLabel,
  isRecordEditable,
  isTaskOverdue,
  newestRelatedEmails,
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
  resolveConnectionRows,
  routeGuardMatches,
  savedFormRenderTarget,
  searchRows,
  shouldInterceptSpaNavigation,
  stableSortRows,
  transitionHistoryPop,
  transitionHistoryPrompt,
  transitionPatch,
  updateSelection,
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

test("production Contact and Account related-email helpers cap the newest 25", () => {
  assert.equal(RELATED_EMAIL_LIMIT, 25);
  const emails = Array.from({ length: 31 }, (_, index) => ({
    activityid: `email-${String(index).padStart(2, "0")}`,
    createdon: new Date(Date.UTC(2026, 0, index + 1)).toISOString(),
    new_authorid: "contact-a",
    new_author: "agent-a",
    _regardingobjectid_value: "account-a",
  }));
  emails.push({
    activityid: "unrelated-newest",
    createdon: "2027-01-01T00:00:00.000Z",
    new_authorid: "contact-b",
    new_author: "agent-b",
    _regardingobjectid_value: "account-b",
  });

  const contactEmails = relatedEmailsForContact(emails, {
    contactid: "CONTACT-A",
    new_agentid: "AGENT-A",
  });
  const accountEmails = relatedEmailsForAccount(emails, "ACCOUNT-A");
  for (const related of [contactEmails, accountEmails]) {
    assert.equal(related.length, 25);
    assert.equal(related[0].activityid, "email-30");
    assert.equal(related.at(-1).activityid, "email-06");
    assert.doesNotMatch(related.map((email) => email.activityid).join(","), /unrelated/);
  }
});

test("Account email references and deletion preflight cover lookup values and OData binds", () => {
  const accounts = [
    { accountid: "account-a", name: "Alpha" },
    { accountid: "account-b", name: "Beta" },
    { accountid: "account-c", name: "Clean" },
  ];
  const emails = [
    {
      activityid: "email-direct",
      _regardingobjectid_value: "ACCOUNT-A",
    },
    {
      activityid: "email-bind",
      "regardingobjectid_account@odata.bind": "/api/data/v9.2/accounts({ACCOUNT-B})",
    },
    {
      activityid: "email-unrelated",
      _regardingobjectid_value: "account-z",
      "regardingobjectid_account@odata.bind": "/accounts(account-y)",
    },
  ];
  const pristineAccounts = structuredClone(accounts);
  const pristineEmails = structuredClone(emails);

  assert.equal(emailReferencesAccount(emails[0], "account-a"), true);
  assert.equal(emailReferencesAccount(emails[1], "account-b"), true);
  assert.equal(emailReferencesAccount(emails[2], "account-a"), false);
  assert.deepEqual(
    relatedEmailsForAccount(emails, "ACCOUNT-B").map((email) => email.activityid),
    ["email-bind"],
  );

  const preflight = preflightAccountDeletion(
    ["account-c", "ACCOUNT-B", "account-a", "account-a"],
    accounts,
    emails,
  );
  assert.deepEqual(preflight, {
    allowed: false,
    blockers: [
      { accountId: "ACCOUNT-B", accountName: "Beta", emailIds: ["email-bind"] },
      { accountId: "account-a", accountName: "Alpha", emailIds: ["email-direct"] },
    ],
  });
  let remainingAccounts = structuredClone(accounts);
  if (preflight.allowed) {
    const selectedIds = new Set(["account-a", "account-b", "account-c"]);
    remainingAccounts = remainingAccounts.filter((account) => !selectedIds.has(account.accountid));
  }
  assert.deepEqual(
    remainingAccounts,
    accounts,
    "bulk preflight prevents every delete when any account is blocked",
  );
  assert.deepEqual(accounts, pristineAccounts);
  assert.deepEqual(emails, pristineEmails);

  assert.deepEqual(
    preflightAccountDeletion(["account-a", "account-c"], accounts, []),
    { allowed: true, blockers: [] },
  );
  const danglingAfterAccountDelete = preflightAccountDeletion(
    ["account-a"],
    accounts.filter((account) => account.accountid !== "account-a"),
    emails,
  );
  assert.equal(danglingAfterAccountDelete.allowed, false);
  assert.equal(danglingAfterAccountDelete.blockers[0].accountId, "account-a");
});

test("dialog replacement uses the outgoing dialog's own cancel value", () => {
  for (const incoming of [
    { kind: "error", cancelValue: "close" },
    { kind: "info", cancelValue: "dismiss" },
  ]) {
    let confirmationResult = "unresolved";
    const confirmation = {
      kind: "confirmation",
      cancelValue: false,
      finish(value) {
        confirmationResult = value;
      },
    };
    const transition = replaceDialogState(confirmation, incoming);
    assert.equal(transition.activeDialog, incoming);
    assert.equal(transition.replacement.dialog, confirmation);
    assert.equal(transition.replacement.value, false);
    transition.replacement.dialog.finish(transition.replacement.value);
    assert.equal(confirmationResult, false);
  }
  assert.deepEqual(replaceDialogState(null, { cancelValue: "close" }).replacement, null);
});

test("dashboard direct-render completion always clears busy and selects stable focus targets", () => {
  assert.deepEqual(dashboardRenderCompletion("selector"), {
    busy: false,
    focusTargetId: "dashboard-selector",
  });
  assert.deepEqual(dashboardRenderCompletion("refresh"), {
    busy: false,
    focusTargetId: "dashboard-refresh",
  });
  assert.deepEqual(dashboardRenderCompletion(), {
    busy: false,
    focusTargetId: null,
  });
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

test("route guard rejects stale routes and different active records", () => {
  const route = { view: "record", entity: "contacts", id: "CONTACT-A" };
  const guard = captureRouteGuard(7, route);
  assert.equal(routeGuardMatches(guard, 7, route), true);
  assert.equal(
    routeGuardMatches(guard, 7, { ...route, id: "contact-a" }),
    true,
  );
  assert.equal(routeGuardMatches(guard, 8, route), false);
  assert.equal(routeGuardMatches(guard, 7, { ...route, id: "contact-b" }), false);
  assert.equal(routeGuardMatches(guard, 7, { ...route, entity: "accounts" }), false);
  assert.equal(routeGuardMatches(guard, 7, { view: "grid", entity: "contacts" }), false);
});

test("contact deletion preflight is deterministic on pristine and post-delete data", () => {
  const contacts = [
    { contactid: "contact-a", fullname: "Ada Agent" },
    { contactid: "contact-b", fullname: "Bob Agent" },
    { contactid: "contact-c", fullname: "Clean Contact" },
  ];
  const connections = [
    {
      connectionid: "connection-2",
      _record1id_value: "contact-b",
      _record2id_value: "CONTACT-A",
    },
    {
      connectionid: "connection-1",
      _record1id_value: "contact-a",
      _record2id_value: "contact-b",
    },
  ];
  const pristineContacts = JSON.parse(JSON.stringify(contacts));
  const pristineConnections = JSON.parse(JSON.stringify(connections));
  const selected = preflightContactDeletion(
    ["CONTACT-C", "CONTACT-A", "contact-a"],
    contacts,
    connections,
  );

  assert.equal(selected.allowed, false);
  assert.deepEqual(selected.blockers, [{
    contactId: "CONTACT-A",
    contactName: "Ada Agent",
    connectionIds: ["connection-1", "connection-2"],
  }]);
  assert.deepEqual(contacts, pristineContacts);
  assert.deepEqual(connections, pristineConnections);

  const afterConnectionDelete = preflightContactDeletion(
    ["contact-a", "contact-c"],
    contacts,
    [],
  );
  assert.deepEqual(afterConnectionDelete, { allowed: true, blockers: [] });

  const postDeleteWithDanglingConnection = preflightContactDeletion(
    ["contact-a"],
    contacts.filter((contact) => contact.contactid !== "contact-a"),
    connections,
  );
  assert.equal(postDeleteWithDanglingConnection.allowed, false);
  assert.equal(postDeleteWithDanglingConnection.blockers[0].contactId, "contact-a");
});

test("SPA navigation interception preserves modified and native link clicks", () => {
  assert.equal(shouldInterceptSpaNavigation({ button: 0 }), true);
  assert.equal(shouldInterceptSpaNavigation({ button: 0, target: "_self" }), true);
  for (const options of [
    { button: 1 },
    { button: 2 },
    { button: 0, ctrlKey: true },
    { button: 0, metaKey: true },
    { button: 0, shiftKey: true },
    { button: 0, altKey: true },
    { button: 0, download: true },
    { button: 0, target: "_blank" },
    { button: 0, target: "report-frame" },
    { button: 0, defaultPrevented: true },
  ]) {
    assert.equal(shouldInterceptSpaNavigation(options), false);
  }
});

test("normal shell uses Customer Service Hub branding and exact sitemap order", async () => {
  const html = await readFile(new URL("../docs/d365/index.html", import.meta.url), "utf8");
  assert.match(html, /<title>Dynamics 365 — Customer Service Hub<\/title>/);
  assert.match(html, />Dynamics 365<\/a>/);
  assert.match(html, />Customer Service Hub<\/span>/);
  assert.deepEqual(
    NAV_GROUPS.map((group) => [group.label, group.items.map((item) => item.label)]),
    [
      ["My Work", ["Dashboards", "Activities"]],
      ["Customers", ["Accounts", "Contacts"]],
      ["Service", ["Cases", "Queues"]],
      ["Knowledge", ["Knowledge Articles", "Knowledge Search"]],
      ["Service Management", ["Simulation settings", "API & simulation"]],
    ],
  );
  const navHtml = html.slice(
    html.indexOf('<nav class="sitemap-navigation">'),
    html.indexOf("</nav>", html.indexOf('<nav class="sitemap-navigation">')),
  );
  let previousIndex = -1;
  for (const group of NAV_GROUPS) {
    const groupIndex = navHtml.indexOf(`>${group.label}<`);
    assert.ok(groupIndex > previousIndex, `${group.label} is out of order`);
    previousIndex = groupIndex;
    for (const item of group.items) {
      const itemIndex = navHtml.indexOf(`>${item.label.replace("&", "&amp;")}<`, previousIndex);
      assert.ok(itemIndex > previousIndex, `${item.label} is out of order`);
      previousIndex = itemIndex;
    }
  }
  assert.doesNotMatch(html, /nav-count|data-count/);
  assert.match(html, /data-area="customer-service"/);
  assert.match(html, /data-area="service-management"/);
  assert.match(html, /id="area-switcher"[\s\S]*aria-expanded="false"/);
});

test("normal shell copy excludes product and technical implementation branding", async () => {
  const [html, appSource] = await Promise.all([
    readFile(new URL("../docs/d365/index.html", import.meta.url), "utf8"),
    readFile(new URL("../docs/d365/app.mjs", import.meta.url), "utf8"),
  ]);
  const normalShell = html
    .replace(/<section data-area="service-management"[\s\S]*?<\/section>/, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ");
  assert.doesNotMatch(
    normalShell,
    /\b(?:Rappterbook|twin|simulation|seed|snapshot|GitHub|ETag|Raw JSON|trace|virtual time|browser-local)\b/i,
  );
  const entityConfiguration = appSource.slice(
    appSource.indexOf("const ENTITY_UI"),
    appSource.indexOf("const ACTIVITIES_GRID"),
  );
  assert.doesNotMatch(entityConfiguration, /"[^"]*(?:Rappterbook|Poke|Glitch|Agent|Diagnostics)[^"]*"/);
});

test("activities combine email and task rows with correct status semantics", () => {
  const now = "2026-04-05T10:00:00.000Z";
  const activities = combineActivities(
    [{
      activityid: "email-1",
      subject: "Sent message",
      statecode: 1,
      statuscode: 3,
      actualend: "2026-04-05T09:00:00.000Z",
    }],
    [
      { activityid: "task-open", subject: "Open", statecode: 0, scheduledend: "2026-04-05T11:00:00.000Z" },
      { activityid: "task-overdue", subject: "Past due", statecode: 0, scheduledend: "2026-04-05T09:00:00.000Z" },
      { activityid: "task-done", subject: "Done", statecode: 1, statuscode: 5 },
    ],
    now,
  );
  assert.deepEqual(
    activities.map((activity) => [activity._activityType, activity._status]),
    [["Email", "Sent"], ["Task", "Open"], ["Task", "Overdue"], ["Task", "Completed"]],
  );
  assert.equal(applySystemView(activities, "activities", "sent-email").length, 1);
  assert.equal(applySystemView(activities, "activities", "open").length, 2);
  assert.equal(applySystemView(activities, "activities", "closed").length, 2);
});

test("system views, search, stable sorting, selection, and 50-row paging are deterministic", () => {
  assert.equal(PAGE_SIZE, 50);
  assert.deepEqual(SYSTEM_VIEWS.contacts.map((view) => view.label), ["Active Contacts", "Inactive Contacts", "All Contacts"]);
  assert.deepEqual(SYSTEM_VIEWS.accounts.map((view) => view.label), ["Active Accounts", "Inactive Accounts", "All Accounts"]);
  assert.deepEqual(SYSTEM_VIEWS.incidents.map((view) => view.label), ["Active Cases", "Resolved Cases", "All Cases"]);
  assert.deepEqual(
    SYSTEM_VIEWS.activities.map((view) => view.label),
    ["Open Activities", "Closed Activities", "All Activities", "Sent Email"],
  );
  assert.deepEqual(SYSTEM_VIEWS.connections.map((view) => view.label), ["Active Connections", "All Connections"]);

  const rows = Array.from({ length: 121 }, (_, index) => ({
    id: String(index).padStart(3, "0"),
    name: index % 2 ? "Beta" : "Alpha",
    statecode: index % 3 ? 0 : 1,
  }));
  assert.equal(applySystemView(rows, "contacts", "active").length, 80);
  assert.equal(searchRows(rows, ["name"], "beta").length, 60);
  const sorted = stableSortRows(rows, "name", "asc", "id");
  assert.deepEqual(sorted.slice(0, 3).map((row) => row.id), ["000", "002", "004"]);
  const first = paginateRows(sorted, 1);
  const second = paginateRows(sorted, 2);
  const third = paginateRows(sorted, 3);
  assert.deepEqual([first.rows.length, second.rows.length, third.rows.length], [50, 50, 21]);
  assert.deepEqual([...first.rows, ...second.rows, ...third.rows].map((row) => row.id), sorted.map((row) => row.id));
  let selected = updateSelection(new Set(), ["000", "002"], true);
  selected = updateSelection(selected, ["000"], false);
  assert.deepEqual([...selected], ["002"]);
});

test("indexed history restores before prompting and preserves Back and Forward entries", () => {
  const runGuardedTraversal = (originIndex, targetIndex, proceed) => {
    const entries = ["first", "second"];
    let cursor = targetIndex;
    let history = createNavigationHistory(originIndex);
    const attempted = transitionHistoryPop(history, targetIndex, true);
    history = attempted.state;
    assert.deepEqual(attempted.effect, {
      type: "traverse",
      delta: originIndex - targetIndex,
    });
    cursor += attempted.effect.delta;
    assert.equal(cursor, originIndex);
    const restored = transitionHistoryPop(history, cursor, true);
    history = restored.state;
    assert.equal(restored.effect.type, "prompt");
    const resolved = transitionHistoryPrompt(history, proceed);
    history = resolved.state;
    if (!proceed) {
      assert.equal(resolved.effect.type, "stay");
      assert.equal(history.currentIndex, originIndex);
      assert.equal(cursor, originIndex);
    } else {
      assert.deepEqual(resolved.effect, {
        type: "traverse",
        delta: targetIndex - originIndex,
      });
      cursor += resolved.effect.delta;
      const arrived = transitionHistoryPop(history, cursor, false);
      history = arrived.state;
      assert.equal(arrived.effect.type, "navigate");
      assert.equal(history.currentIndex, targetIndex);
      assert.equal(
        transitionHistoryPop(history, targetIndex, false).effect.type,
        "stay",
      );
    }
    assert.deepEqual(entries, ["first", "second"]);
    return cursor;
  };

  assert.equal(runGuardedTraversal(1, 0, false), 1);
  for (const choice of ["discard", "save"]) {
    assert.equal(runGuardedTraversal(1, 0, Boolean(choice)), 0);
    assert.equal(runGuardedTraversal(0, 1, Boolean(choice)), 1);
  }
  assert.deepEqual(pushNavigationHistory(createNavigationHistory(4)), {
    currentIndex: 5,
    pending: null,
  });
});

test("indexed history restores reentrant Back and Forward pops in every pending phase", () => {
  const attempted = transitionHistoryPop(createNavigationHistory(4), 3, true);
  const restoring = attempted.state;
  assert.equal(restoring.pending.phase, "restoring");

  const assertCorrections = (history, anchorIndex, targets) => {
    for (const targetIndex of targets) {
      const transition = transitionHistoryPop(history, targetIndex, true);
      assert.equal(transition.effect.type, "traverse");
      assert.equal(transition.effect.delta, anchorIndex - targetIndex);
      assert.deepEqual(transition.state, history);
      assert.notEqual(transition.effect.type, "prompt");
    }
  };

  assertCorrections(restoring, 4, [2, 3, 5, 1, 5, 2]);
  assert.deepEqual(
    transitionHistoryPop(restoring, null, true),
    { state: restoring, effect: { type: "stay" } },
  );

  const restored = transitionHistoryPop(restoring, 4, true);
  assert.equal(restored.effect.type, "prompt");
  const prompting = restored.state;
  assert.equal(prompting.pending.phase, "prompting");
  assertCorrections(prompting, 4, [3, 5, 2, 3, 5, 1]);
  assert.deepEqual(
    transitionHistoryPop(prompting, 4, true),
    { state: prompting, effect: { type: "stay" } },
  );

  const accepted = transitionHistoryPrompt(prompting, true);
  const proceeding = accepted.state;
  assert.equal(proceeding.pending.phase, "proceeding");
  assertCorrections(proceeding, 3, [2, 4, 1, 5, 4, 2]);
  const arrived = transitionHistoryPop(proceeding, 3, false);
  assert.equal(arrived.effect.type, "navigate");
  assert.deepEqual(arrived.state, { currentIndex: 3, pending: null });

  const canceled = transitionHistoryPrompt(prompting, false);
  assert.deepEqual(canceled, {
    state: { currentIndex: 4, pending: null },
    effect: { type: "stay" },
  });
});

test("record tabs use wrapped roving selection and skip disabled Related", () => {
  const existingTabs = [{ disabled: false }, { disabled: false }, { disabled: false }];
  assert.equal(nextRovingTabIndex(existingTabs, 0, "ArrowLeft"), 2);
  assert.equal(nextRovingTabIndex(existingTabs, 2, "ArrowRight"), 0);
  assert.equal(nextRovingTabIndex(existingTabs, 1, "Home"), 0);
  assert.equal(nextRovingTabIndex(existingTabs, 1, "End"), 2);

  const newRecordTabs = [{ disabled: false }, { disabled: false }, { disabled: true }];
  assert.equal(nextRovingTabIndex(newRecordTabs, 1, "ArrowRight"), 0);
  assert.equal(nextRovingTabIndex(newRecordTabs, 0, "ArrowLeft"), 1);
  assert.equal(nextRovingTabIndex(newRecordTabs, 0, "End"), 1);
  assert.equal(nextRovingTabIndex(newRecordTabs, 0, "Tab"), 0);
});

test("grid search includes formatted values as well as raw values", () => {
  const contact = { contactid: "c", new_status: "dormant" };
  const contacts = searchRows(
    [contact],
    ["new_status"],
    "Inactive",
    (record, field) => field === "new_status"
      ? contactStatusLabel(record.new_status)
      : record[field],
  );
  assert.deepEqual(contacts, [contact]);
  assert.deepEqual(searchRows([contact], ["new_status"], "dormant"), [contact]);

  const now = "2026-04-05T10:00:00.000Z";
  const activities = combineActivities(
    [
      { activityid: "sent", subject: "Mail", statecode: 1, statuscode: 3 },
      { activityid: "email-complete", subject: "Mail", statecode: 1, statuscode: 4 },
    ],
    [
      { activityid: "done", subject: "Done", statecode: 1, prioritycode: 2 },
      {
        activityid: "late",
        subject: "Late",
        statecode: 0,
        prioritycode: 0,
        scheduledend: "2026-04-05T09:00:00.000Z",
      },
    ],
    now,
  );
  for (const term of ["Sent", "Completed", "Overdue", "Email", "Task"]) {
    assert.ok(searchRows(activities, ["_status", "_activityType"], term).length > 0, term);
  }
  const highPriority = searchRows(
    activities,
    ["prioritycode"],
    "High",
    (record, field) => gridCodeLabel(record._entity, field, record[field], now, record),
  );
  assert.deepEqual(highPriority.map((record) => record._id), ["done"]);
  const lowPriority = searchRows(
    activities,
    ["prioritycode"],
    "Low",
    (record, field) => gridCodeLabel(record._entity, field, record[field], now, record),
  );
  assert.deepEqual(lowPriority.map((record) => record._id), ["late"]);
});

test("editable snapshots clear dirty state after exact value reversion", () => {
  const baseline = normalizeEditableSnapshot({
    subject: "Follow up",
    prioritycode: 1,
    scheduledend: null,
    description: "Line one\r\nLine two",
  });
  assert.equal(editableSnapshotsEqual(baseline, {
    description: "Line one\nLine two",
    scheduledend: undefined,
    prioritycode: 1,
    subject: "Follow up",
  }), true);
  assert.equal(editableSnapshotsEqual(baseline, {
    ...baseline,
    prioritycode: 2,
  }), false);
  const restored = { ...baseline, prioritycode: 2 };
  restored.prioritycode = 1;
  assert.equal(editableSnapshotsEqual(baseline, restored), true);
});

test("closed record editability and command contracts are state-controlled", () => {
  for (const entity of ["contacts", "accounts", "tasks", "incidents"]) {
    assert.equal(isRecordEditable(entity, null, true), true);
    assert.equal(isRecordEditable(entity, { statecode: 0 }, true), true);
    assert.equal(isRecordEditable(entity, { statecode: 1 }, true), false);
  }
  assert.equal(isRecordEditable("emails", { statecode: 1 }, false), false);
  assert.deepEqual(
    recordCommandActions("contacts", { statecode: 1 }, { editable: true, deletable: true }),
    ["activate", "delete", "refresh", "back"],
  );
  assert.deepEqual(
    recordCommandActions("accounts", { statecode: 1 }, { editable: true, deletable: true }),
    ["activate", "delete", "refresh", "back"],
  );
  assert.deepEqual(
    recordCommandActions("tasks", { statecode: 1 }, { editable: true, deletable: true }),
    ["delete", "refresh", "back"],
  );
  assert.deepEqual(
    recordCommandActions("incidents", { statecode: 2 }, { editable: true, deletable: true }),
    ["reopen", "delete", "refresh", "back"],
  );
  assert.deepEqual(
    recordCommandActions("incidents", { statecode: 0 }, { editable: true, deletable: true }),
    ["save", "save-close", "resolve", "cancel", "delete", "refresh", "back"],
  );
  assert.deepEqual(transitionPatch("contacts", "deactivate", EPOCH), {
    statecode: 1,
    statuscode: 2,
    new_status: "inactive",
  });
  assert.deepEqual(transitionPatch("contacts", "activate", EPOCH), {
    statecode: 0,
    statuscode: 1,
    new_status: "active",
  });
});

test("contact relationship rows expose only neutral directional labels", () => {
  const contacts = [
    { contactid: "a", fullname: "Ada" },
    { contactid: "b", fullname: "Babbage" },
    { contactid: "c", fullname: "Curie" },
  ];
  const connections = [
    {
      connectionid: "one",
      name: "source-a follows source-b",
      _record1id_value: "a",
      _record2id_value: "b",
    },
    {
      connectionid: "two",
      name: "source-c follows source-a",
      _record1id_value: "c",
      _record2id_value: "a",
    },
  ];
  const related = relatedConnectionsForContact(connections, "a", contacts);
  assert.deepEqual(
    related.map((connection) => [
      connection._relatedName,
      connection._relationship,
    ]),
    [["Babbage", "Follows"], ["Curie", "Followed by"]],
  );
  assert.deepEqual(
    searchRows(related, ["_relatedName", "_relationship"], "followed by")
      .map((connection) => connection.connectionid),
    ["two"],
  );
  assert.deepEqual(
    stableSortRows(related, "_relationship", "asc", "connectionid")
      .map((connection) => connection._relationship),
    ["Followed by", "Follows"],
  );
  assert.equal(related.some((connection) => connection._relationship.includes("source-")), false);
});

test("all connection rows are reachable through paged contact relationships with resolved names", async () => {
  const [contactsPayload, connectionsPayload] = await Promise.all([
    readFile(new URL("../docs/api/data/v9.2/contacts.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../docs/api/data/v9.2/connections.json", import.meta.url), "utf8").then(JSON.parse),
  ]);
  const contacts = contactsPayload.value;
  const connections = connectionsPayload.value;
  const resolved = resolveConnectionRows(connections, contacts);
  assert.equal(connections.length, 2426);
  assert.ok(resolved.every((connection) => connection._record1name && connection._record2name));

  const reachable = new Set();
  for (const contact of contacts) {
    const related = relatedConnectionsForContact(connections, contact.contactid, contacts);
    const pageCount = Math.max(1, Math.ceil(related.length / PAGE_SIZE));
    for (let pageNumber = 1; pageNumber <= pageCount; pageNumber += 1) {
      const page = paginateRows(related, pageNumber);
      assert.ok(page.rows.length <= PAGE_SIZE);
      for (const connection of page.rows) reachable.add(connection.connectionid);
    }
  }
  assert.equal(reachable.size, connections.length);
});

test("dashboard components derive their metrics and charts from supplied data", () => {
  const data = {
    incidents: [
      { incidentid: "a", statecode: 0, prioritycode: 1, createdon: "2026-01-02T00:00:00Z" },
      { incidentid: "b", statecode: 1, prioritycode: 3, createdon: "2026-01-01T00:00:00Z" },
    ],
    contacts: [{ contactid: "a", statecode: 0 }, { contactid: "b", statecode: 1 }],
    accounts: [{ accountid: "a", name: "One", new_postcount: 7 }, { accountid: "b", name: "Two", new_postcount: 3 }],
    emails: [{ activityid: "e", statecode: 1, statuscode: 3, createdon: "2026-01-03T00:00:00Z" }],
    tasks: [{ activityid: "t", statecode: 0, scheduledend: "2026-01-04T00:00:00Z" }],
  };
  const metrics = deriveDashboardMetrics(data, "2026-01-03T00:00:00Z");
  assert.deepEqual(metrics.casePriority.map((item) => item.value), [1, 0, 1]);
  assert.deepEqual(metrics.contactStatus.map((item) => item.value), [1, 1]);
  assert.deepEqual(metrics.accountActivity.map((item) => item.value), [7, 3]);
  assert.deepEqual(metrics.activeCases.map((record) => record.incidentid), ["a"]);
  assert.deepEqual(metrics.recentActivities.map((record) => record._id), ["t", "e"]);
  assert.deepEqual(metrics.openActivities.map((record) => record._id), ["t"]);
  assert.deepEqual(metrics.sentEmails.map((record) => record._id), ["e"]);
  assert.deepEqual(metrics.taskActivities.map((record) => record._id), ["t"]);
  assert.deepEqual(metrics.activitiesByType, [
    { label: "Email", value: 1 },
    { label: "Task", value: 1 },
  ]);
  assert.deepEqual(metrics.activitiesByStatus, [
    { label: "Open", value: 1 },
    { label: "Sent", value: 1 },
  ]);

  data.contacts.push({ contactid: "c", statecode: 0 });
  data.accounts[1].new_postcount = 12;
  data.tasks.push({ activityid: "done", statecode: 1, scheduledend: "2026-01-02T00:00:00Z" });
  const changed = deriveDashboardMetrics(data, "2026-01-03T00:00:00Z");
  assert.deepEqual(changed.contactStatus.map((item) => item.value), [2, 1]);
  assert.equal(changed.accountActivity[0].label, "Two");
  assert.deepEqual(changed.activitiesByType, [
    { label: "Email", value: 1 },
    { label: "Task", value: 2 },
  ]);
  assert.deepEqual(changed.activitiesByStatus, [
    { label: "Completed", value: 1 },
    { label: "Open", value: 1 },
    { label: "Sent", value: 1 },
  ]);

  const noTasks = deriveDashboardMetrics({ emails: data.emails, tasks: [] }, "2026-01-03T00:00:00Z");
  assert.deepEqual(noTasks.taskActivities, []);
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

test("connected Contacts are restricted until their Connections are deleted", async () => {
  const seed = fixtureSeed();
  seed.contacts.value.push({
    contactid: "00000000-0000-0000-0000-000000000002",
    firstname: "Grace",
    fullname: "Grace Hopper",
  });
  seed.connections = {
    value: [{
      connectionid: "connection-a",
      name: "Ada follows Grace",
      _record1id_value: "00000000-0000-0000-0000-000000000001",
      _record2id_value: "00000000-0000-0000-0000-000000000002",
    }],
  };
  const twin = createTwin({ seed, epoch: EPOCH });
  const contact = twin.getState("contacts")[0];
  const connection = twin.getState("connections")[0];
  const before = twin.getState("contacts");
  const blocked = await twin.request({
    method: "DELETE",
    path: `/contacts(${contact.contactid})`,
    logicalRequestId: "connected-contact-delete",
    headers: { "If-Match": contact["@odata.etag"] },
  });

  assert.equal(blocked.status, 409);
  assert.match(blocked.body.error.message, /Connection.*Deactivate/i);
  assert.deepEqual(twin.getState("contacts"), before);

  const removedConnection = await twin.request({
    method: "DELETE",
    path: `/connections(${connection.connectionid})`,
    logicalRequestId: "connection-delete",
    headers: { "If-Match": connection["@odata.etag"] },
  });
  const removedContact = await twin.request({
    method: "DELETE",
    path: `/contacts(${contact.contactid})`,
    logicalRequestId: "contact-delete-after-preflight",
    headers: { "If-Match": contact["@odata.etag"] },
  });
  assert.equal(removedConnection.status, 204);
  assert.equal(removedContact.status, 204);
});

test("Accounts referenced by Emails remain intact until every reference is deleted", async () => {
  const seed = fixtureSeed();
  seed.accounts = {
    value: [
      { accountid: "account-a", name: "Alpha" },
      { accountid: "account-b", name: "Beta" },
      { accountid: "account-c", name: "Clean" },
    ],
  };
  seed.emails = {
    value: [
      {
        activityid: "email-direct",
        subject: "Direct reference",
        _regardingobjectid_value: "ACCOUNT-A",
      },
      {
        activityid: "email-bind",
        subject: "Bind reference",
        "regardingobjectid_account@odata.bind": "/accounts({ACCOUNT-B})",
      },
    ],
  };
  const twin = createTwin({ seed, epoch: EPOCH });
  const accountsBefore = twin.getState("accounts");
  const emailsBefore = twin.getState("emails");
  const accountA = accountsBefore.find((account) => account.accountid === "account-a");
  const accountB = accountsBefore.find((account) => account.accountid === "account-b");
  const accountC = accountsBefore.find((account) => account.accountid === "account-c");

  const blockedDirect = await twin.request({
    method: "DELETE",
    path: "/accounts(account-a)",
    logicalRequestId: "delete-account-direct-reference",
    headers: { "If-Match": accountA["@odata.etag"] },
  });
  const blockedBind = await twin.request({
    method: "DELETE",
    path: "/accounts(account-b)",
    logicalRequestId: "delete-account-bind-reference",
    headers: { "If-Match": accountB["@odata.etag"] },
  });
  assert.equal(blockedDirect.status, 409);
  assert.equal(blockedBind.status, 409);
  assert.match(blockedDirect.body.error.message, /Email.*Deactivate/i);
  assert.deepEqual(twin.getState("accounts"), accountsBefore);
  assert.deepEqual(twin.getState("emails"), emailsBefore);

  const cleanDelete = await twin.request({
    method: "DELETE",
    path: "/accounts(account-c)",
    logicalRequestId: "delete-clean-account",
    headers: { "If-Match": accountC["@odata.etag"] },
  });
  assert.equal(cleanDelete.status, 204);
  assert.equal(twin.getState("accounts").some((account) => account.accountid === "account-c"), false);

  const emailA = twin.getState("emails").find((email) => email.activityid === "email-direct");
  const removedEmail = await twin.request({
    method: "DELETE",
    path: "/emails(email-direct)",
    logicalRequestId: "delete-account-reference-email",
    headers: { "If-Match": emailA["@odata.etag"] },
  });
  const removedAccount = await twin.request({
    method: "DELETE",
    path: "/accounts(account-a)",
    logicalRequestId: "delete-account-after-email",
    headers: { "If-Match": accountA["@odata.etag"] },
  });
  assert.equal(removedEmail.status, 204);
  assert.equal(removedAccount.status, 204);
  assert.equal(twin.getState("accounts").some((account) => account.accountid === "account-a"), false);
  assert.equal(
    twin.getState("emails").some((email) => emailReferencesAccount(email, "account-a")),
    false,
  );
  assert.equal(twin.getState("accounts").some((account) => account.accountid === "account-b"), true);
  assert.equal(
    twin.getState("emails").some((email) => emailReferencesAccount(email, "account-b")),
    true,
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

test("save-before-action rebases the form record and uses the saved ETag after cancellation", async () => {
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  const original = twin.getState("contacts")[0];
  const saved = await twin.request({
    method: "PATCH",
    path: `/contacts(${original.contactid})`,
    logicalRequestId: "dirty-dialog-save",
    headers: { "If-Match": original["@odata.etag"], Prefer: "return=representation" },
    body: { description: "Saved before the requested action." },
  });
  const afterSave = twin.stateDigest();
  const renderTarget = savedFormRenderTarget(
    { entity: "contacts", record: original },
    saved.body,
    "details",
  );

  assert.equal(saved.status, 200);
  assert.equal(renderTarget.entity, "contacts");
  assert.equal(renderTarget.record, saved.body);
  assert.equal(renderTarget.initialTab, "details");
  assert.notEqual(renderTarget.record["@odata.etag"], original["@odata.etag"]);
  assert.equal(twin.stateDigest(), afterSave, "canceling the first action leaves the saved record intact");

  const action = await twin.request({
    method: "PATCH",
    path: `/contacts(${renderTarget.record.contactid})`,
    logicalRequestId: "action-after-canceled-confirmation",
    headers: {
      "If-Match": renderTarget.record["@odata.etag"],
      Prefer: "return=representation",
    },
    body: transitionPatch("contacts", "deactivate", twin.now()),
  });
  assert.equal(action.status, 200);
  assert.equal(action.body.statecode, 1);
  assert.notEqual(action.body["@odata.etag"], renderTarget.record["@odata.etag"]);

  const staleOriginal = await twin.request({
    method: "PATCH",
    path: `/contacts(${original.contactid})`,
    logicalRequestId: "original-form-etag-is-stale",
    headers: { "If-Match": original["@odata.etag"] },
    body: { description: "A stale closure must not win." },
  });
  assert.equal(staleOriginal.status, 412);
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

test("advancing virtual time leaves a past-due task open until Mark Complete is explicit", async () => {
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  const created = await twin.request({
    method: "POST",
    path: "/tasks",
    logicalRequestId: "due-task",
    headers: { Prefer: "return=representation" },
    body: { subject: "Due in one minute", scheduledend: "2026-04-05T10:01:00.000Z" },
  });
  twin.advanceTime(60_001, "past due");
  const afterFirst = await twin.request({
    method: "GET", path: `/tasks(${created.body.activityid})`, logicalRequestId: "due-read-1",
  });
  const firstEtag = afterFirst.headers.ETag;
  twin.advanceTime(60_000, "second tick");
  const afterSecond = await twin.request({
    method: "GET", path: `/tasks(${created.body.activityid})`, logicalRequestId: "due-read-2",
  });

  assert.equal(afterFirst.body.statecode, 0);
  assert.equal(afterFirst.body.statuscode, 2);
  assert.equal(isTaskOverdue(afterFirst.body, twin.now()), true);
  assert.equal(afterSecond.headers.ETag, firstEtag);
  assert.equal(twin.getTrace().filter((event) => event.type === "transition.applied").length, 0);

  const completed = await twin.request({
    method: "PATCH",
    path: `/tasks(${created.body.activityid})`,
    logicalRequestId: "mark-complete",
    headers: { "If-Match": afterSecond.headers.ETag, Prefer: "return=representation" },
    body: transitionPatch("tasks", "complete", twin.now()),
  });
  assert.equal(completed.body.statecode, 1);
  assert.equal(completed.body.statuscode, 5);
  assert.equal(completed.body.actualend, twin.now());
  assert.equal(isTaskOverdue(completed.body, twin.now()), false);
});

test("task cancellation and case resolve, cancel, and reopen use explicit PATCH transitions", async () => {
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  const task = await twin.request({
    method: "POST",
    path: "/tasks",
    logicalRequestId: "task-to-cancel",
    headers: { Prefer: "return=representation" },
    body: { subject: "Cancel explicitly" },
  });
  const canceledTask = await twin.request({
    method: "PATCH",
    path: `/tasks(${task.body.activityid})`,
    logicalRequestId: "cancel-task",
    headers: { "If-Match": task.headers.ETag, Prefer: "return=representation" },
    body: transitionPatch("tasks", "cancel", twin.now()),
  });
  assert.deepEqual(
    [canceledTask.body.statecode, canceledTask.body.statuscode, canceledTask.body.actualend],
    [2, 6, twin.now()],
  );

  const incident = await twin.request({
    method: "POST",
    path: "/incidents",
    logicalRequestId: "case-transitions",
    headers: { Prefer: "return=representation" },
    body: { title: "Explicit case transitions" },
  });
  const resolved = await twin.request({
    method: "PATCH",
    path: `/incidents(${incident.body.incidentid})`,
    logicalRequestId: "resolve-case",
    headers: { "If-Match": incident.headers.ETag, Prefer: "return=representation" },
    body: transitionPatch("incidents", "resolve", twin.now()),
  });
  assert.deepEqual([resolved.body.statecode, resolved.body.statuscode], [1, 5]);
  const reopened = await twin.request({
    method: "PATCH",
    path: `/incidents(${incident.body.incidentid})`,
    logicalRequestId: "reopen-case",
    headers: { "If-Match": resolved.headers.ETag, Prefer: "return=representation" },
    body: transitionPatch("incidents", "reopen", twin.now()),
  });
  assert.deepEqual([reopened.body.statecode, reopened.body.statuscode], [0, 1]);
  const canceled = await twin.request({
    method: "PATCH",
    path: `/incidents(${incident.body.incidentid})`,
    logicalRequestId: "cancel-case",
    headers: { "If-Match": reopened.headers.ETag, Prefer: "return=representation" },
    body: transitionPatch("incidents", "cancel", twin.now()),
  });
  assert.deepEqual([canceled.body.statecode, canceled.body.statuscode], [2, 6]);
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

test("built-in virtual-time scenario keeps tasks open and applies only the SLA transition", async () => {
  const twin = createTwin({ seed: fixtureSeed(), epoch: EPOCH });
  const result = await runBuiltInScenario(twin, "virtual-time");
  assert.equal(result.passed, true);
  assert.equal(result.assertions.length, 2);
  assert.equal(result.assertions[0].actual, 0);
  assert.equal(result.trace.filter((event) => event.type === "transition.applied").length, 1);
  assert.equal(result.trace.find((event) => event.type === "transition.applied").transition, "sla.breached");
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
  const [html, app, css] = await Promise.all([
    readFile(new URL("../docs/d365/index.html", import.meta.url), "utf8"),
    readFile(new URL("../docs/d365/app.mjs", import.meta.url), "utf8"),
    readFile(new URL("../docs/d365/d365.css", import.meta.url), "utf8"),
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
  assert.doesNotMatch(html, /\son(?:click|change|input|submit|keydown)=/i);
  assert.doesNotMatch(html, /(?:src|href)=["']https?:/i);
  assert.doesNotMatch(css, /@import|@font-face|url\(\s*["']?https?:/i);
  assert.doesNotMatch(app, /\.innerHTML\s*=/);
  assert.doesNotMatch(app, /insertAdjacentHTML|outerHTML\s*=|window\.(?:alert|confirm)|\.onclick\s*=/);
  assert.match(app, /textContent/);
  assert.match(app, /Failed to load|could not be loaded/i);
  assert.match(app, /noopener/);
  assert.match(app, /noreferrer/);
  assert.match(html, /<svg[\s>]/);
  assert.doesNotMatch(html, /[♙▤✉✓⇄◫⚗ⓘ☰◆⠿⚠↻↗⊘⌫]/u);
  assert.doesNotMatch(app, /\p{Extended_Pictographic}/u);
});

test("browser release guards are wired into navigation, mutations, and related email rendering", async () => {
  const app = await readFile(new URL("../docs/d365/app.mjs", import.meta.url), "utf8");
  const showLoading = app.slice(
    app.indexOf("function showLoading("),
    app.indexOf("\nfunction showLoadError("),
  );
  const navigate = app.slice(
    app.indexOf("async function navigate("),
    app.indexOf("\nfunction handleDocumentClick("),
  );
  const bulkDelete = app.slice(
    app.indexOf("async function bulkDelete("),
    app.indexOf("\nasync function bulkTransition("),
  );
  const singleDelete = app.slice(
    app.indexOf("async function deleteCurrentRecord("),
    app.indexOf("\nasync function loadRelatedPanel("),
  );
  const clickHandler = app.slice(
    app.indexOf("function handleDocumentClick("),
    app.indexOf("\nfunction handleDocumentKeydown("),
  );
  const manualRequest = app.slice(
    app.indexOf("async function sendManualRequest("),
    app.indexOf("\nasync function runScenario("),
  );

  assert.match(showLoading, /setCommands\(\[\]\)/);
  assert.match(navigate, /setCommands\(\[\]\)/);
  assert.match(app, /captureRouteGuard\(app\.navigationToken, app\.currentRoute\)/);
  assert.match(app, /routeGuardMatches\(guard, app\.navigationToken, app\.currentRoute\)/);
  assert.match(app, /routeGuardIsCurrent\(routeGuard\)/);

  assert.match(bulkDelete, /ensureEntities\(\["contacts", "connections"\]\)/);
  assert.match(bulkDelete, /preflightContactDeletion/);
  assert.ok(
    bulkDelete.indexOf("preflightContactDeletion") < bulkDelete.indexOf("for (const record of selected)"),
    "all selected contacts must be preflighted before the first DELETE",
  );
  assert.match(bulkDelete, /ensureEntities\(\["accounts", "emails"\]\)/);
  assert.match(bulkDelete, /preflightAccountDeletion/);
  assert.ok(
    bulkDelete.indexOf("preflightAccountDeletion") < bulkDelete.indexOf("for (const record of selected)"),
    "all selected accounts must be preflighted before the first DELETE",
  );
  assert.match(singleDelete, /ensureEntities\(\["contacts", "connections"\]\)/);
  assert.match(singleDelete, /Contact cannot be deleted/);
  assert.match(singleDelete, /ensureEntities\(\["accounts", "emails"\]\)/);
  assert.match(singleDelete, /preflightAccountDeletion/);
  assert.match(singleDelete, /Account cannot be deleted/);
  assert.match(manualRequest, /ensureEntities\(\["contacts", "connections"\]\)/);
  assert.match(manualRequest, /preflightContactDeletion/);
  assert.match(manualRequest, /ensureEntities\(\["accounts", "emails"\]\)/);
  assert.match(manualRequest, /preflightAccountDeletion/);
  assert.match(app, /Deactivate instead/);

  assert.match(app, /relatedEmailsForContact\(app\.twin\.getState\("emails"\), record\)/);
  assert.match(app, /relatedEmailsForAccount\(app\.twin\.getState\("emails"\), record\.accountid\)/);
  assert.doesNotMatch(app, /Number\.POSITIVE_INFINITY/);

  assert.match(clickHandler, /shouldInterceptSpaNavigation/);
  for (const option of [
    "button", "ctrlKey", "metaKey", "shiftKey", "altKey", "download", "target",
  ]) {
    assert.match(clickHandler, new RegExp(`${option}:`));
  }
});

test("Knowledge Search exposes a persistent high-contrast focus-within indicator", async () => {
  const css = await readFile(new URL("../docs/d365/d365.css", import.meta.url), "utf8");
  const rule = css.match(/\.knowledge-search-form:focus-within\s*\{([^}]*)\}/);
  assert.ok(rule, "Knowledge Search must expose focus on its visible container");
  assert.match(rule[1], /border-color:\s*var\(--focus\)/);
  assert.match(rule[1], /outline:\s*2px solid var\(--focus\)/);
  assert.match(rule[1], /outline-offset:\s*2px/);
  assert.doesNotMatch(rule[1], /outline:\s*(?:0|none)/);
  assert.match(css, /--focus:\s*#0f6cbd/);
});

test("browser app implements combined grids, record forms, relationships, and process contracts", async () => {
  const app = await readFile(new URL("../docs/d365/app.mjs", import.meta.url), "utf8");
  const processStart = app.indexOf("function buildBusinessProcess(record, editable)");
  const processEnd = app.indexOf("\nfunction renderRecordForm(", processStart);
  const processSource = app.slice(processStart, processEnd);

  assert.match(app, /seedInstallTail:\s*Promise\.resolve\(\)/);
  assert.match(app, /if \(app\.entityPromises\.has\(entity\)\) return app\.entityPromises\.get\(entity\)/);
  assert.match(app, /const pending = app\.seedInstallTail\.then/);
  assert.match(app, /app\.seedInstallTail = pending\.catch/);
  assert.match(app, /combineActivities\(\s*app\.twin\.getState\("emails"\),\s*app\.twin\.getState\("tasks"\)/s);
  assert.match(app, /captureRouteGuard\(expectedToken, app\.currentRoute\)/);
  assert.match(app, /routeGuardIsCurrent\(routeGuard\)/);
  assert.match(app, /PAGE_SIZE/);
  assert.doesNotMatch(app, /MAX_GRID_ROWS|slice\(0,\s*300\)/);
  assert.match(app, /"aria-sort"/);
  assert.match(app, /updateSelection\(state\.selected/);
  assert.match(app, /SYSTEM_VIEWS\.connections/);
  assert.match(app, /relatedConnectionsForContact/);
  assert.match(app, /_relatedName/);
  assert.match(app, /_relationship/);
  assert.doesNotMatch(app, /connection\.name/);
  assert.match(app, /relatedEmailsForContact/);
  assert.match(app, /relatedEmailsForAccount/);
  assert.match(app, /\["Summary", "Details", "Related"\]/);
  assert.match(app, /Contact Information/);
  assert.match(app, /Professional Information/);
  assert.match(app, /Engagement Profile/);
  assert.match(app, /Task Details/);
  assert.match(app, /Case Summary/);
  assert.match(app, /Service Level/);
  for (const commandLabel of [
    "Mark Complete", "Cancel Case", "Resolve Case", "Reopen", "Save & Close",
  ]) {
    assert.match(app, new RegExp(commandLabel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.match(processSource, /\["Identify", "Research", "Resolve"\]/);
  assert.doesNotMatch(processSource, /twin\.request|transitionPatch/);
  assert.match(app, /await ensureEntities\(BUILT_IN_SCENARIOS\.flatMap/);
  assert.match(app, /const target = parsePath\(path\);[\s\S]*await ensureEntity\(target\.entity\);[\s\S]*app\.twin\.request/);
  assert.match(app, /Date\.UTC\(/);
  assert.match(app, /getUTCFullYear|getUTCHours/);
  assert.doesNotMatch(app, /new Date\(control\.value\)|new Date\(value\)\.toISOString/);
});

test("browser form and dashboard wiring enforce the hardened interaction contracts", async () => {
  const app = await readFile(new URL("../docs/d365/app.mjs", import.meta.url), "utf8");
  const contactStart = app.indexOf("contacts: {");
  const accountStart = app.indexOf("accounts: {", contactStart);
  const incidentStart = app.indexOf("incidents: {");
  const activitiesStart = app.indexOf("const ACTIVITIES_GRID", incidentStart);
  const contactConfig = app.slice(contactStart, accountStart);
  const incidentConfig = app.slice(incidentStart, activitiesStart);
  assert.match(contactConfig, /field\("new_status", "Customer status", \{ type: "contact-status" \}\)/);
  assert.doesNotMatch(contactConfig, /field\("new_status"[^)]*editable/);
  assert.match(incidentConfig, /field\("new_sla_status", "SLA status", \{ type: "service-status" \}\)/);
  assert.doesNotMatch(incidentConfig, /field\("new_sla_status"[^)]*editable/);

  for (const title of [
    "Recent Activities",
    "Open Activities",
    "Sent Email",
    "Activities by Type",
    "Activities by Status",
    "Tasks",
  ]) {
    assert.match(app, new RegExp(`"${title}"`));
  }
  assert.match(app, /app\.dashboardView === "service-activity"[\s\S]*serviceActivityDashboardPanels/);
  assert.match(app, /recordCommandActions\(entity, record/);
  assert.match(app, /nextRovingTabIndex\(tabs/);
  assert.match(app, /editableSnapshotsEqual\(baseline, formPayload\(form, entity\)\)/);
  assert.match(app, /disabled: tab === "related" && creating/);
  assert.match(app, /button\.tabIndex = selected \? 0 : -1/);
});

test("dialog, saved-form, history, and direct Dashboard wiring enforce final safety contracts", async () => {
  const app = await readFile(new URL("../docs/d365/app.mjs", import.meta.url), "utf8");
  const showDialog = app.slice(
    app.indexOf("function showDialog("),
    app.indexOf("\nfunction showErrorDialog("),
  );
  const dirtyResolution = app.slice(
    app.indexOf("async function resolveDirtyState("),
    app.indexOf("\nasync function requestNavigation("),
  );
  const dashboard = app.slice(
    app.indexOf("async function renderDashboard("),
    app.indexOf("\nfunction dashboardListPanel("),
  );
  const history = app.slice(
    app.indexOf("async function runHistoryPrompt("),
    app.indexOf("\nfunction formatUtcDate("),
  );

  assert.match(showDialog, /replaceDialogState\(app\.activeDialog, dialog\)/);
  assert.match(
    showDialog,
    /replacement\.replacement\.dialog\.finish\(replacement\.replacement\.value\)/,
  );
  assert.doesNotMatch(app, /dialogFinish/);

  const confirmationCount = [...app.matchAll(/const confirmed = await confirmAction\(/g)].length;
  const strictConfirmationCount = [...app.matchAll(/if \(confirmed !== true \|\|/g)].length;
  assert.equal(confirmationCount, 4);
  assert.equal(strictConfirmationCount, confirmationCount);
  assert.doesNotMatch(app, /if \(!confirmed/);

  assert.match(dirtyResolution, /const savedRecord = await saveRecord\(/);
  assert.match(dirtyResolution, /savedFormRenderTarget\(activeForm, savedRecord, selectedTab\)/);
  assert.match(
    dirtyResolution,
    /renderRecordForm\(renderTarget\.entity, renderTarget\.record, renderTarget\.initialTab\)/,
  );
  assert.ok(
    dirtyResolution.indexOf("await saveRecord")
      < dirtyResolution.indexOf("renderRecordForm(renderTarget.entity"),
  );
  assert.doesNotMatch(dirtyResolution, /Boolean\(await saveRecord/);
  assert.match(app, /const record = app\.activeForm\?\.record/);

  assert.match(history, /function serializedHistoryPrompt/);
  assert.match(history, /if \(app\.historyPromptPromise\) return app\.historyPromptPromise/);
  assert.match(history, /transitionHistoryPrompt\(app\.navigationHistory, proceed\)/);

  assert.match(dashboard, /finally\s*\{/);
  assert.match(dashboard, /dashboardRenderCompletion\(focusTarget\)/);
  assert.match(dashboard, /setBusy\(completion\.busy\)/);
  assert.match(dashboard, /document\.getElementById\(completion\.focusTargetId\)\?\.focus\(\)/);
  assert.match(dashboard, /id: "dashboard-selector"/);
  assert.match(dashboard, /"data-action": "select-dashboard"/);
  assert.match(dashboard, /id: "dashboard-refresh", action: "refresh-dashboard"/);
  assert.match(dashboard, /renderDashboard\(app\.navigationToken, "selector"\)/);
  assert.match(dashboard, /renderDashboard\(refreshGuard\.navigationToken, "refresh"\)/);
});

test("dirty navigation and accessible dialogs replace native alert and confirm", async () => {
  const [html, app] = await Promise.all([
    readFile(new URL("../docs/d365/index.html", import.meta.url), "utf8"),
    readFile(new URL("../docs/d365/app.mjs", import.meta.url), "utf8"),
  ]);
  assert.match(html, /<dialog id="app-dialog"/);
  assert.match(html, /aria-labelledby="dialog-title"/);
  assert.match(app, /function showDialog/);
  assert.match(app, /\.showModal\(\)/);
  assert.match(app, /function trapFocus|const trapFocus/);
  assert.match(app, /event\.key !== "Tab"/);
  assert.match(app, /previousFocus.*focus\(\)/s);
  assert.match(app, /function resolveDirtyState/);
  assert.match(app, /Unsaved changes/);
  assert.match(app, /Save.*Discard changes.*Cancel|Cancel.*Discard changes.*Save/s);
  assert.match(app, /window\.addEventListener\("beforeunload", beforeUnload\)/);
  assert.match(app, /event\.returnValue = ""/);
  assert.match(app, /window\.addEventListener\("popstate", handlePopState\)/);
  assert.match(app, /window\.history\.go\(transition\.effect\.delta\)/);
  assert.doesNotMatch(app, /window\.addEventListener\("hashchange"/);
  assert.doesNotMatch(app, /window\.(?:alert|confirm)/);
});
