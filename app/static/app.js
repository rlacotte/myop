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
    tab.className = "show-tab" + (show.id === state.current_show ? " active" : "");
    tab.title = show.enabled ? `${show.title} — ${show.delivery_hour}` : `${show.title} — en pause`;
    tab.innerHTML = `<span class="dot${show.enabled ? "" : " off"}"></span>
      <span class="tab-name"></span>`;
    tab.querySelector(".tab-name").textContent = show.title;
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
    for (const key of ["num_headlines", "num_briefs", "max_brief_chars", "max_per_source", "keep_episodes"]) {
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
      const active = feeds.filter((f) => f.active).length;
      const section = document.createElement("div");
      section.className = "cat";
      section.innerHTML = `
        <div class="cat-head">
          <h3></h3>
          <span class="pill${active ? " ok" : ""}">${active}/${feeds.length}</span>
          <span class="grow"></span>
          <button class="btn tiny ghost" data-category="${category}" data-enable="${allOn ? "false" : "true"}">
            ${allOn ? "Tout retirer" : "Tout activer"}
          </button>
        </div>
        <div class="feeds"></div>`;
      section.querySelector("h3").textContent = category;
      const grid = section.querySelector(".feeds");
      for (const feed of shown) {
        const row = document.createElement("label");
        row.className = `feed${feed.active ? " on" : ""}`;
        row.title = feed.active ? "Désactiver" : "Activer";
        row.innerHTML = `
          <input type="checkbox" data-url="${feed.url}" ${feed.active ? "checked" : ""}>
          <span class="n"></span>
          <button type="button" class="btn tiny ghost" data-test="${feed.url}" data-name="${feed.name}">test</button>`;
        row.querySelector(".n").textContent = feed.name;
        grid.append(row);
      }
      libraryList.append(section);
    }

    if (!libraryList.children.length) {
      libraryList.innerHTML = '<div class="empty">Aucune source ne correspond à ta recherche.</div>';
    }
  }

  function renderCustom(custom) {
    customList.innerHTML = "";
    if (!custom.length) {
      customList.innerHTML =
        '<div class="empty" style="margin-top:16px">Aucun flux perso pour l\'instant.</div>';
      return;
    }
    const list = document.createElement("div");
    list.className = "rows";
    list.style.marginTop = "10px";
    custom.forEach((source) => {
      const row = document.createElement("div");
      row.className = "r";
      row.innerHTML = `
        <div class="main"><div class="t"></div><div class="m"></div></div>
        <button class="btn tiny ghost" data-test="${source.url}" data-name="${source.name}">test</button>
        <button class="btn tiny danger" data-delete="${source.index}">✕</button>`;
      row.querySelector(".t").textContent = source.name;
      row.querySelector(".m").textContent = source.url;
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
    $("#preview-items").className = "rows";
    $("#preview-items").innerHTML = '<p class="loading">Chargement…</p>';
    try {
      const data = await api(`/sources/preview?url=${encodeURIComponent(btn.dataset.test)}`);
      $("#preview-title").textContent = `Test — ${data.feed_title || btn.dataset.name}`;
      const box = $("#preview-items");
      box.innerHTML = "";
      if (!data.items.length) box.innerHTML = '<div class="empty">Aucun item dans ce flux.</div>';
      for (const item of data.items) {
        const row = document.createElement("div");
        row.className = "r";
        row.innerHTML = `<div class="main"><div class="t"></div></div><span class="m">${item.date}</span>`;
        row.querySelector(".t").textContent = item.title;
        box.append(row);
      }
    } catch (err) {
      $("#preview-items").innerHTML = `<div class="status ko">${err.message}</div>`;
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
    box.className = "status";
    box.innerHTML = '<span class="loading">Vérification en direct…</span>';
    try {
      const results = await api(`/sources/health?${showQuery()}`);
      const down = results.filter((r) => !r.ok).length;
      box.className = "status" + (down ? " ko" : " ok");
      box.innerHTML =
        `<strong>${results.length - down}/${results.length} sources répondent.</strong>` +
        results
          .map((r) =>
            r.ok
              ? `<div class="badge-ok">✓ ${r.name} — ${r.items} items, dernier : ${r.latest} (${r.ms} ms)</div>`
              : `<div class="badge-ko">✕ ${r.name} — ${r.error}</div>`
          )
          .join("");
    } catch (err) {
      box.className = "status ko";
      box.innerHTML = err.message;
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

/* Accueil et épisodes partagent la production (générer, suivre, publier) : le
   tableau de bord n'est pas une page de plus, c'est la même machine vue de haut. */
if (["home", "episodes"].includes(document.body.dataset.page)) {
  const genBtn = $("#btn-generate");
  const genStatus = $("#gen-status");
  const hasEditor = !!$("#draft-card");

  const qr = $("#qr");
  if (qr) {
    qr.onload = () => (qr.hidden = false);
    qr.src = `${API}/qr.png?${showQuery()}`;
  }

  async function loadEpisodes(data) {
    const box = $("#episodes-list");
    if (!box) return;
    const limit = Number(box.dataset.limit || 0);
    let episodes = data || (await api(`/episodes?${showQuery()}`));
    if (!episodes.length) {
      box.innerHTML =
        '<div class="empty">Aucun épisode pour l\'instant — lance « Générer maintenant ».</div>';
      return;
    }
    if (limit) episodes = episodes.slice(0, limit);
    box.innerHTML = "";
    box.className = "rows";
    for (const ep of episodes) {
      const row = document.createElement("div");
      row.className = "r";
      const date = new Date(ep.pubDate);
      row.innerHTML = `
        <div class="main">
          <div class="t"></div>
          <div class="m">${date.toLocaleDateString("fr-FR")} · ${fmtDuration(ep.duration)} · ${Math.round(ep.size / 1024)} Ko</div>
        </div>
        ${ep.local
          ? `<audio controls preload="none" src="${ep.audio}"></audio>`
          : '<span class="pill warn">MP3 absent en local</span>'}`;
      row.querySelector(".t").textContent = ep.title;
      // Boucle de goût : un vote par titre du dernier épisode, sous la ligne
      const voteBlock = document.createElement("div");
      voteBlock.className = "vote";
      voteBlock.innerHTML = '<div class="vote-title">Ces sujets t\'ont plu ?</div>';
      if (episodes.indexOf(ep) === 0 && ep.description && hasEditor) {
        const voteBox = voteBlock;
        for (const title of ep.description.split(" • ").slice(0, 6)) {
          const chip = document.createElement("div");
          chip.className = "vote-chip";
          chip.innerHTML = `<span class="vt"></span>
            <button class="btn tiny ghost" data-vote="1" title="Plus de sujets comme celui-ci">▲</button>
            <button class="btn tiny ghost" data-vote="0" title="Moins de sujets comme celui-ci">▼</button>`;
          chip.querySelector(".vt").textContent = title.slice(0, 90);
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
      if (voteBlock.querySelector(".vote-chip")) box.append(voteBlock);
    }
  }

  function renderStatus(status) {
    if (!genStatus) return;
    if (!status.log?.length && !status.result) return;
    genStatus.hidden = false;
    genStatus.className = "status" + (status.running ? " running" : status.result?.ok ? " ok" : status.result ? " ko" : "");
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
          if (genBtn) genBtn.disabled = false;
          loadEpisodes();
          loadOverview();
        }
      } catch (_) {}
    }, 2000);
  }

  genBtn?.addEventListener("click", async () => {
    try {
      await api("/generate", {
        method: "POST",
        body: JSON.stringify({ show_id: SHOW }),
      });
      if (genBtn) genBtn.disabled = true;
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
      if (genBtn) genBtn.disabled = true;
      toast(`Régénération du ${date} lancée ⏪`);
      pollStatus();
    } catch (err) {
      toast(err.message, "err");
    }
  });

  /* Chiffres clés du tableau de bord */
  async function loadOverview() {
    if (!$("#stat-sources")) return;
    try {
      const data = await api(`/overview?${showQuery()}`);
      $("#stat-sources").textContent = data.sources;
      $("#stat-episodes").textContent = data.episodes;
      $("#stat-last").innerHTML = data.latest
        ? new Date(data.latest.pubDate).toLocaleDateString("fr-FR", { day: "numeric", month: "short" })
        : "—";
      const state = $("#hero-state");
      if (data.running) state.className = "pill warn", state.textContent = "en cours…";
      else if (data.has_draft) state.className = "pill cool", state.textContent = "brouillon en attente";
      else if (!data.show.enabled) state.className = "pill", state.textContent = "en pause";
      else state.className = "pill ok", state.textContent = "prête";
      if (data.has_draft) {
        $("#hero-sub").innerHTML =
          'Un script préparé attend d\'être relu — <a href="/episodes">ouvrir l\'éditeur</a>.';
      }
    } catch (_) {}
  }
  loadOverview();

  $("#btn-copy-feed")?.addEventListener("click", (event) => {
    navigator.clipboard
      .writeText(event.currentTarget.dataset.url)
      .then(() => toast("URL du flux copiée ✓"))
      .catch(() => toast("Copie impossible", "err"));
  });

  // Éditeur de script : préparer → retoucher → synthétiser
  let draftData = null;
  $("#btn-draft")?.addEventListener("click", async (event) => {
    const btn = event.currentTarget;
    btn.disabled = true;
    toast("Préparation du script (collecte + rédaction)…");
    try {
      // Depuis l'accueil, l'édition se fait sur la page dédiée : le brouillon
      // étant enregistré côté serveur, il suffit d'y renvoyer.
      if (!hasEditor) {
        await api(`/script/draft?${showQuery()}`, { method: "POST" });
        location.href = `/episodes?${showQuery()}`;
        return;
      }
      draftData = await api(`/script/draft?${showQuery()}`, { method: "POST" });
      renderDraft();
      $("#draft-card").scrollIntoView({ behavior: "smooth" });
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false;
    }
  });

  const SEGMENT_KINDS = ["intro", "headlines", "meteo", "brief", "reading", "outro"];

  // Récupère les saisies en cours avant tout redessin ou envoi
  function collectDraft() {
    if (!draftData) return;
    draftData.segments = draftData.segments.map((segment, i) => ({
      ...segment,
      text: document.querySelector(`[data-seg="${i}"]`)?.value ?? segment.text,
    }));
    draftData.title = $("#draft-title")?.value ?? draftData.title;
  }

  function renderDraft() {
    const card = $("#draft-card");
    card.hidden = false;
    $("#draft-meta").textContent =
      `${draftData.segments.length} segments${draftData.ai_used ? " · ✍️ IA" : " · déterministe"}`;
    $("#draft-title").value = draftData.title || "";
    const box = $("#draft-segments");
    box.innerHTML = "";
    draftData.segments.forEach((segment, i) => {
      const field = document.createElement("div");
      field.className = "draft-segment";
      const kinds = SEGMENT_KINDS.map(
        (kind) => `<option value="${kind}"${kind === segment.kind ? " selected" : ""}>${kind}</option>`
      ).join("");
      field.innerHTML = `
        <div class="row wrap seg-head">
          <select data-kind="${i}" class="kind kind-${segment.kind}">${kinds}</select>
          <select data-speaker="${i}">
            <option value=""${!segment.speaker ? " selected" : ""}>voix principale</option>
            <option value="host"${segment.speaker === "host" ? " selected" : ""}>voix 1</option>
            <option value="co"${segment.speaker === "co" ? " selected" : ""}>voix 2</option>
          </select>
          <span class="grow"></span>
          <button class="btn small ghost" data-move="${i}" data-dir="-1" ${i === 0 ? "disabled" : ""}>↑</button>
          <button class="btn small ghost" data-move="${i}" data-dir="1" ${i === draftData.segments.length - 1 ? "disabled" : ""}>↓</button>
          <button class="btn small ghost" data-remove="${i}">✕</button>
        </div>
        <textarea rows="${Math.max(2, Math.ceil(segment.text.length / 90))}" data-seg="${i}"></textarea>`;
      // .value plutôt que le HTML : un script contenant « </textarea> » casserait le champ
      field.querySelector("textarea").value = segment.text;
      box.append(field);
    });
  }

  async function saveDraft(quiet) {
    collectDraft();
    if (!draftData) return;
    try {
      await api("/script/draft", {
        method: "PUT",
        body: JSON.stringify({
          show_id: SHOW,
          segments: draftData.segments,
          title: draftData.title,
        }),
      });
      if (!quiet) toast("Brouillon enregistré ✓");
    } catch (err) {
      if (!quiet) toast(err.message, "err");
    }
  }

  $("#draft-segments")?.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-move], button[data-remove]");
    if (!button) return;
    event.preventDefault();
    collectDraft();
    if (button.dataset.remove !== undefined) {
      if (draftData.segments.length <= 1) return toast("Il faut au moins un segment", "err");
      draftData.segments.splice(Number(button.dataset.remove), 1);
    } else {
      const from = Number(button.dataset.move);
      const to = from + Number(button.dataset.dir);
      if (to < 0 || to >= draftData.segments.length) return;
      const [moved] = draftData.segments.splice(from, 1);
      draftData.segments.splice(to, 0, moved);
    }
    renderDraft();
    saveDraft(true);
  });

  $("#draft-segments")?.addEventListener("change", (event) => {
    const select = event.target.closest("select[data-kind], select[data-speaker]");
    if (!select) return;
    collectDraft();
    const index = Number(select.dataset.kind ?? select.dataset.speaker);
    if (select.dataset.kind !== undefined) draftData.segments[index].kind = select.value;
    else draftData.segments[index].speaker = select.value || null;
    renderDraft();
    saveDraft(true);
  });

  $("#btn-seg-add")?.addEventListener("click", () => {
    collectDraft();
    draftData.segments.push({ kind: "brief", text: "", rate: null, speaker: null });
    renderDraft();
    $("#draft-segments").lastElementChild.querySelector("textarea").focus();
  });

  $("#btn-draft-save")?.addEventListener("click", () => saveDraft(false));

  $("#btn-draft-discard")?.addEventListener("click", async () => {
    if (!confirm("Abandonner ce brouillon ?")) return;
    await api(`/script/draft?${showQuery()}`, { method: "DELETE" }).catch(() => {});
    draftData = null;
    $("#draft-card").hidden = true;
    toast("Brouillon abandonné");
  });

  $("#btn-render")?.addEventListener("click", async () => {
    if (!draftData) return;
    collectDraft();
    if (!draftData.segments.some((segment) => segment.text.trim())) {
      return toast("Le script est vide", "err");
    }
    try {
      await api("/script/render", {
        method: "POST",
        body: JSON.stringify({
          show_id: SHOW,
          segments: draftData.segments,
          items_keys: draftData.items_keys || [],
          titles: draftData.titles || [],
          title: draftData.title || "",
          description: draftData.description || "",
          ai_used: draftData.ai_used || false,
          reading_items: draftData.reading_items || [],
        }),
      });
      $("#draft-card").hidden = true;
      toast("Synthèse lancée 🎧");
      pollStatus();
    } catch (err) {
      toast(err.message, "err");
    }
  });

  $("#btn-draft-close")?.addEventListener("click", () => {
    saveDraft(true);
    $("#draft-card").hidden = true;
  });

  // Brouillon laissé en plan lors d'une visite précédente
  api(`/script/draft?${showQuery()}`)
    .then((data) => {
      if (!data.draft) return;
      draftData = data.draft;
      renderDraft();
      toast("Brouillon de script repris");
    })
    .catch(() => {});

  // Liste de lecture
  async function loadReading() {
    const box = $("#reading-list");
    if (!box) return;
    const items = await api("/reading");
    if (!items.length) {
      box.className = "";
      box.innerHTML =
        '<div class="empty" style="margin-top:16px">Vide — colle l\'URL d\'un article à écouter demain.</div>';
      return;
    }
    box.className = "rows";
    box.style.marginTop = "10px";
    box.innerHTML = "";
    items.forEach((item, i) => {
      const row = document.createElement("div");
      row.className = "r";
      row.innerHTML = `
        <div class="main"><div class="t"></div><div class="m">${Math.round(item.chars / 1000)}k signes</div></div>
        <a class="btn tiny ghost" href="${item.url}" target="_blank">ouvrir</a>
        <button class="btn tiny danger" data-unread="${i}">✕</button>`;
      row.querySelector(".t").textContent = item.title || item.url;
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
