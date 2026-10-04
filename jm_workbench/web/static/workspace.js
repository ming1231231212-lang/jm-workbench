import { icon } from "./community-icons.js";

export const routeIcons = {
  tasks: "list-checks",
  publishing: "video",
  community: "messages-square",
  data: "chart-no-axes-combined",
  accounts: "users-round",
  settings: "settings-2",
};

export function savedDensity(storage) {
  try {
    return (
      (storage.getItem("jm-workspace-density") ??
        storage.getItem("jm-community-density")) === "compact"
    );
  } catch {
    return false;
  }
}

// Each async render owns a ticket. Later navigation always wins.
export class ViewRequests {
  constructor() {
    this.sequence = 0;
  }
  begin() {
    const ticket = ++this.sequence;
    return () => ticket === this.sequence;
  }
}

export function initializeWorkspace() {
  const body = document.body,
    menu = document.querySelector(".community-mobile-menu");
  const sidebar = document.querySelector(".sidebar");
  const mobile = matchMedia("(max-width: 680px)");
  body.classList.add("jm-workspace");
  document.querySelector(".skip-link")?.addEventListener("click", (event) => {
    event.preventDefault();
    document.querySelector("#content").focus();
  });
  menu.innerHTML = icon("menu");
  const density = document.querySelector(".community-density");
  function applyDensity(compact) {
    body.classList.toggle("community-dense", compact);
    density.setAttribute("aria-pressed", String(compact));
    density.textContent = compact ? "舒适显示" : "紧凑显示";
    density.title = compact ? "切换为舒适间距" : "切换为紧凑间距";
  }
  let compact = false;
  try {
    compact = savedDensity(localStorage);
  } catch {}
  applyDensity(compact);
  function setMenu(open, restoreFocus = false) {
    body.classList.toggle("community-menu-open", open);
    menu.setAttribute("aria-expanded", String(open));
    menu.setAttribute("aria-label", open ? "关闭导航" : "打开导航");
    sidebar.inert = mobile.matches && !open;
    if (open) sidebar.querySelector('a[aria-current="page"]')?.focus();
    else if (restoreFocus) menu.focus();
  }
  setMenu(false);
  mobile.addEventListener("change", () => setMenu(false));
  return {
    closeMenu: () => setMenu(false),
    handle(action) {
      if (action === "com-v2-menu") {
        setMenu(
          !body.classList.contains("community-menu-open"),
          body.classList.contains("community-menu-open"),
        );
        return true;
      }
      if (action === "com-v2-density") {
        const compact = !body.classList.contains("community-dense");
        applyDensity(compact);
        try {
          localStorage.setItem(
            "jm-workspace-density",
            compact ? "compact" : "comfortable",
          );
        } catch {}
        return true;
      }
      return false;
    },
    escape() {
      if (body.classList.contains("community-menu-open")) setMenu(false, true);
    },
  };
}
