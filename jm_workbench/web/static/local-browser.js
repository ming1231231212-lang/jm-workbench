// Keep all user-facing website links in normal local Chrome, including when JM
// itself is opened inside an embedded preview. Never fall back to another browser.
export function installLocalBrowserLinks(root, request, toast) {
  let opening = false;
  async function open(event) {
    if (event.type === "auxclick" && event.button !== 1) return;
    const link = event.target.closest?.("a[href]");
    if (!link || link.hasAttribute("download")) return;
    const raw = link.getAttribute("href");
    if (!raw || raw.startsWith("#")) return;
    let url;
    try { url = new URL(raw, root.baseURI); } catch { return; }
    if (!["http:", "https:"].includes(url.protocol)) return;
    if (link.target !== "_blank" && url.origin === new URL(root.baseURI).origin) return;
    event.preventDefault();
    if (opening) return;
    opening = true;
    try {
      const result = await request("/api/browser/open", { url: url.href });
      toast(result.message);
    } catch (ex) { toast(ex.message, true); }
    finally { opening = false; }
  }
  root.addEventListener("click", open);
  root.addEventListener("auxclick", open);
}
