import test from "node:test";
import assert from "node:assert/strict";
import { CommunityWorkspace } from "../jm_workbench/web/static/community-v2.js";

test("slow browser checks cannot delay records or duplicate on refresh", async () => {
  let resolveCheck,
    checks = 0;
  const ui = new CommunityWorkspace({
    request: async (path) => {
      if (path.endsWith("/state"))
        return {
          accounts: [{ id: "a", platform: "tieba", enabled: true, version: 1 }],
          posts: [],
        };
      checks++;
      return new Promise((resolve) => (resolveCheck = resolve));
    },
  });
  const loaded = await ui.load();
  assert.equal(loaded.accounts.length, 1);
  await ui.load();
  assert.equal(checks, 1);
  const pending = ui.backgroundChecks.get("a");
  resolveCheck({ status: "pending", message: "等待登录" });
  await pending;
  assert.equal(ui.data.accounts[0].sync_status, "pending");
});
test("late sync cannot replace a newer manual account check", async () => {
  let resolveCheck;
  const ui = new CommunityWorkspace({
    request: async (path) =>
      path.endsWith("/state")
        ? {
            accounts: [
              { id: "a", platform: "tieba", enabled: true, version: 1 },
            ],
          }
        : new Promise((resolve) => (resolveCheck = resolve)),
  });
  await ui.load();
  const pending = ui.backgroundChecks.get("a");
  ui.syncChecks.set("a", { version: 1, status: "verified", at: Date.now() });
  ui.data.accounts[0].sync_status = "verified";
  resolveCheck({ status: "pending", message: "过期响应" });
  await pending;
  assert.equal(ui.data.accounts[0].sync_status, "verified");
});
import {
  planStatus,
  postStatus,
  filterPosts,
  planProgress,
  csvExport,
  connectionStatus,
} from "../jm_workbench/web/static/community-v2-model.js";
import {
  workspace,
  drawer,
} from "../jm_workbench/web/static/community-v2-views.js";

const data = {
  accounts: [
    {
      id: "a",
      enabled: true,
      platform: "tieba",
      identity: "same",
      sync_status: "verified",
    },
  ],
  platforms: [{ id: "tieba", name: "百度贴吧", automatic: true }],
  risk: [],
  plans: [],
};
const plan = {
  id: "p",
  state: "enabled",
  platform: "tieba",
  payload: { account_id: "a" },
  days: [
    {
      day: "2026-10-03",
      counts: { thread: { submitted: 1 }, reply: { submitted: 5 } },
    },
    {
      day: "2026-10-04",
      counts: { thread: { submitted: 0 }, reply: { submitted: 2 } },
    },
  ],
};
test("platform restriction overrides login and enabled plan without changing data", () => {
  const d = { ...data, risk: [{ platform: "tieba", reason: "restriction" }] };
  assert.equal(planStatus(plan, d).key, "blocked");
  assert.equal(plan.state, "enabled");
  assert.equal(planStatus(plan, data).key, "enabled");
});
test("pending sync is not shown as connected despite historical identity", () => {
  assert.equal(
    connectionStatus({ ...data.accounts[0], sync_status: "pending" }).key,
    "login",
  );
  assert.equal(
    planStatus(plan, {
      ...data,
      accounts: [{ ...data.accounts[0], sync_status: "pending" }],
    }).key,
    "login",
  );
});
test("today progress does not borrow yesterday totals", () => {
  assert.equal(planProgress(plan, "2026-10-04").reply.submitted, 2);
  assert.equal(planProgress(plan, "2026-10-05").reply.submitted, 0);
});
test("unknown overrides accepted and receipts do not imply visible", () => {
  assert.equal(
    postStatus({
      state: "active",
      jobs: [
        { state: "submitted", receipt: { visibility: "unverified" } },
        { state: "unknown" },
      ],
    }).key,
    "unknown",
  );
  assert.equal(
    postStatus({
      jobs: [{ state: "submitted", receipt: { visibility: "unverified" } }],
    }).key,
    "submitted",
  );
  assert.equal(
    postStatus({
      jobs: [{ state: "recorded", receipt: { url: "https://example.com" } }],
    }).key,
    "recorded",
  );
});
test("filters match full body source target and selected plan without assuming one target", () => {
  const posts = [
    {
      id: "p1",
      plan_id: "plan1",
      state: "draft",
      payload: {
        kind: "reply",
        title: "note",
        body: "中文正文",
        source_title: "原帖问题",
        targets: [{ account_id: "a", destination: "https://example.com/123" }],
      },
      jobs: [],
    },
    {
      id: "p2",
      state: "draft",
      payload: { kind: "thread", title: "other", targets: [] },
      jobs: [],
    },
  ];
  assert.equal(
    filterPosts(
      { ...data, posts },
      { q: "原帖问题", kind: "reply", plan: "plan1" },
    ).length,
    1,
  );
  assert.equal(
    filterPosts({ ...data, posts }, { platform: "tieba", q: "中文正文" })
      .length,
    1,
  );
  assert.equal(filterPosts({ ...data, posts }, { plan: "missing" }).length, 0);
});
test("CSV exports full text and neutralizes formulas including leading whitespace", () => {
  const out = csvExport(
    [
      {
        id: "one",
        state: "draft",
        payload: { title: " =2+2", body: 'a,"b"\n下一行', targets: [] },
        jobs: [],
      },
    ],
    data,
  );
  assert.ok(out.includes("' =2+2"));
  assert.ok(out.includes('a,""b""\n下一行'));
});
test("today summary link excludes older accepted posts", () => {
  const posts = [
    {
      payload: { targets: [] },
      jobs: [{ state: "submitted", started: 1791043200 }],
    },
    {
      payload: { targets: [] },
      jobs: [{ state: "submitted", started: 1791043100 }],
    },
  ];
  assert.equal(
    filterPosts({ ...data, posts }, { status: "submitted", day: "2026-10-04" })
      .length,
    1,
  );
});
test("new workspace escapes remote content and only exposes three main views", () => {
  const html = workspace(
    {
      ...data,
      posts: [
        {
          id: "one",
          state: "draft",
          payload: {
            title: "<script>alert(1)</script>",
            body: "<img onerror=x>",
            targets: [],
          },
          jobs: [],
        },
      ],
      post_total: 1,
    },
    { tab: "content", page: 1, selected: new Set() },
  );
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("&lt;script&gt;"));
  assert.equal((html.match(/aria-current="(?:page|false)"/g) || []).length, 3);
});
test("comment drawer never creates script or credentialed links", () => {
  const html = drawer(
    {
      ...data,
      posts: [
        {
          id: "one",
          payload: {
            kind: "reply",
            title: "title",
            body: "<img>",
            source_excerpt: "<iframe>",
            targets: [
              { destination: "javascript:alert(1)" },
              { destination: "https://user:secret@example.com/" },
            ],
          },
          jobs: [],
        },
      ],
    },
    { drawer: { type: "content", id: "one" } },
  );
  assert.ok(!html.includes('href="javascript:'));
  assert.ok(!html.includes('href="https://user:'));
  assert.ok(html.includes("&lt;iframe&gt;"));
  assert.ok(!html.includes("<img>"));
});
