/* MYOP — logique du dashboard (vanilla JS, une section par page) */

const $ = (sel) => document.querySelector(sel);
const API = "/api";
const SHOW = window.MYOP_SHOW || "matin";

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

const showQuery = () => `show=${encodeURIComponent(SHOW)}`;

/* Nav active */
document.querySelectorAll("nav a").forEach((a) => {
  if (a.dataset.nav === location.pathname) a.classList.add("active");
});

function fmtDuration(seconds) {
  const m = Math.floor(seconds / 60);
  return `${m} min ${String(seconds % 60).padStart(2, "0")}`;
}

/* ---------------------------------------------------- barre des émissions */

async function loadShowTabs() {
  const state = await api("/state");
  const box = $("#show-tabs");
  if (!box) return;
  box.innerHTML = "";
  for (const show of state.shows) {
    const tab = document.createElement("a");
    tab.href = `${location.pathname}?show=${encodeURIComponent(show.id)}`;
    tab.textContent = show.title + (show.enabled ? "" : " ⏸");
    tab.className = "show-tab" + (show.id === state.current_show ? " active" : "");
    box.append(tab);
  }
  $("#show-add")?.addEventListener("click", async () => {
    const title = prompt("Nom de la nouvelle émission (ex : Briefing Tech du soir) :");
    if (!title) return;
    const hour = prompt("Heure de livraison (HH:MM, Paris) :", "18:00") || "18:00";
    try {
      const data = await api("/shows", { method: "POST", body: JSON.stringify({ title, delivery_hour: hour }) });
      location.href = `${location.pathname}?show=${data.id}`;
    } catch (err) {
      toast(err.message, "err");
    }
  });
}
loadShowTabs().catch(() => {});

/* ------------------------------------------------------------ page : réglages */

if (document.body.dataset.page === "settings") {
  const form = $("#settings-form");

  async function fillVoices(select, current) {
    if (!select) return;
    try {
      const voices = await api("/voices");
      select.innerHTML = "";
      if (!current) {
        select.append(new Option("— aucune —", ""));
      }
      for (const v of voices) {
        const opt = new Option(v.label, v.ShortName);
        if (v.ShortName === current) opt.selected = true;
        select.append(opt);
      }
      if (current && !voices.some((v) => v.ShortName === current)) {
        select.prepend(new Option(current, current, true, true));
      }
    } catch (_) {
      /* liste indisponible : option courante conservée */
    }
  }
  fillVoices($("#voice-select"), form.voice?.value);
  fillVoices($("#voice-co-select"), "");

  const preview = (sel) => () => {
    const voice = sel?.value;
    if (!voice) return;
    new Audio(`${API}/voice-preview/${encodeURIComponent(voice)}`)
      .play()
      .catch(() => toast("Extrait indisponible (service TTS injoignable)", "err"));
  };
  $("#voice-preview")?.addEventListener("click", preview($("#voice-select")));
  $("#voice-co-preview")?.addEventListener("click", preview($("#voice-co-select")));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const fd = new FormData(form);
    const payload = { show_id: SHOW };
    for (const [key, value] of fd.entries()) payload[key] = value;
    for (const box of ["enabled", "ephemeris", "ai_enabled", "jingle", "chapters", "skip_if_empty"]) {
      payload[box] = fd.get(box) === "on";
    }
    for (const key of ["num_headlines", "num_briefs", "max_brief_chars", "max_per_source"]) {
      if (payload[key] !== undefined) payload[key] = parseInt(payload[key], 10);
    }
    if (!payload.voice_co) payload.voice_co = "";
    try {
      await api("/settings", { method: "PUT", body: JSON.stringify(payload) });
      toast("Réglages enregistrés ✓");
    } catch (err) {
      toast(err.message, "err");
    }
  });

  $("#btn-delete-show")?.addEventListener("click", async () => {
    if (!confirm("Supprimer cette émission (et ses épisodes générés) ?")) return;
    try {
      await api(`/shows/${SHOW}`, { method: "DELETE" });
      location.href = "/";
    } catch (err) {
      toast(err.message, "err");
    }
  });
}

