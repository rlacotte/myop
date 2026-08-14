/* MYOP — logique du dashboard (vanilla JS, une section par page) */

const $ = (sel) => document.querySelector(sel);
const API = "/api";

function toast(message, kind = "ok") {
  const el = $("#toast");
  el.textContent = message;
  el.className = kind;
  el.hidden = false;
  clearTimeout(el._timer);
  el._timer = setTimeout(() => (el.hidden = true), 4000);
}

async function api(path, options = {}) {
  const resp = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    let detail = `${resp.status}`;
    try {
      const body = await resp.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch (_) {}
    throw new Error(detail);
  }
  return resp.json().catch(() => ({}));
}

/* Nav active */
document.querySelectorAll("nav a").forEach((a) => {
  if (a.dataset.nav === location.pathname) a.classList.add("active");
});

function fmtDuration(seconds) {
  const m = Math.floor(seconds / 60);
  return `${m} min ${String(seconds % 60).padStart(2, "0")}`;
}

/* ------------------------------------------------------------------ page : réglages */

if (document.body.dataset.page === "settings") {
  const form = $("#settings-form");

  // Liste des voix françaises
  api("/voices")
    .then((voices) => {
      const select = $("#voice-select");
      const current = select.value;
      select.innerHTML = "";
      for (const v of voices) {
        const opt = document.createElement("option");
        opt.value = v.ShortName;
        opt.textContent = v.label;
        if (v.ShortName === current) opt.selected = true;
        select.append(opt);
      }
    })
    .catch(() => toast("Voix en ligne indisponibles (liste statique conservée)", "err"));

  $("#voice-preview").addEventListener("click", () => {
    const voice = $("#voice-select").value;
    const audio = new Audio(`${API}/voice-preview/${encodeURIComponent(voice)}`);
    audio.play().catch(() => toast("Extrait indisponible (service TTS injoignable)", "err"));
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const fd = new FormData(form);
    const payload = {};
    for (const [key, value] of fd.entries()) payload[key] = value;
    payload.skip_if_empty = fd.get("skip_if_empty") === "on";
    payload.ai_enabled = fd.get("ai_enabled") === "on";
    for (const key of ["num_headlines", "num_briefs", "max_brief_chars", "max_per_source"]) {
      payload[key] = parseInt(payload[key], 10);
    }
    try {
      await api("/settings", { method: "PUT", body: JSON.stringify(payload) });
      toast("Réglages enregistrés ✓");
    } catch (err) {
      toast(err.message, "err");
    }
  });
}

/* ------------------------------------------------------------------ page : sources */

