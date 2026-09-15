import test from "node:test";
import assert from "node:assert/strict";
import { escape, button } from "../jm_workbench/web/static/ui.js";
import * as views from "../jm_workbench/web/static/views.js";
import {
  taskPayload,
  previewMarkup,
} from "../jm_workbench/web/static/comment-fields.js";
const s = {
  accounts: [],
  tasks: [],
  bindings: [],
  runs: [],
  counts: {},
  attempt_counts: {},
  history_count: 0,
  risk: [],
  events: [],
  platforms: [{ id: "ks", name: "快手", crawler: true, comment: true }],
  settings: {},
  defaults: {},
};
test("untrusted data cannot produce executable HTML", () => {
  assert.equal(
    escape('<img src=x onerror="alert(1)">'),
    "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;",
  );
  const html = views.tasks({
    ...s,
    tasks: [
      {
        id: "x",
        name: "<script>alert(1)</script>",
        kind: "crawler",
        platform: "ks",
        enabled: true,
        keywords: ["<img>"],
        max_items: 1,
      },
    ],
  });
  assert.ok(!html.includes("<script>"));
  assert.ok(!html.includes("<img>"));
});
test("dialog action buttons never submit form implicitly", () =>
  assert.ok(button("取消", "close-dialog").includes('type="button"')));
test("all eight modules provide meaningful empty states", () => {
  for (const name of [
    "overview",
    "tasks",
    "accounts",
    "matrix",
    "platforms",
    "runs",
    "settings",
  ])
    assert.ok(views[name](s).length > 100);
  assert.ok(
    views
      .data(s, { items: [], total: 0, page: 1 })
      .includes("没有符合条件的数据"),
  );
});
test("matrix disables incompatible platform bindings", () => {
  const html = views.matrix({
    ...s,
    accounts: [{ id: "a", name: "a", platform: "dy", enabled: true }],
    tasks: [
      { id: "t", name: "t", platform: "ks", enabled: true, kind: "crawler" },
    ],
  });
  assert.ok(html.includes("平台不匹配"));
  assert.ok(!html.includes('data-binding="true"'));
});

test("data page explains grouping and configured comments without approval buttons", () => {
  const html = views.data(s, {
    items: [
      {
        id: 1,
        platform: "ks",
        category: "merchant",
        category_label: "门店 / 品牌线索",
        data: { nickname: "某店", caption: "<script>bad</script>" },
        keywords: ["词一", "词二"],
        occurrences: 2,
        comment_preview: {
          label: "不会评论",
          reason: "缺少正文证据",
          templates: [],
        },
      },
    ],
    total: 1,
    page: 1,
    summary: {
      records: 2,
      unique: 1,
      duplicates: 1,
      content_matches: 0,
      categories: [{ id: "merchant", label: "门店 / 品牌线索", count: 1 }],
    },
    comment_templates: [
      {
        name: "当前任务",
        kind: "adult_comments",
        enabled: true,
        start_hour: 20,
        end_hour: 23,
        templates: ["当前真实配置模板"],
      },
    ],
    batches: [],
  });
  assert.ok(html.includes("当前真实配置模板"));
  assert.ok(html.includes("不会评论"));
  assert.ok(html.includes("2 次采集记录已合并"));
  assert.ok(html.includes("词一、词二"));
  assert.ok(html.includes('value="latest" selected'));
  assert.ok(!html.includes("<script>"));
  assert.ok(!html.includes('data-action="launch"'));
});

test("comment editing separates scope, core and full templates with safe previews", () => {
  const html = views.taskForm({
    ...s,
    adult_comment_core: "店里如果有积压或停卖的货可以找我哦",
  });
  assert.ok(html.includes('name="adult_target"'));
  assert.ok(html.includes('value="keyword" selected'));
  assert.ok(html.includes('value="core_variants" selected'));
  assert.ok(html.includes('name="comment_core"'));
  assert.ok(html.includes('data-action="preview-comment"'));
  const legacy = views.taskForm(s, {
    id: "old",
    kind: "adult_comments",
    templates: ["旧文案"],
  });
  assert.ok(legacy.includes('value="inventory" selected'));
  assert.ok(legacy.includes('value="templates" selected'));
  const preview = previewMarkup({
    target_description: "商家自己的经营视频",
    examples: ["<script>unsafe</script>"],
  });
  assert.ok(!preview.includes("<script>"));
  assert.ok(preview.includes("不加入发送队列"));
});

test("task form serializes comment fields without carrying adult mode into other business", () => {
  const values = {
    kind: "adult_comments",
    adult_target: "merchant",
    comment_mode: "core_variants",
    comment_core: "核心句",
    keywords: "词一\n词二",
    enabled: "true",
    collect_comments: "false",
    max_items: "10",
    max_publish: "1",
    start_hour: "20",
    end_hour: "23",
    comments_per_item: "10",
  };
  const payload = taskPayload(values);
  assert.equal(payload.comment_core, "核心句");
  assert.equal(payload.adult_target, "merchant");
  assert.deepEqual(payload.templates, []);
  assert.deepEqual(payload.keywords, ["词一", "词二"]);
  assert.equal(payload.max_publish, 1);
  const other = taskPayload({
    ...values,
    kind: "peiwang_comments",
    templates: "陪玩原文案",
  });
  assert.equal(other.comment_mode, "templates");
  assert.equal(other.comment_core, "");
  assert.equal(other.adult_target, "inventory");
  assert.deepEqual(other.templates, ["陪玩原文案"]);
});