/* ------------------------------------------------------------ page : sources */

if (document.body.dataset.page === "sources") {
  const libraryList = $("#library-list");
  const customList = $("#custom-list");
  const searchBox = $("#library-search");
  let libraryData = null;

  async function refresh() {
    libraryData = await api(`/library?${showQuery()}`);
    renderLibrary();
    renderCustom(libraryData.custom);
    const exportLink = $("#btn-opml-export");
    if (exportLink) exportLink.href = `${API}/opml?${showQuery()}`;
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

  libraryList.addEventListener("change", async (event) => {
    const url = event.target.dataset?.url;
    if (!url) return;
    try {
      const data = await api("/library/toggle", {
        method: "POST",
        body: JSON.stringify({ url, enabled: event.target.checked, show_id: SHOW }),
      });
      libraryData.active_count = data.active_count;
      const feed = libraryData.categories.flatMap((c) => c.feeds).find((f) => f.url === url);
      if (feed) feed.active = event.target.checked;
      renderLibrary();
      toast(event.target.checked ? "Source activée ✓" : "Source retirée");
    } catch (err) {
      toast(err.message, "err");
      renderLibrary();
    }
  });

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
          show_id: SHOW,
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

  // Test d'un flux : aperçu des derniers items
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

  customList.addEventListener("click", async (event) => {
    const btn = event.target.closest("[data-delete]");
    if (!btn) return;
    try {
      await api(`/sources/${btn.dataset.delete}?${showQuery()}`, { method: "DELETE" });
      refresh();
      toast("Source supprimée ✓");
    } catch (err) {
      toast(err.message, "err");
    }
  });

  $("#add-source").addEventListener("submit", async (event) => {
    event.preventDefault();
    const fd = new FormData(event.target);
    try {
      await api("/sources", {
        method: "POST",
        body: JSON.stringify({ name: fd.get("name"), url: fd.get("url"), show_id: SHOW }),
      });
      event.target.reset();
      refresh();
      toast("Source ajoutée ✓");
    } catch (err) {
      toast(err.message, "err");
    }
  });

  // Santé des sources
  $("#btn-health")?.addEventListener("click", async (event) => {
    const btn = event.currentTarget;
    const box = $("#health-box");
    btn.disabled = true;
    box.hidden = false;
    box.innerHTML = '<span class="loading">🩺 Vérification en direct…</span>';
    try {
      const results = await api(`/sources/health?${showQuery()}`);
      box.innerHTML = results
        .map((r) =>
          r.ok
            ? `<div>✅ ${r.name} — ${r.items} items, dernier : ${r.latest} (${r.ms} ms)</div>`
            : `<div>❌ ${r.name} — ${r.error}</div>`
        )
        .join("");
    } catch (err) {
      box.innerHTML = `<div>⚠️ ${err.message}</div>`;
    } finally {
      btn.disabled = false;
    }
  });

  // OPML import/export
  $("#btn-opml-import")?.addEventListener("click", () => $("#opml-file")?.click());
  $("#opml-file")?.addEventListener("change", async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      const content = await file.text();
      const data = await api("/opml", {
        method: "POST",
        body: JSON.stringify({ content, show_id: SHOW }),
      });
      toast(`${data.added} flux importé(s) ✓ (total : ${data.total})`);
      refresh();
    } catch (err) {
      toast(err.message, "err");
    }
  });

  refresh().catch((err) => toast(err.message, "err"));
}

/* ----------------------------------------------------------- page : épisodes */