if (document.body.dataset.page === "sources") {
  const libraryList = $("#library-list");
  const customList = $("#custom-list");
  const searchBox = $("#library-search");
  let libraryData = null;

  async function refresh() {
    libraryData = await api("/library");
    renderLibrary();
    renderCustom(libraryData.custom);
  }

  function renderLibrary() {
    const query = (searchBox?.value || "").trim().toLowerCase();
    $("#active-count").textContent = `${libraryData.active_count} source(s) active(s)`;
    libraryList.innerHTML = "";

    for (const { category, feeds } of libraryData.categories) {
      const shown = feeds.filter(
        (f) =>
          !query ||
          f.name.toLowerCase().includes(query) ||
          category.toLowerCase().includes(query)
      );
      if (!shown.length) continue;

      const allOn = feeds.every((f) => f.active);
      const section = document.createElement("div");
      section.className = "category";
      section.innerHTML = `
        <div class="category-head">
          <span class="category-name">${category}</span>
          <span class="badge">${feeds.filter((f) => f.active).length}/${feeds.length}</span>
          <button class="btn small ghost" data-category="${category}" data-enable="${allOn ? "false" : "true"}">
            ${allOn ? "Tout retirer" : "Tout activer"}
          </button>
        </div>`;
      for (const feed of shown) {
        const row = document.createElement("div");
        row.className = `feed-row${feed.active ? " on" : ""}`;
        row.innerHTML = `
          <label class="switch" title="${feed.active ? "Désactiver" : "Activer"}">
            <input type="checkbox" data-url="${feed.url}" ${feed.active ? "checked" : ""}>
            <span class="slider"></span>
          </label>
          <span class="source-name">${feed.name}</span>
          <button class="btn small ghost" data-test="${feed.url}" data-name="${feed.name}">Tester</button>`;
        section.append(row);
      }
      libraryList.append(section);
    }

    if (!libraryList.children.length) {
      libraryList.innerHTML = '<p class="loading">Aucune source ne correspond à ta recherche.</p>';
    }
  }

  function renderCustom(custom) {
    customList.innerHTML = "";
    if (!custom.length) {
      customList.innerHTML =
        '<p class="hint">Aucune source personnalisée — ajoute ci-dessous n\'importe quel flux RSS.</p>';
      return;
    }
    const list = document.createElement("div");
    list.className = "custom-list";
    custom.forEach((source) => {
      const row = document.createElement("div");
      row.className = "source-row";
      row.innerHTML = `
        <span class="source-name">${source.name}</span>
        <span class="source-url">${source.url}</span>
        <button class="btn small" data-test="${source.url}" data-name="${source.name}">Tester</button>
        <button class="btn small danger" data-delete="${source.index}">✕</button>`;
      list.append(row);
    });
    customList.append(list);
  }

  // Bascule d'une source de la bibliothèque
  libraryList.addEventListener("change", async (event) => {
    const url = event.target.dataset?.url;
    if (!url) return;
    try {
      const data = await api("/library/toggle", {
        method: "POST",
        body: JSON.stringify({ url, enabled: event.target.checked }),
      });
      libraryData.active_count = data.active_count;
      const feed = libraryData.categories
        .flatMap((c) => c.feeds)
        .find((f) => f.url === url);
      if (feed) feed.active = event.target.checked;
      renderLibrary();
      toast(event.target.checked ? "Source activée ✓" : "Source retirée");
    } catch (err) {
      toast(err.message, "err");
      renderLibrary();
    }
  });

  // Activer / retirer toute une catégorie
  libraryList.addEventListener("click", async (event) => {
    const btn = event.target.closest("[data-category]");
    if (!btn) return;
    btn.disabled = true;
    try {
      const data = await api("/library/category", {
        method: "POST",
        body: JSON.stringify({
          category: btn.dataset.category,
          enabled: btn.dataset.enable === "true",
        }),
      });
      await refresh();
      toast(data.active_count + " source(s) active(s) ✓");
    } catch (err) {
      toast(err.message, "err");
      btn.disabled = false;
    }
  });

  searchBox?.addEventListener("input", renderLibrary);

  // Test d'un flux (bibliothèque ou perso) : aperçu des derniers items
  document.addEventListener("click", async (event) => {
    const btn = event.target.closest("[data-test]");
    if (!btn) return;
    const box = $("#preview-box");
    box.hidden = false;
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
    $("#preview-title").textContent = `Test — ${btn.dataset.name}`;
    $("#preview-items").innerHTML = '<li class="loading">Chargement…</li>';
    try {
      const data = await api(`/sources/preview?url=${encodeURIComponent(btn.dataset.test)}`);
      $("#preview-title").textContent = `Test — ${data.feed_title || btn.dataset.name}`;
      $("#preview-items").innerHTML =
        data.items
          .map((item) => `<li>${item.title}<span class="date">${item.date}</span></li>`)
          .join("") || '<li class="loading">Aucun item dans ce flux.</li>';
    } catch (err) {
      $("#preview-items").innerHTML = `<li class="loading">⚠️ ${err.message}</li>`;
    }
  });

  // Suppression d'une source perso
  customList.addEventListener("click", async (event) => {
    const btn = event.target.closest("[data-delete]");
    if (!btn) return;
    try {
      await api(`/sources/${btn.dataset.delete}`, { method: "DELETE" });
      refresh();
      toast("Source supprimée ✓");
    } catch (err) {
      toast(err.message, "err");
    }
  });

  // Ajout d'une source perso
  $("#add-source").addEventListener("submit", async (event) => {
    event.preventDefault();
    const fd = new FormData(event.target);
    try {
      await api("/sources", {
        method: "POST",
        body: JSON.stringify({ name: fd.get("name"), url: fd.get("url") }),
      });
      event.target.reset();
      refresh();
      toast("Source ajoutée ✓");
    } catch (err) {
      toast(err.message, "err");
    }
  });

  refresh().catch((err) => toast(err.message, "err"));
}

