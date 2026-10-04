import { CommunityUI } from "./community.js";
import { escape as e, button as b, field, select } from "./ui.js";
import { workspace, drawer, currentDay } from "./community-v2-views.js";
import {
  filterPosts,
  csvExport,
  getAccount,
  connectionStatus,
  getPlatform,
} from "./community-v2-model.js";
import { icon } from "./community-icons.js";

export class CommunityWorkspace extends CommunityUI {
  constructor(opts) {
    super(opts);
    this.hostRender = opts.render;
    this.tab = "plans";
    this.filters = {
      tab: "plans",
      q: "",
      platform: "",
      status: "",
      kind: "",
      plan: "",
      page: 1,
      accountMode: "list",
      selected: new Set(),
      drawer: null,
      drawerTab: "summary",
    };
    this.render = async () => this.repaint();
    this.wizard = null;
    this.returnFocus = null;
    this.backgroundChecks = new Map();
  }
  async loadAndSync() {
    // Render persisted records first; slow identity checks must not hide the workspace.
    const data = await this.request("/api/community/state");
    this.data = data;
    for (const account of data.accounts) {
      if (
        !account.enabled ||
        !["tieba", "juejin", "csdn"].includes(account.platform)
      )
        continue;
      const cached = this.syncChecks.get(account.id);
      if (cached?.version === account.version) {
        account.sync_status = cached.status;
        account.sync_message = cached.message;
      }
      const interval = account.platform === "tieba" ? 30000 : 300000;
      if (
        !this.backgroundChecks.has(account.id) &&
        (!cached ||
          cached.version !== account.version ||
          this.clock() - cached.at >= interval)
      )
        this.startBackgroundCheck(account);
    }
    return data;
  }
  startBackgroundCheck(account) {
    const check = { at: this.clock(), version: account.version };
    this.syncChecks.set(account.id, check);
    const pending = this.request(
      `/api/community/accounts/${account.id}/sync`,
      {},
    )
      .catch(() => ({
        status: "pending",
        message: "同步未完成，可点击“检查连接”重试",
      }))
      .then((result) => {
        // A newer manual check, account edit or removal wins over a delayed response.
        if (this.syncChecks.get(account.id) !== check) return;
        const current = this.data?.accounts.find((a) => a.id === account.id);
        if (!current || current.version !== check.version) return;
        Object.assign(check, {
          status: result.status,
          message: result.message,
        });
        if (result.account) Object.assign(current, result.account);
        current.sync_status = check.status;
        current.sync_message = check.message;
        if (
          typeof document !== "undefined" &&
          !document.querySelector("#dialog[open]")
        )
          this.repaint();
      })
      .finally(() => this.backgroundChecks.delete(account.id));
    this.backgroundChecks.set(account.id, pending);
  }
  page() {
    this.filters.tab = this.tab;
    return workspace(this.data, this.filters);
  }
  repaint() {
    const root = document.querySelector("#community-v2");
    if (!root) return;
    const active = document.activeElement,
      search = active?.id === "community-search",
      selection = search ? [active.selectionStart, active.selectionEnd] : null;
    root.outerHTML = this.page();
    if (search) {
      const input = document.querySelector("#community-search");
      input.focus({ preventScroll: true });
      input.setSelectionRange(...selection);
    }
    if (this.filters.drawer) this.draw();
  }
  activate() {
    document.body.classList.add("community-v2");
    if (!document.querySelector("#community-drawer")) {
      const d = document.createElement("dialog");
      d.id = "community-drawer";
      d.className = "drawer";
      d.setAttribute("aria-labelledby", "community-drawer-title");
      d.innerHTML = '<div id="drawer-content"></div>';
      document.body.append(d);
      d.addEventListener("close", () => {
        this.filters.drawer = null;
        const target = this.returnFocus;
        if (target?.isConnected) target.focus({ preventScroll: true });
        else
          document
            .querySelector("#community-v2 .page-heading button")
            ?.focus({ preventScroll: true });
      });
    }
  }
  deactivate() {
    document.querySelector("#community-drawer")?.close();
    document.body.classList.remove("community-v2");
  }
  openDetail(type, id) {
    this.returnFocus = document.activeElement;
    this.filters.drawer = { type, id };
    this.filters.drawerTab = "summary";
    this.draw();
    const d = document.querySelector("#community-drawer");
    if (!d.open) d.showModal();
  }
  draw() {
    const html = drawer(this.data, this.filters);
    if (html === null) {
      document.querySelector("#community-drawer")?.close();
      return;
    }
    document.querySelector("#drawer-content").innerHTML = html;
    document
      .querySelector('[data-action="com-v2-close"]')
      ?.setAttribute("aria-label", "关闭详情");
  }
  clear() {
    Object.assign(this.filters, {
      q: "",
      platform: "",
      status: "",
      kind: "",
      plan: "",
      day: "",
      page: 1,
    });
    this.filters.selected.clear();
  }
  changeView(tab) {
    this.tab = tab;
    this.clear();
    document.querySelector("#community-drawer")?.close();
    this.repaint();
  }
  change(el) {
    if (el.dataset.comFilter) {
      this.filters[el.dataset.comFilter] = el.value;
      this.filters.page = 1;
      this.filters.selected.clear();
      return this.repaint();
    }
    if (el.dataset.comSelect) {
      const ids =
        el.dataset.comSelect === "all"
          ? filterPosts(this.data, this.filters)
              .slice((this.filters.page - 1) * 8, this.filters.page * 8)
              .map((p) => p.id)
          : [el.dataset.comSelect];
      ids.forEach((id) =>
        el.checked
          ? this.filters.selected.add(id)
          : this.filters.selected.delete(id),
      );
      return this.repaint();
    }
    if (el.name === "wizard_platform" && el.form?.id === "com-v2-wizard") {
      this.readWizard();
      this.wizard.data.account_id =
        this.data.accounts.find((a) => a.platform === el.value && a.enabled)
          ?.id || "";
      return this.renderWizard();
    }
    if (el.name === "account_id" && el.form?.id === "com-v2-wizard") {
      this.readWizard();
      return this.renderWizard();
    }
  }
  export(selected = false) {
    const posts = selected
      ? this.data.posts.filter((p) => this.filters.selected.has(p.id))
      : filterPosts(this.data, this.filters);
    const url = URL.createObjectURL(
      new Blob([csvExport(posts, this.data)], {
        type: "text/csv;charset=utf-8;",
      }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "JM-社区发布-" + currentDay(this.data) + ".csv";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    this.toast("已导出 " + posts.length + " 条内容");
  }
  startWizard(id) {
    const p = this.data.plans.find((p) => p.id === id);
    if (p?.state === "enabled") throw Error("请先暂停计划，再修改设置");
    const accounts = this.data.accounts.filter(
      (a) => a.enabled && ["tieba", "juejin", "csdn"].includes(a.platform),
    );
    if (!accounts.length) {
      this.toast("先添加一个支持每日计划的社区账号");
      return this.accountForm();
    }
    const d = structuredClone(
      p?.payload || {
        name: "",
        account_id: accounts[0].id,
        board: "",
        rules_note: "",
        hour: 10,
        minute: 0,
        source_boards: [],
        topics: [],
        replies: [],
        reply_rules: [],
      },
    );
    this.wizard = {
      id: id || "",
      step: 1,
      data: d,
      platform: getAccount(this.data, d.account_id)?.platform || "tieba",
    };
    this.renderWizard();
  }
  readWizard() {
    if (!this.wizard) return;
    const f = document.querySelector("#com-v2-wizard");
    if (!f) return;
    const d = this.wizard.data;
    for (const key of ["name", "account_id", "board", "rules_note"])
      if (f.elements[key]) d[key] = f.elements[key].value.trim();
    if (f.elements.wizard_platform)
      this.wizard.platform = f.elements.wizard_platform.value;
    if (f.elements.source_boards)
      d.source_boards = f.elements.source_boards.value
        .split(/[,，]/)
        .map((s) => s.trim())
        .filter(Boolean);
    if (f.elements.start_time) {
      const parts = f.elements.start_time.value.split(":").map(Number);
      d.hour = parts[0];
      d.minute = parts[1];
    }
  }
  wizardError(text) {
    const box = document.querySelector("#com-v2-form-error");
    box.textContent = text;
    box.hidden = false;
    box.focus();
  }
  validateStep() {
    const f = document.querySelector("#com-v2-wizard");
    this.readWizard();
    if (!f.reportValidity()) return false;
    const w = this.wizard;
    if (w.step === 1 && !getAccount(this.data, w.data.account_id)) {
      this.wizardError("请选择一个可用账号");
      return false;
    }
    if (w.step === 2 && w.data.source_boards.length > 3) {
      this.wizardError("评论来源最多填写 3 个");
      return false;
    }
    return true;
  }
  renderWizard() {
    const w = this.wizard,
      d = w.data,
      a = getAccount(this.data, d.account_id),
      risk = this.data.risk.find((r) => r.platform === w.platform);
    let body = "";
    if (w.step === 1)
      body = `<div class="form-row">${select(
        "平台",
        "wizard_platform",
        [
          ["tieba", "百度贴吧"],
          ["juejin", "稀土掘金"],
          ["csdn", "CSDN"],
        ],
        w.platform,
      )}${select(
        "发布账号",
        "account_id",
        this.data.accounts
          .filter((a) => a.enabled && a.platform === w.platform)
          .map((a) => [a.id, a.name]),
        d.account_id,
      )}</div><div class="source-summary"><strong>${e(a ? connectionStatus(a).label : "该平台尚无可用账号")}</strong>${risk ? e(risk.reason) : "选择账号后，继续设置目标和每日安排。"}${w.id ? "<br>已有计划保留原账号，历史记录不会转移。" : ""}</div><p class="form-note">每日计划目前支持贴吧、掘金和 CSDN。其他平台可在内容记录中创建帖子。</p>`;
    if (w.step === 2)
      body =
        field(
          "计划名称",
          "name",
          d.name,
          "text",
          'required maxlength="60" placeholder="例如：趣造AI · 日常分享"',
        ) +
        field(
          w.platform === "tieba"
            ? "目标贴吧（吧名）"
            : w.platform === "juejin"
              ? "文章分类"
              : "文章位置",
          "board",
          d.board,
          "text",
          `required maxlength="50" placeholder="${w.platform === "tieba" ? "人工智能" : w.platform === "juejin" ? "人工智能" : "博客"}"`,
        ) +
        (w.platform === "csdn"
          ? '<p class="form-note">CSDN使用指定原帖评论素材；自动查找目标尚未接入。</p>'
          : field(
              "评论来源（标签 / 吧名，最多3个）",
              "source_boards",
              d.source_boards.join("，"),
              "text",
              'placeholder="人工智能，AI编程，Agent"',
            )) +
        `<label class="field"><span>发布位置与内容规则</span><textarea name="rules_note" rows="3" required minlength="12" maxlength="1000" placeholder="记录目标社区允许的内容、要回复的问题类型等…">${e(d.rules_note)}</textarea></label>`;
    if (w.step === 3)
      body =
        field(
          "每天开始时间（北京时间）",
          "start_time",
          `${String(d.hour).padStart(2, "0")}:${String(d.minute).padStart(2, "0")}`,
          "time",
          'required max="20:59"',
        ) +
        `<div class="detail-stats"><div class="detail-stat"><span>每日帖子</span><strong>1 <small>篇</small></strong></div><div class="detail-stat"><span>每日评论</span><strong>5 <small>个不同原帖</small></strong></div></div><div class="wizard-review"><h3>${e(d.name)}</h3><p>${e(a?.name)} · ${e(d.board)}</p><p>已有帖子素材 ${d.topics.length} 篇 · 指定帖评论 ${d.replies.length} 条 · 匹配规则 ${d.reply_rules.length} 条</p></div><div class="source-summary">每个原帖只评论一次，间隔至少 30 分钟。保存后可从计划详情补充素材；素材不足时保留缺口，不重复凑数。</div>${risk ? `<div class="detail-alert red"><strong>平台暂停，暂不可启用</strong>${e(risk.reason)}</div>` : ""}`;
    this.showForm(
      `<form id="com-v2-wizard" data-id="${e(w.id)}"><div class="dialog-header"><div><h2 id="dialog-title">${w.id ? "修改" : "新建"}发布计划</h2><p>分三步设置，每一步只处理一件事。</p></div>${b(icon("x"), "close-dialog", "", "icon-button")}</div><div class="wizard-steps">${["平台与账号", "内容与目标", "执行安排"].map((s, i) => `<div class="wizard-step ${i + 1 === w.step ? "current" : i + 1 < w.step ? "done" : ""}"><b>${i + 1}</b>${s}</div>`).join("")}</div><div class="form-error" id="com-v2-form-error" role="alert" tabindex="-1" hidden></div>${body}<div class="dialog-footer">${w.step > 1 ? b("上一步", "com-v2-wizard-back") : b("取消", "close-dialog")}${w.step === 3 ? '<button class="button" name="finish" value="save">保存设置</button><button class="button primary" name="finish" value="enable" ' + (risk || !a || connectionStatus(a).key !== "connected" ? 'disabled title="先完成账号连接并处理平台暂停"' : "") + ">保存并启用</button>" : '<button class="button primary" name="finish" value="next">下一步 ' + icon("arrow-right") + "</button>"}</div></form>`,
    );
    if (w.id && w.step === 1) {
      const f = document.querySelector("#com-v2-wizard");
      f.elements.account_id.disabled = true;
      f.elements.wizard_platform.disabled = true;
    }
  }
  async submitWizard(form, submitter) {
    if (!this.validateStep()) return;
    if (this.wizard.step < 3) {
      this.wizard.step++;
      this.renderWizard();
      return;
    }
    const w = this.wizard;
    let result;
    try {
      result = await this.request(
        "/api/community/plans" + (w.id ? "/" + w.id : ""),
        w.data,
        w.id ? "PUT" : "POST",
      );
      w.id = result.id;
      form.dataset.id = result.id;
      if (submitter?.value === "enable")
        result = await this.request(`/api/community/plans/${w.id}/enable`, {});
    } catch (ex) {
      this.wizardError((w.id ? "设置已保存或原计划已保留；" : "") + ex.message);
      await this.load();
      return;
    }
    this.tab = "plans";
    this.clear();
    this.dialog.close();
    await this.fresh();
    this.openDetail("plan", w.id);
    this.toast(result.message);
    this.wizard = null;
  }
  async handle(action, id) {
    if (action === "com-tab") {
      const kind = id === "posts" ? "thread" : id === "replies" ? "reply" : "";
      this.changeView(
        ["posts", "replies", "content"].includes(id)
          ? "content"
          : id === "platforms"
            ? "accounts"
            : id,
      );
      this.filters.kind = kind;
      if (id === "platforms") this.filters.accountMode = "matrix";
      return this.repaint();
    }
    if (action === "com-view") return this.openDetail("content", id);
    if (action === "com-v2-plan") return this.openDetail("plan", id);
    if (action === "com-v2-account") return this.openDetail("account", id);
    if (action === "com-v2-close")
      return document.querySelector("#community-drawer").close();
    if (action === "com-v2-clear") {
      this.clear();
      return this.repaint();
    }
    if (action === "com-v2-kind") {
      this.filters.kind = id;
      this.filters.page = 1;
      this.filters.selected.clear();
      return this.repaint();
    }
    if (action === "com-v2-page") {
      this.filters.page = Number(id);
      return this.repaint();
    }
    if (action === "com-v2-account-mode") {
      this.filters.accountMode = id;
      this.filters.q = "";
      this.filters.platform = "";
      return this.repaint();
    }
    if (action === "com-v2-drawer-tab") {
      this.filters.drawerTab = id;
      return this.draw();
    }
    if (action === "com-v2-plan-posts") {
      this.changeView("content");
      this.filters.plan = id;
      return this.repaint();
    }
    if (action === "com-v2-stat") {
      if (["thread", "reply"].includes(id)) {
        this.changeView("content");
        this.filters.kind = id;
        this.filters.status = "submitted";
        this.filters.day = currentDay(this.data);
      } else {
        this.filters.status = this.filters.status === id ? "" : id;
      }
      return this.repaint();
    }
    if (action === "com-v2-material-help") {
      this.toast("点击计划 → 规则与素材，可补充帖子、指定帖评论和匹配规则");
      return;
    }
    if (action === "com-v2-compose") {
      this.showForm(
        `<div class="dialog-header"><div><h2 id="dialog-title">写内容</h2><p>选择要保存或发布的内容类型。</p></div>${b(icon("x"), "close-dialog", "", "icon-button")}</div><div class="option-grid">${b(icon("file-text") + "发布帖子", "com-new", "", "option")}${b(icon("message-square") + "评论原帖", "com-new-reply", "", "option")}</div>`,
      );
      return;
    }
    if (action === "com-v2-copy") {
      const p = this.data.posts.find((p) => p.id === id);
      await navigator.clipboard.writeText(p.payload.body);
      return this.toast("正文已复制");
    }
    if (action === "com-v2-export" || action === "com-v2-export-selected")
      return this.export(action.endsWith("selected"));
    if (action === "com-v2-unselect") {
      this.filters.selected.clear();
      return this.repaint();
    }
    if (action === "com-v2-bulk-pause") {
      const ids = this.data.posts
        .filter(
          (p) =>
            this.filters.selected.has(p.id) &&
            p.jobs?.some((j) => j.state === "queued"),
        )
        .map((p) => p.id);
      let done = 0;
      try {
        for (const id of ids) {
          await this.request(`/api/community/posts/${id}/pause`, {});
          done++;
        }
      } finally {
        this.filters.selected.clear();
        await this.fresh();
        this.toast(`已暂停 ${done} / ${ids.length} 条等待内容`);
      }
      return;
    }
    if (action === "com-v2-cancel") {
      this.showForm(
        `<div class="dialog-header"><h2 id="dialog-title">取消这条内容？</h2>${b(icon("x"), "close-dialog", "", "icon-button")}</div><p>停止尚未提交的目标，历史内容与回执保留。</p><div class="dialog-footer">${b("返回", "close-dialog")}${b("确认取消", "com-v2-confirm-cancel", id, "danger")}</div>`,
      );
      return;
    }
    if (action === "com-v2-confirm-cancel") {
      await super.handle("com-cancel", id);
      this.dialog.close();
      return;
    }
    if (action === "com-plan-new" || action === "com-plan-edit")
      return this.startWizard(id);
    if (action === "com-v2-wizard-back") {
      this.readWizard();
      this.wizard.step--;
      return this.renderWizard();
    }
    return super.handle(action, id);
  }
  async submit(form, submitter) {
    if (form.id === "com-v2-wizard") return this.submitWizard(form, submitter);
    await super.submit(form, submitter);
    if (["posts", "replies"].includes(this.tab)) {
      this.filters.kind = this.tab === "replies" ? "reply" : "thread";
      this.tab = "content";
      this.repaint();
    }
    if (form.id === "com-delete-account-form")
      document.querySelector("#community-drawer")?.close();
  }
}