if (document.body.dataset.page === "episodes") {
  const genBtn = $("#btn-generate");
  const genStatus = $("#gen-status");
  let lastTitles = [];

  const qr = $("#qr");
  if (qr) {
    qr.onload = () => (qr.hidden = false);
    qr.src = `${API}/qr.png?${showQuery()}`;
  }

  async function loadEpisodes(data) {
    const box = $("#episodes-list");
    const episodes = data || (await api(`/episodes?${showQuery()}`));
    if (!episodes.length) {
      box.innerHTML =
        '<p class="loading">Aucun épisode pour l\'instant — clique sur « Générer maintenant ».</p>';
      return;
    }
    box.innerHTML = "";
    for (const ep of episodes) {
      const row = document.createElement("div");
      row.className = "episode";
      const date = new Date(ep.pubDate);
      row.innerHTML = `
        ${ep.local
          ? `<audio controls preload="none" src="${ep.audio}"></audio>`
          : '<span class="missing">MP3 absent localement</span>'}
        <div class="meta">
          <strong>${ep.title}</strong>
          <div class="desc">${ep.description || ""}</div>
          <div class="vote"></div>
        </div>
        <span class="badge">${date.toLocaleDateString("fr-FR")} · ${fmtDuration(ep.duration)} · ${Math.round(ep.size / 1024)} Ko</span>`;
      // Boucle de goût : un vote par titre du dernier épisode
      if (episodes.indexOf(ep) === 0 && ep.description) {
        const voteBox = row.querySelector(".vote");
        for (const title of ep.description.split(" • ").slice(0, 6)) {
          const chip = document.createElement("span");
          chip.className = "vote-chip";
          chip.innerHTML = `<span class="vt">${title.slice(0, 70)}</span>
            <button class="btn tiny" data-vote="1">👍</button>
            <button class="btn tiny danger" data-vote="0">👎</button>`;
          chip.querySelectorAll("[data-vote]").forEach((btn) =>
            btn.addEventListener("click", async () => {
              try {
                const result = await api("/feedback", {
                  method: "POST",
                  body: JSON.stringify({
                    title,
                    source: title.split(" — ")[0],
                    good: btn.dataset.vote === "1",
                  }),
                });
                chip.remove();
                toast(
                  result.ok && result.source_score !== undefined
                    ? `Merci ! Score de la source : ${result.source_score > 0 ? "+" : ""}${result.source_score}`
                    : "Merci !"
                );
              } catch (err) {
                toast(err.message, "err");
              }
            })
          );
          voteBox.append(chip);
        }
      }
      box.append(row);
    }
  }

  function renderStatus(status) {
    genStatus.hidden = false;
    let html = status.log.map((line) => `<div>${line}</div>`).join("");
    if (status.running) html += '<div class="loading">⏳ Génération en cours… (collecte, IA, synthèse vocale)</div>';
    const result = status.result;
    if (result) {
      if (result.ok) {
        html += `<div>✅ Épisode <strong>${result.episode_id}</strong> — ${fmtDuration(result.duration)}, ${Math.round(result.size / 1024)} Ko${result.ai_used ? " · ✍️ script IA" : ""}${result.reading_count ? ` · 📖 ${result.reading_count} article(s) lu(s)` : ""}</div>`;
        if (result.chapters?.length) {
          html += `<div class="hint">🔖 ${result.chapters.join(" · ")}</div>`;
        }
        html += "<ul>";
        for (const t of result.titles || []) html += `<li>${t}</li>`;
        html += "</ul>";
      } else {
        html += `<div>⚠️ ${result.reason}</div>`;
      }
      for (const w of result.warnings || []) html += `<div class="hint">⚠️ ${w}</div>`;
    }
    genStatus.innerHTML = html;
  }

  let pollTimer = null;
  function pollStatus() {
    clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      try {
        const status = await api(`/generate/status?${showQuery()}`);
        renderStatus(status);
        if (!status.running) {
          clearInterval(pollTimer);
          genBtn.disabled = false;
          loadEpisodes();
        }
      } catch (_) {}
    }, 2000);
  }

  genBtn.addEventListener("click", async () => {
    try {
      await api("/generate", {
        method: "POST",
        body: JSON.stringify({ show_id: SHOW }),
      });
      genBtn.disabled = true;
      toast("Génération lancée ⚡");
      pollStatus();
    } catch (err) {
      toast(err.message, "err");
    }
  });

  $("#btn-generate-date")?.addEventListener("click", async () => {
    const date = $("#gen-date").value;
    if (!date) return toast("Choisis une date d'abord", "err");
    try {
      await api("/generate", { method: "POST", body: JSON.stringify({ show_id: SHOW, date }) });
      genBtn.disabled = true;
      toast(`Régénération du ${date} lancée ⏪`);
      pollStatus();
    } catch (err) {
      toast(err.message, "err");
    }
  });

  // Éditeur de script : préparer → retoucher → synthétiser
  let draftData = null;
  $("#btn-draft")?.addEventListener("click", async (event) => {
    const btn = event.currentTarget;
    btn.disabled = true;
    toast("Préparation du script (collecte + rédaction)…");
    try {
      draftData = await api(`/script/draft?${showQuery()}`, { method: "POST" });
      renderDraft();
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false;
    }
  });

  function renderDraft() {
    const card = $("#draft-card");
    card.hidden = false;
    card.scrollIntoView({ behavior: "smooth" });
    $("#draft-meta").textContent =
      `${draftData.title}${draftData.ai_used ? " · ✍️ IA" : " · déterministe"}`;
    const box = $("#draft-segments");
    box.innerHTML = "";
    draftData.segments.forEach((segment, i) => {
      const field = document.createElement("label");
      field.className = "draft-segment";
      field.innerHTML = `
        <span class="kind kind-${segment.kind}">${segment.kind}${segment.speaker ? " · " + segment.speaker : ""}</span>
        <textarea rows="${Math.max(2, Math.ceil(segment.text.length / 90))}" data-seg="${i}">${segment.text}</textarea>`;
      box.append(field);
    });
  }

  $("#btn-render")?.addEventListener("click", async () => {
    if (!draftData) return;
    draftData.segments = draftData.segments.map((segment, i) => ({
      ...segment,
      text: document.querySelector(`[data-seg="${i}"]`)?.value ?? segment.text,
    }));
    try {
      await api("/script/render", {
        method: "POST",
        body: JSON.stringify({
          show_id: SHOW,
          segments: draftData.segments,
          items_keys: draftData.items_keys || [],
          titles: draftData.titles || [],
          description: draftData.description || "",
          ai_used: draftData.ai_used || false,
          reading_items: [],
        }),
      });
      $("#draft-card").hidden = true;
      toast("Synthèse lancée 🎧");
      pollStatus();
    } catch (err) {
      toast(err.message, "err");
    }
  });

  $("#btn-draft-close")?.addEventListener("click", () => ($("#draft-card").hidden = true));

  // Liste de lecture
  async function loadReading() {
    const box = $("#reading-list");
    if (!box) return;
    const items = await api("/reading");
    if (!items.length) {
      box.innerHTML = '<p class="hint">Vide — colle une URL d\'article à écouter demain matin.</p>';
      return;
    }
    box.innerHTML = "";
    items.forEach((item, i) => {
      const row = document.createElement("div");
      row.className = "source-row";
      row.innerHTML = `
        <span class="source-name grow" style="min-width:200px">${item.title || item.url}</span>
        <span class="badge">${Math.round(item.chars / 1000)}k caractères</span>
        <a class="btn small ghost" href="${item.url}" target="_blank">ouvrir</a>
        <button class="btn small danger" data-unread="${i}">✕</button>`;
      box.append(row);
    });
    box.querySelectorAll("[data-unread]").forEach((btn) =>
      btn.addEventListener("click", async () => {
        await api(`/reading/${btn.dataset.unread}`, { method: "DELETE" });
        loadReading();
      })
    );
  }

  $("#add-reading")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const fd = new FormData(event.target);
    try {
      const data = await api("/reading", {
        method: "POST",
        body: JSON.stringify({ url: fd.get("url") }),
      });
      event.target.reset();
      loadReading();
      toast(`Ajouté à la liste : ${data.title?.slice(0, 60) || "ok"} ✓`);
    } catch (err) {
      toast(err.message, "err");
    }
  });

  // Actions GitHub
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
      await api("/sync-remote", { method: "POST" });
      loadEpisodes();
      toast("Historique synchronisé ✓");
    } catch (err) {
      toast(err.message, "err");
    }
  });

  loadEpisodes().catch(() => {});
  loadReading().catch(() => {});
  api(`/generate/status?${showQuery()}`).then(renderStatus).catch(() => {});
}
