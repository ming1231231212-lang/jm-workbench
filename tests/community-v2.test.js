import test from "node:test";
import assert from "node:assert/strict";
import { CommunityWorkspace } from "../jm_workbench/web/static/community-v2.js";

test("viewing and refreshing records does not connect to account browsers", async () => {
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
  assert.equal(checks, 0);
  ui.startBackgroundCheck(ui.data.accounts[0]);
  ui.startBackgroundCheck(ui.data.accounts[0]);
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
  ui.startBackgroundCheck(ui.data.accounts[0]);
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

test("disabled browser control overrides old verified identity and enabled plan", () => {
  const a={...data.accounts[0],automatic_execution:false};
  assert.equal(connectionStatus(a).key,"manual");
  assert.equal(planStatus(plan,{...data,accounts:[a]}).key,"manual");
  assert.equal(planStatus(plan,{...data,accounts:[a],risk:[{platform:"tieba",reason:"restriction"}]}).key,"blocked");
});

test("web-only content offers a safe handoff instead of continuing automatic sending", () => {
  const d={...data,platforms:[{...data.platforms[0],automatic:false}],posts:[{
    id:"one",state:"active",payload:{title:"saved",body:"exact body",targets:[{account_id:"a"}]},
    jobs:[{id:"j",platform:"tieba",account_id:"a",state:"paused",started:0,receipt:{}}],
  }]};
  const html=drawer(d,{drawer:{type:"content",id:"one"}});
  assert.ok(html.includes('data-action="com-to-web"'));
  assert.ok(!html.includes('data-action="com-resume"'));
  d.posts[0].jobs[0].started=1;
  assert.ok(!drawer(d,{drawer:{type:"content",id:"one"}}).includes('data-action="com-to-web"'));
  d.posts[0].jobs[0].started=0;d.risk=[{platform:"tieba",reason:"restriction"}];
  assert.ok(!drawer(d,{drawer:{type:"content",id:"one"}}).includes('data-action="com-to-web"'));
});
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

test("cross-day receipt distinguishes actual submission from original plan date", () => {
  const post={id:'catchup',created:1,state:'active',plan_id:plan.id,plan_day:'2026-10-17',payload:{kind:'thread',title:'Catchup',body:'Original body',targets:[]},
    jobs:[{id:'sent',platform:'tieba',state:'submitted',started:1792380000,receipt:{url:'https://tieba.baidu.com/p/123456',visibility:'account_visible'}}]};
  const d={...data,posts:[post],plans:[plan]};
  assert.ok(drawer(d,{drawer:{type:'content',id:'catchup'}}).includes('实际提交：'));
  assert.ok(drawer(d,{drawer:{type:'plan',id:plan.id},drawerTab:'content'}).includes('原计划 2026-10-17'));
  assert.ok(drawer(d,{drawer:{type:'plan',id:plan.id},drawerTab:'summary'}).includes('按实际发送日期'));
  post.jobs[0].state='unknown';
  assert.ok(!drawer(d,{drawer:{type:'content',id:'catchup'}}).includes('实际提交：'));
});

test("registered receipts count in plan progress without claiming automated acceptance", () => {
  const p={...plan,payload:{...plan.payload,name:"Daily",board:"ai",hour:1,minute:0,source_boards:[]},
    days:[{day:"2026-10-14",counts:{thread:{submitted:0,recorded:1},reply:{submitted:0,recorded:5}}}]};
  const d={...data,plans:[p],posts:[],summary:{day:"2026-10-14"}};
  assert.equal(planProgress(p,"2026-10-14").reply.completed,5);
  assert.equal(planProgress(p,"2026-10-14").reply.submitted,0);
  assert.equal(planProgress(p,"2026-10-15").reply.completed,0);
  const html=workspace(d,{tab:"plans",selected:new Set()});
  assert.ok(html.includes('帖子 <b>1/1</b>') && html.includes('评论 <b>5/5</b>'));
  assert.ok(html.includes('含网页登记 1 帖 / 5 评') && html.includes('每天 01:00'));
  const detail=drawer(d,{drawer:{type:"plan",id:"p"},drawerTab:"summary"});
  assert.ok(detail.includes('com-plan-sync-receipts') && detail.includes('具体结果查看内容回执'));
});
test("article-only goals and historical goals stay separate", () => {
  const p={...plan,payload:{...plan.payload,replies_per_day:0}};
  assert.equal(planProgress(p,"2026-10-06").replyGoal,0);
  p.days=[{day:"2026-10-05",reply_goal:5,next_check:123}];
  assert.equal(planProgress(p,"2026-10-05").replyGoal,5);
  assert.equal(planProgress(p,"2026-10-05").nextCheck,123);
});

test("plan list exposes next check and zero reply goal", () => {
  const p={...plan,payload:{...plan.payload,name:"Test",board:"ai",hour:10,minute:0,replies_per_day:0},days:[],next_action_at:1791279000,next_action:"重新检查素材、目标与账号连接"};
  const html=workspace({...data,plans:[p],posts:[],summary:{day:"2026-10-06"}}, {tab:"plans",selected:new Set()});
  assert.ok(html.includes("评论已关闭"));
  assert.ok(html.includes("重新检查素材、目标与账号连接") && html.includes("北京时间"));
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
test("workspace escapes remote content without duplicating sidebar navigation", () => {
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
  assert.equal((html.match(/aria-current="(?:page|false)"/g) || []).length, 0);
  assert.ok(html.includes('内容与记录'));
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


test("posts-only progress retains historical comments without filling article progress", () => {
  const p={...plan,payload:{...plan.payload,name:"Daily",board:"ai",hour:1,minute:0,source_boards:[],replies_per_day:0},
    days:[{day:"2026-10-14",reply_goal:0,counts:{thread:{recorded:0},reply:{recorded:5}}}]};
  const d={...data,plans:[p],posts:[],summary:{day:"2026-10-14"}};
  const html=workspace(d,{tab:"plans",selected:new Set()});
  assert.ok(html.includes("每天 01:00 · 仅发帖子") && html.includes("评论已关闭"));
  assert.ok(html.includes('max="1" value="0"') && !html.includes("5/0"));
  const detail=drawer(d,{drawer:{type:"plan",id:"p"},drawerTab:"summary"});
  assert.ok(detail.includes("今日已发布 5 条，记录保留") && !detail.includes("5/0"));
});