/* ----------------------------------------------------------------- page : épisodes */

if (document.body.dataset.page === "episodes") {
  const genBtn = $("#btn-generate");
  const genStatus = $("#gen-status");

  // QR code du flux
  const qr = $("#qr");
  if (qr) {
    qr.onload = () => (qr.hidden = false);
    qr.src = `${API}/qr.png`;
  }

  $("#copy-url")?.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("#feed-url").value);
      toast("URL du flux copiée ✓");
    } catch (_) {
      toast("Copie impossible — sélectionne l'URL manuellement", "err");
    }
  });

  async function loadEpisodes(data) {
    const box = $("#episodes-list");
    const episodes = data || (await api("/episodes"));
    if (!episodes.length) {
      box.innerHTML = '<p class="loading">Aucun épisode pour l\'instant — clique sur « Générer maintenant ».</p>';
      return;
    }
    box.innerHTML = "";
    for (const ep of episodes) {
      const row = document.createElement("div");
      row.className = "episode";
      const date = new Date(ep.pubDate);
      row.innerHTML = `
        ${ep.local
          ? `<audio controls preload="none" src="/audio/${ep.id}.mp3"></audio>`
          : '<span class="missing">MP3 absent localement</span>'}
        <div class="meta">
          <strong>${ep.title}</strong>
          <div class="desc">${ep.description || ""}</div>
        </div>
        <span class="badge">${date.toLocaleDateString("fr-FR")} · ${fmtDuration(ep.duration)} · ${Math.round(ep.size / 1024)} Ko</span>`;
      box.append(row);
    }
  }

  let pollTimer = null;
  function pollStatus() {
    clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      try {
        const status = await api("/generate/status");
        renderStatus(status);
        if (!status.running) {
          clearInterval(pollTimer);
          genBtn.disabled = false;
          loadEpisodes();
        }
      } catch (_) {}
    }, 2000);
  }

  function renderStatus(status) {
    genStatus.hidden = false;
    let html = status.log.map((line) => `<div>${line}</div>`).join("");
    if (status.running) html += '<div class="loading">⏳ Génération en cours… (RSS + synthèse vocale)</div>';
    const result = status.result;
    if (result) {
      if (result.ok) {
        html += `<div>✅ Épisode <strong>${result.episode_id}</strong> — ${fmtDuration(result.duration)}, ${Math.round(result.size / 1024)} Ko${result.ai_used ? " · ✍️ script IA" : ""}</div><ul>`;
        for (const t of result.titles || []) html += `<li>${t}</li>`;
        html += "</ul>";
      } else {
        html += `<div>⚠️ ${result.reason}</div>`;
      }
      for (const w of result.warnings || []) html += `<div class="hint">⚠️ ${w}</div>`;
    }
    genStatus.innerHTML = html;
  }

  genBtn.addEventListener("click", async () => {
    try {
      await api("/generate", { method: "POST" });
      genBtn.disabled = true;
      toast("Génération lancée ⚡");
      pollStatus();
    } catch (err) {
      toast(err.message, "err");
    }
  });

  const actions = [
    ["#btn-publish-config", "/publish-config", "POST"],
    ["#btn-publish-dist", "/publish-dist", "POST"],
    ["#btn-trigger", "/trigger", "POST"],
  ];
  for (const [sel, path, method] of actions) {
    $(sel)?.addEventListener("click", async (event) => {
      const btn = event.currentTarget;
      btn.disabled = true;
      try {
        const data = await api(path, { method });
        toast(data.message || "OK ✓");
      } catch (err) {
        toast(err.message, "err");
      } finally {
        btn.disabled = false;
      }
    });
  }

  $("#btn-sync")?.addEventListener("click", async () => {
    try {
      const episodes = await api("/sync-remote", { method: "POST" });
      loadEpisodes(episodes);
      toast("Historique synchronisé ✓");
    } catch (err) {
      toast(err.message, "err");
    }
  });

  loadEpisodes().catch(() => {});
  api("/generate/status").then(renderStatus).catch(() => {});
}
