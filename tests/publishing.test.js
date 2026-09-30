import test from "node:test";
import assert from "node:assert/strict";
import {
  publishPayload,
  publishingPage,
  publishingAccounts,
  PublishingUI,
} from "../jm_workbench/web/static/publishing.js";
const form = () => {
  const f = new FormData();
  for (const [k, v] of Object.entries({
    request_id: "test-12345678",
    title: " 标题 ",
    account_ids: "sau:1",
    material_ids: "local:1",
    tags: "#经营， 店铺 #经营",
  }))
    f.append(k, v);
  return f;
};
test("publication payload keeps selected account/video combinations and content", () => {
  const f = form();
  f.append("account_ids", "sau:2");
  f.append("material_ids", "local:2");
  const p = publishPayload(f);
  assert.equal(p.title, "标题");
  assert.equal(p.account_ids.length, 2);
  assert.equal(p.material_ids.length, 2);
  assert.deepEqual(p.tags, ["经营", "店铺", "经营"]);
  assert.equal(p.mode, "now");
  assert.equal(p.schedule_at, 0);
});
test("scheduled publication rejects expired and invalid dates", () => {
  for (const d of ["invalid", "2020-01-01T12:00"]) {
    const f = form();
    f.set("mode", "scheduled");
    f.set("schedule", d);
    assert.throws(() => publishPayload(f), /未来/);
  }
  const f = form();
  f.set("mode", "scheduled");
  f.set("schedule", new Date(Date.now() + 3600000).toISOString());
  assert.ok(publishPayload(f).schedule_at > Date.now() / 1000);
});
test("missing account material or title cannot produce launch payload", () => {
  for (const k of ["account_ids", "material_ids", "title"]) {
    const f = form();
    f.delete(k);
    assert.throws(() => publishPayload(f));
  }
});
const base = {
  connected: true,
  materials: [],
  batches: [],
  accounts: [],
  settings: { sau_web_url: "http://127.0.0.1:5173" },
};
test("publication views escape untrusted titles, names, and tags", () => {
  const payload = publishPayload(form());
  payload.title = "<img src=x onerror=alert(1)>";
  payload.tags = ["<script>"];
  const html = publishingPage({
    ...base,
    batches: [{ id: "one", state: "draft", payload, jobs: [], created: 1 }],
  });
  assert.ok(!html.includes("<img"));
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("&lt;img"));
  assert.ok(html.includes("本地草稿"));
  const accounts = publishingAccounts({
    ...base,
    accounts: [
      { name: "<svg onload=alert(1)>", platform: "ks", status: "needs_login" },
    ],
  });
  assert.ok(!accounts.includes("<svg"));
  assert.ok(accounts.includes("需要重新登录"));
});
test("generic submitted receipt is visibly not a verified publication", () => {
  const html = publishingPage({
    ...base,
    batches: [
      {
        id: "one",
        state: "submitted",
        payload: publishPayload(form()),
        jobs: [{ state: "submitted", platform: "ks" }],
        created: 1,
      },
    ],
  });
  assert.ok(html.includes("已提交 · 未核验"));
  assert.ok(!html.includes("发布成功"));
});
test("composer disables account with missing login and uses local draft by default", () => {
  let html = "";
  const ui = new PublishingUI({ showForm: (x) => (html = x) });
  ui.data = {
    ...base,
    accounts: [
      { id: "sau:1", name: "Account", platform: "ks", status: "needs_login" },
    ],
  };
  ui.compose(ui.newDraft());
  assert.match(html, /name="account_ids"[^>]+disabled/);
  assert.match(html, /value="draft">保存草稿/);
  assert.match(html, /存入平台草稿（仅视频号）/);
  assert.match(html, /data-pub-schedule hidden/);
});
test("filter changes results without changing records", () => {
  const data = {
    ...base,
    batches: [
      {
        id: "one",
        state: "draft",
        payload: publishPayload(form()),
        jobs: [],
        created: 1,
      },
    ],
  };
  const html = publishingPage(data, "batches", "unknown");
  assert.ok(html.includes("没有这个状态的任务"));
  assert.equal(data.batches.length, 1);
});
