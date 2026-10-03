import * as views from "./views.js";
import { escape as e } from "./ui.js";
import { CommunityUI, communityPage } from "./community.js";
import {
  PublishingUI,
  publishingPage,
  publishingAccounts,
  publishingSettings,
} from "./publishing.js";
import {
  syncCommentFields,
  taskPayload,
  previewMarkup,
} from "./comment-fields.js";
let state,
  page = "",
  dataPage = 1,
  q = "",
  decision = "",
  dataBatch = "latest",
  dataCategory = "",
  busy = false,
  toastTimer,
  loading = false;
const content = document.querySelector("#content"),
  dialog = document.querySelector("#dialog");
const publishing = new PublishingUI({
  request,
  token: () => state?.token || "",
  toast,
  render,
  showForm,
  dialog,
});
const community = new CommunityUI({request, toast, render, showForm, dialog});
function toast(text, error = false) {
  const box = document.querySelector("#toast");
  box.textContent = text;
  box.className = error ? "error" : "";
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (box.hidden = true), 8000);
}
async function request(path, body, method = "POST") {
  const opts =
    body === undefined
      ? {}
      : {
          method,
          headers: {
            "Content-Type": "application/json",
            "X-JM-Token": state?.token || "",
          },
          body: JSON.stringify(body),
        };
  const response = await fetch(path, opts);
  let result;
  try {
    result = await response.json();
  } catch {
    throw Error("服务未返回有效结果，请刷新运行记录确认状态");
  }
  if (!response.ok) throw Error(result.error || "请求未完成");
  return result;
}
async function render() {
  page = location.hash.slice(1) || "tasks";
  if (!views.pages.some((p) => p[0] === page)) page = "tasks";
  const route = views.pages.find((p) => p[0] === page),
    activePage = route[3] || page;
  document.querySelector("#page-label").textContent = views.pages.find(
    (p) => p[0] === page,
  )[2];
  document.querySelector("#nav").innerHTML = views.pages
    .filter((p) => !p[3])
    .map(
      ([id, icon, title]) =>
        `<a href="#${id}" class="${id === activePage ? "active" : ""}" ${id === activePage ? 'aria-current="page"' : ""}><span>${icon}</span>${title}</a>`,
    )
    .join("");
  document.querySelector("#version").textContent =
    "v" + state.version + " · " + state.revision.slice(0, 8);
  document.querySelector('[data-action="launch"]').hidden =
    activePage !== "tasks";
  if (page === "community") {
    content.innerHTML = communityPage(await community.load(), community.tab, community.region, community.query);
  } else if (page === "publishing") {
    const data = await publishing.load();
    content.innerHTML = publishingPage(data, publishing.tab, publishing.filter);
  } else if (page === "accounts") {
    content.innerHTML =
      views.accounts(state) + publishingAccounts(await publishing.load());
  } else if (page === "settings") {
    content.innerHTML =
      views.settings(state) + publishingSettings(await publishing.load());
  } else if (page === "data") {
    const result = await request(
      `/api/data?page=${dataPage}&q=${encodeURIComponent(q)}&decision=${encodeURIComponent(decision)}&batch=${encodeURIComponent(dataBatch)}&category=${encodeURIComponent(dataCategory)}`,
    );
    dataPage = result.page;
    content.innerHTML = views.data(
      state,
      result,
      q,
      decision,
      dataBatch,
      dataCategory,
    );
  } else if (page === "runs")
    content.innerHTML = views.runs(state, await request("/api/attempts"));
  else content.innerHTML = views[page](state);
}
async function refresh(show = false) {
  if (loading) return;
  loading = true;
  try {
    state = await request("/api/state");
    await render();
    if (show) toast("数据已刷新");
  } finally {
    loading = false;
  }
}
function showForm(html) {
  document.querySelector("#dialog-content").innerHTML = html;
  syncCommentFields(document.querySelector("#task-form"));
  dialog.showModal();
}
async function action(name, id) {
  if (name === "close-dialog") return dialog.close();
  if (name === "refresh") return refresh(true);
  if (name.startsWith("pub-")) return publishing.handle(name, id);
  if (name.startsWith("com-")) return community.handle(name, id);
  if (name === "preview-comment") {
    const form = document.querySelector("#task-form");
    if (!form.reportValidity()) return;
    const result = await request(
      "/api/comment-preview",
      taskPayload(Object.fromEntries(new FormData(form))),
    );
    form.querySelector("#comment-preview-result").innerHTML =
      previewMarkup(result);
    return;
  }
  if (name === "new-task" || name === "edit-task")
    return showForm(
      views.taskForm(
        state,
        state.tasks.find((t) => t.id === id),
      ),
    );
  if (name === "new-account" || name === "edit-account")
    return showForm(
      views.accountForm(
        state,
        state.accounts.find((a) => a.id === id),
      ),
    );
  if (name === "data-prev" || name === "data-next") {
    dataPage = Math.max(1, dataPage + (name === "data-prev" ? -1 : 1));
    return render();
  }
  if (name === "filter-category") {
    dataCategory = id || "";
    dataPage = 1;
    return render();
  }
  if (name === "clear-risk")
    return showForm(
      `<form id="risk-form" data-id="${e(id)}"><h2 id="dialog-title">平台限制处理记录</h2><p>确认平台已恢复后填写处理情况。解除后任务仍保持停止。</p><label class="field"><span>处理记录（至少12字）</span><textarea name="note" minlength="12" required></textarea></label><div class="dialog-footer"><button type="button" class="button" data-action="close-dialog">取消</button><button class="button primary">记录并解除</button></div></form>`,
    );
  let result;
  if (name === "launch") {
    result = await request("/api/launch", id ? { task_id: id } : {});
    if (!result.ok)
      throw Error(
        "执行前检查未通过：" +
          result.errors.map((r) => r.name + " · " + r.reason).join("；"),
      );
    toast(
      `已加入 ${result.created.length} 项任务；${result.existing.length} 项任务正在执行`,
    );
  } else if (name === "stop") result = await request("/api/stop", {});
  else if (name === "stop-run")
    result = await request(`/api/runs/${id}/stop`, {});
  else if (name === "continue-run")
    result = await request(`/api/runs/${id}/continue`, {});
  else if (name === "open-account" || name === "check-account") {
    toast(
      name === "open-account"
        ? "正在打开账号浏览器…"
        : "正在核验账号连接，请稍候…",
    );
    result = await request(
      `/api/accounts/${id}/${name === "open-account" ? "open" : "check"}`,
      {},
    );
    if (name === "check-account")
      toast(
        result.connection === "verified"
          ? "账号登录身份已核验"
          : "浏览器连接已验证，平台登录将在采集时检查",
      );
  }
  if (result?.message) toast(result.message);
  await refresh();
}
document.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  event.preventDefault();
  if (busy) return;
  busy = true;
  target.disabled = true;
  try {
    await action(target.dataset.action, target.dataset.id);
  } catch (ex) {
    toast(ex.message, true);
  } finally {
    busy = false;
    target.disabled = false;
  }
});
document.addEventListener("change", async (event) => {
  const el = event.target;
  if (el.matches("[data-pub-upload]")) {
    if (busy) return;
    busy = true;
    try {
      await publishing.upload(el.files);
    } catch (ex) {
      toast(ex.message, true);
    } finally {
      busy = false;
      el.value = "";
    }
    return;
  }
  if (el.matches("[data-pub-filter]") || el.form?.id === "pub-form") {
    try {
      await publishing.change(el);
    } catch (ex) {
      toast(ex.message, true);
    }
    return;
  }
  if (el.matches("[data-binding]")) {
    if (busy) {
      el.checked = !el.checked;
      return;
    }
    busy = true;
    el.disabled = true;
    try {
      await request("/api/matrix", {
        task_id: el.dataset.task,
        account_id: el.dataset.account,
        enabled: el.checked,
      });
      toast("矩阵绑定已保存");
      await refresh();
    } catch (ex) {
      el.checked = !el.checked;
      toast(ex.message, true);
    } finally {
      busy = false;
      el.disabled = false;
    }
  }
  if (el.name === "kind" && el.form?.id === "task-form") {
    const defaults = state.defaults[el.value];
    if (defaults && !el.form.dataset.id)
      for (const key of ["name", "keywords", "templates"])
        el.form.elements[key].value = Array.isArray(defaults[key])
          ? defaults[key].join("\n")
          : defaults[key];
    if (el.value === "crawler") el.form.elements.templates.value = "";
    if (!el.form.dataset.id)
      el.form.elements.comment_mode.value =
        el.value === "adult_comments" ? "core_variants" : "templates";
  }
  if (
    el.form?.id === "task-form" &&
    ["kind", "comment_mode", "adult_target", "publish_scope"].includes(el.name)
  )
    syncCommentFields(el.form);
});
document.addEventListener("input", (event) => {
  if (event.target.form?.id === "task-form")
    event.target.form
      .querySelector("#comment-preview-result")
      .replaceChildren();
});
document.addEventListener('change', event => {
  if(event.target.form?.id==='com-account-form' && event.target.name==='platform') community.syncAccount(event.target.form);
});
document.addEventListener("submit", async (event) => {
  const form = event.target;
  event.preventDefault();
  if (busy) return;
  if (form.id === "data-filter") {
    q = form.elements.q.value;
    decision = form.elements.decision.value;
    dataBatch = form.elements.batch.value;
    dataPage = 1;
    await render();
    return;
  }
  busy = true;
  const submit = form.querySelector('button:not([type="button"])');
  if (submit) submit.disabled = true;
  const data = Object.fromEntries(new FormData(form)),
    id = form.dataset.id;
  try {
    if (form.id.startsWith('com-')) {
      await community.submit(form, event.submitter);
      return;
    }
    if (
      form.id === "pub-form" ||
      form.id === "pub-settings-form" ||
      form.id === "pub-resolve-form"
    ) {
      await publishing.submit(form, event.submitter);
      return;
    } else if (form.id === "task-form") {
      await request(
        "/api/tasks" + (id ? "/" + id : ""),
        taskPayload(data),
        id ? "PUT" : "POST",
      );
    } else if (form.id === "account-form") {
      data.enabled = data.enabled === "true";
      await request(
        "/api/accounts" + (id ? "/" + id : ""),
        data,
        id ? "PUT" : "POST",
      );
    } else if (form.id === "settings-form")
      await request("/api/settings", data, "PUT");
    else if (form.id === "risk-form")
      await request(`/api/risk/${id}/clear`, data);
    dialog.close();
    toast("配置已保存");
    await refresh();
  } catch (ex) {
    toast(ex.message, true);
  } finally {
    busy = false;
    if (submit) submit.disabled = false;
  }
});
window.addEventListener("hashchange", () => {
  if (state) render().catch((ex) => toast(ex.message, true));
});
refresh().catch((ex) => {
  content.innerHTML = `<div class="empty"><h2>暂时连接不到JM工作台</h2><p>${e(ex.message)}</p><button class="button" data-action="refresh">重新连接</button></div>`;
});
setInterval(() => {
  if (
    !busy &&
    !dialog.open &&
    document.visibilityState === "visible" &&
    !["INPUT", "TEXTAREA", "SELECT"].includes(
      document.activeElement?.tagName,
    ) &&
    ["tasks", "publishing", "community", "overview", "runs", "platforms"].includes(page)
  )
    refresh().catch(() => {});
}, 10000);
