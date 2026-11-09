import "./style.css";
import { loadManifest } from "./data";
import { renderGallery } from "./gallery";
import { renderUnit } from "./unit";
import { renderLab } from "./lab";

const app = document.getElementById("app")!;
let cleanup: (() => void) | null = null;

async function route() {
  cleanup?.();
  cleanup = null;
  app.replaceChildren();
  const hash = location.hash.replace(/^#\/?/, "");
  const [page, arg] = hash.split("/");
  document.querySelectorAll<HTMLAnchorElement>(".topbar nav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.route === (page === "lab" ? "lab" : "gallery"));
  });
  const m = await loadManifest();
  if (page === "lab") cleanup = await renderLab(app, m, arg === "classic");
  else if (page === "unit" && arg) cleanup = renderUnit(app, m, decodeURIComponent(arg));
  else cleanup = renderGallery(app, m);
  window.scrollTo(0, 0);
}

window.addEventListener("hashchange", route);
route();
