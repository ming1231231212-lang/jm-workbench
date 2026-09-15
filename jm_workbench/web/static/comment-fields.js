import { escape as e, select, button } from "./ui.js";

export function commentFields(s, t = {}) {
  const kind = t.kind || "adult_comments",
    d = s.defaults[kind] || {};
  const mode =
    t.comment_mode ||
    (t.id || kind !== "adult_comments" ? "templates" : "core_variants");
  return `<section class="comment-config"><div data-adult-fields>${select(
    "成人用品评论范围",
    "adult_target",
    [
      ["keyword", "与搜索关键词内容一致即可"],
      ["merchant", "商家自己的经营视频（无需先说明库存）"],
      ["inventory", "需要库存、补货或清仓等线索"],
    ],
    t.adult_target || (t.id ? "inventory" : "keyword"),
  )}${select(
    "文案方式",
    "comment_mode",
    [
      ["core_variants", "围绕核心句生成不同表达"],
      ["templates", "使用配置的完整文案"],
    ],
    mode,
  )}</div>
  <label class="field" data-core-field><span>评论核心</span><textarea name="comment_core" rows="2" maxlength="80">${e(t.comment_core || s.adult_comment_core || "")}</textarea><small>保留收货意图，在本机变化称呼、条件句和结尾；不添加对商家的事实判断。同一视频保持同一句，不因去重被拦而换句重发。</small></label>
  <label class="field" data-templates-field><span>完整评论文案 · 每行一条</span><textarea name="templates" rows="3">${e((t.templates || d.templates || []).join("\n"))}</textarea><small>使用条件式收货询问或18+招募文案。</small></label>
  <div class="note" data-comment-note>还需准确视频详情、固定登录身份和开放评论权限。平台共享间隔至少30分钟、滚动24小时最多5条；同一视频不重复，同一作者和相同文本7天内不重复。限制或回执不明会停发。</div>
  <div data-comment-preview>${button("预览文案", "preview-comment")}<div id="comment-preview-result" aria-live="polite"></div></div></section>`;
}

export function syncCommentFields(form) {
  if (!form || form.id !== "task-form") return;
  const adult = form.elements.kind.value === "adult_comments";
  const crawler = form.elements.kind.value === "crawler";
  const generated =
    adult && form.elements.comment_mode.value === "core_variants";
  for (const [selector, show] of [
    ["[data-adult-fields]", adult],
    ["[data-core-field]", generated],
    ["[data-templates-field]", !crawler && !generated],
    ["[data-comment-note]", !crawler],
    ["[data-comment-preview]", !crawler],
  ]) {
    const section = form.querySelector(selector);
    section.hidden = !show;
    section.querySelectorAll("input,textarea,select").forEach((el) => {
      el.disabled = !show;
    });
  }
  form.elements.comment_core.required = generated;
  form.elements.templates.required = !crawler && !generated;
  form.querySelector("#comment-preview-result").replaceChildren();
}

export function taskPayload(values) {
  const data = { ...values };
  for (const key of [
    "max_items",
    "comments_per_item",
    "max_publish",
    "start_hour",
    "end_hour",
  ])
    data[key] = Number(data[key]);
  for (const key of ["keywords", "templates"])
    data[key] = (data[key] || "")
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
  data.enabled = data.enabled === "true";
  data.collect_comments = data.collect_comments === "true";
  if (data.kind !== "adult_comments") {
    data.adult_target = "inventory";
    data.comment_mode = "templates";
    data.comment_core = "";
  }
  return data;
}

export function previewMarkup(result) {
  return `<p>${e(result.target_description)}</p>${result.examples.map((text) => `<blockquote>${e(text)}</blockquote>`).join("")}<small>这里只预览，不保存配置、不加入发送队列。</small>`;
}
