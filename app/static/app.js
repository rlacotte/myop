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
  const list = $("#sources-list");

  async function refresh() {
    const sources = await api("/sources");
    list.innerHTML = "";
    if (!sources.length) {
      list.innerHTML = '<p class="loading">Aucune source — ajoute un flux RSS ci-dessus.</p>';
      return;
    }
    sources.forEach((source, position) => {
      const row = document.createElement("div");
      row.className = "source-row";
      row.innerHTML = `
        <button class="btn small ghost" data-move="-1" title="Monter" ${position === 0 ? "disabled" : ""}>↑</button>
        <button class="btn small ghost" data-move="1" title="Descendre" ${position === sources.length - 1 ? "disabled" : ""}>↓</button>
        <span class="source-name">${source.name}</span>
        <span class="source-url">${source.url}</span>
        <button class="btn small" data-test>Tester</button>
        <button class="btn small danger" data-delete>✕</button>`;
      list.append(row);

      row.querySelector("[data-delete]").addEventListener("click", async () => {
        try {
          await api(`/sources/${source.index}`, { method: "DELETE" });
          refresh();
        } catch (err) {
          toast(err.message, "err");
        }
      });
      row.querySelectorAll("[data-move]").forEach((btn) =>
        btn.addEventListener("click", async () => {
          try {
            await api(`/sources/${source.index}/move`, {
              method: "POST",
              body: JSON.stringify({ direction: parseInt(btn.dataset.move, 10) }),
            });
            refresh();
          } catch (err) {
            toast(err.message, "err");
          }
        })
      );
      row.querySelector("[data-test]").addEventListener("click", async () => {
        const box = $("#preview-box");
        box.hidden = false;
        $("#preview-title").textContent = `Test — ${source.name}`;
        $("#preview-items").innerHTML = '<li class="loading">Chargement…</li>';
        try {
          const data = await api(`/sources/preview?url=${encodeURIComponent(source.url)}`);
          $("#preview-title").textContent = `Test — ${data.feed_title || source.name}`;
          $("#preview-items").innerHTML =
            data.items
              .map((item) => `<li>${item.title}<span class="date">${item.date}</span></li>`)
              .join("") || '<li class="loading">Aucun item dans ce flux.</li>';
        } catch (err) {
          $("#preview-items").innerHTML = `<li class="loading">⚠️ ${err.message}</li>`;
        }
      });
    });
  }

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
        html += `<div>✅ Épisode <strong>${result.episode_id}</strong> — ${fmtDuration(result.duration)}, ${Math.round(result.size / 1024)} Ko</div><ul>`;
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
