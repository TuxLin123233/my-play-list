(() => {
  "use strict";

  const DATA = window.PLAYLIST_DATA;
  if (!DATA) {
    console.error("PLAYLIST_DATA 未加载");
    return;
  }

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const ESC_MAP = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  };
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ESC_MAP[ch]);
  const normalize = (value) =>
    String(value ?? "")
      .normalize("NFKC")
      .toLowerCase()
      .replace(/\s+/g, " ")
      .trim();

  const state = {
    genre: "all",
    query: "",
    sort: "default",
    view: localStorage.getItem("playlist-view") === "list" ? "list" : "grid",
    theme: localStorage.getItem("playlist-theme") === "light" ? "light" : "dark",
    heroId: null,
  };

  const els = {
    genreChips: $("#genre-chips"),
    grid: $("#grid"),
    empty: $("#empty"),
    emptyReset: $("#empty-reset"),
    resultCount: $("#result-count"),
    search: $("#search"),
    searchClear: $("#search-clear"),
    sort: $("#sort"),
    viewButtons: $$("[data-view]"),
    themeToggle: $("#theme-toggle"),
    themeLabel: $(".theme-label"),
    metaTheme: $('meta[name="theme-color"]'),
    shuffle: $("#shuffle"),
    toTop: $("#to-top"),
    dialog: $("#song-dialog"),
    dialogClose: $("#dialog-close"),
    dialogCover: $("#dialog-cover"),
    dialogIndex: $("#dialog-index"),
    dialogTitle: $("#dialog-title"),
    dialogArtist: $("#dialog-artist"),
    dialogAlbum: $("#dialog-album"),
    dialogTags: $("#dialog-tags"),
    dialogQQ: $("#dialog-qq"),
    dialogNetease: $("#dialog-netease"),
    toast: $("#toast"),
    year: $("#year"),
    heroCount: $("#hero-count"),
    vinylCount: $("#vinyl-count"),
    heroCover: $("#hero-cover"),
    heroTitle: $("#hero-title"),
    heroArtist: $("#hero-artist"),
    heroGenre: $("#hero-genre"),
    heroCatalog: $("#hero-catalog"),
    heroCoverBtn: $("#hero-cover-btn"),
    spin: $("#spin"),
    elsewhereDialog: $("#elsewhere-dialog"),
    elsewhereOpen: $$("[data-elsewhere]"),
    elsewhereClose: $("#elsewhere-close"),
  };

  const collator = new Intl.Collator("zh-CN", { sensitivity: "base", numeric: true });
  let searchTimer = 0;
  let toastTimer = 0;

  /* ---------- theme ---------- */

  function applyTheme(theme, persist) {
    state.theme = theme;
    document.documentElement.dataset.theme = theme;
    const isDark = theme === "dark";
    if (els.themeLabel) els.themeLabel.textContent = isDark ? "浅色" : "深色";
    if (els.themeToggle) {
      const label = isDark ? "切换到浅色主题" : "切换到深色主题";
      els.themeToggle.setAttribute("aria-label", label);
      els.themeToggle.title = label;
    }
    if (els.metaTheme) els.metaTheme.setAttribute("content", isDark ? "#12110f" : "#f5f3ee");
    if (persist) localStorage.setItem("playlist-theme", theme);
  }

  /* ---------- view ---------- */

  function applyView(view, persist) {
    state.view = view === "list" ? "list" : "grid";
    els.grid.classList.toggle("is-list", state.view === "list");
    els.viewButtons.forEach((button) => {
      const active = button.dataset.view === state.view;
      button.setAttribute("aria-pressed", String(active));
    });
    if (persist) localStorage.setItem("playlist-view", state.view);
  }

  /* ---------- data / filtering ---------- */

  function getFiltered() {
    const query = normalize(state.query);
    const list = DATA.songs.filter((song) => {
      if (state.genre !== "all" && song.genre !== state.genre) return false;
      if (!query) return true;
      return (
        normalize(song.title).includes(query) ||
        normalize(song.artist).includes(query) ||
        normalize(song.album).includes(query)
      );
    });

    if (state.sort === "title") {
      list.sort((a, b) => collator.compare(a.title, b.title) || collator.compare(a.artist, b.artist));
    } else if (state.sort === "artist") {
      list.sort((a, b) => collator.compare(a.artist, b.artist) || collator.compare(a.title, b.title));
    } else if (state.sort === "album") {
      list.sort((a, b) => {
        if (!a.album && !b.album) return collator.compare(a.title, b.title);
        if (!a.album) return 1;
        if (!b.album) return -1;
        return collator.compare(a.album, b.album) || collator.compare(a.title, b.title);
      });
    } else if (state.sort === "duration") {
      list.sort((a, b) => toSeconds(a.duration) - toSeconds(b.duration) || collator.compare(a.title, b.title));
    }
    return list;
  }

  function toSeconds(duration) {
    if (!duration) return Number.POSITIVE_INFINITY;
    const parts = String(duration).split(":").map(Number);
    if (parts.some(Number.isNaN)) return Number.POSITIVE_INFINITY;
    return parts.reduce((total, part) => total * 60 + part, 0);
  }

  /* ---------- render ---------- */

  function cardHTML(song, index) {
    const language =
      song.language && song.language !== "其他"
        ? `<span class="lang">${esc(song.language)}</span>`
        : "";
    const duration = song.duration ? `<span class="duration">${esc(song.duration)}</span>` : "";
    const genreInline = `<span class="genre-inline">${esc(song.genre)}</span>`;
    const album = song.album ? `<p class="song-card__album">${esc(song.album)}</p>` : "";
    const cover = song.cover || song.coverRemote || "";
    const fallback = song.coverRemote && song.coverRemote !== cover ? song.coverRemote : "";

    return `
      <article class="song-card" data-id="${esc(song.id)}" tabindex="0" role="button"
        aria-label="查看 ${esc(song.title)} 详情" style="--i:${index % 14}">
        <div class="song-card__cover">
          ${cover ? `<img src="${esc(cover)}" alt="${esc(song.title)} - ${esc(song.artist)}"
            loading="lazy" decoding="async" data-fallback="${esc(fallback)}">` : ""}
          <span class="song-card__index">${String(index + 1).padStart(3, "0")}</span>
          <span class="song-card__play" aria-hidden="true">↗</span>
        </div>
        <div class="song-card__body">
          <h3 class="song-card__title">${esc(song.title)}</h3>
          <p class="song-card__artist">${esc(song.artist)}</p>
          ${album}
          <div class="song-card__meta">${genreInline}${language}${duration}</div>
        </div>
      </article>`;
  }

  function setHeroShowcase(song) {
    if (!song || !els.heroCover) return;
    state.heroId = song.id;
    const cover = song.cover || song.coverRemote || "";
    els.heroCover.src = cover;
    els.heroCover.alt = `${song.title} - ${song.artist}`;
    els.heroCover.dataset.fallback =
      song.coverRemote && song.coverRemote !== cover ? song.coverRemote : "";
    els.heroTitle.textContent = song.title;
    els.heroArtist.textContent = song.artist;
    els.heroGenre.textContent = song.genre;
    els.heroCatalog.textContent = "NO. " + String(song.id).padStart(3, "0");
    if (els.heroCoverBtn) {
      els.heroCoverBtn.setAttribute("aria-label", `查看 ${song.title} 详情`);
    }
  }

  function spinShowcase() {
    if (!DATA.songs.length) return;
    const song = DATA.songs[Math.floor(Math.random() * DATA.songs.length)];
    setHeroShowcase(song);
  }

  function render() {
    const list = getFiltered();
    els.grid.innerHTML = list.map(cardHTML).join("");
    els.empty.hidden = list.length > 0;
    updateResultCount(list.length);

    if (state.genre !== "all") {
      const active = $(`.chip[data-genre="${cssEscape(state.genre)}"]`, els.genreChips);
      if (active) active.scrollIntoView({ block: "nearest", inline: "center" });
    }
  }

  function updateResultCount(count) {
    const total = DATA.stats.songs;
    const parts = [];
    if (state.genre !== "all") parts.push(state.genre);
    const query = state.query.trim();
    if (query) parts.push(`“${query}”`);

    if (count === total && parts.length === 0) {
      els.resultCount.textContent = `共 ${total} 首 · 按风格收好的私人歌单`;
    } else {
      els.resultCount.textContent = `找到 ${count} 首${parts.length ? " · " + parts.join(" · ") : ""}`;
    }
  }

  function renderChips() {
    const chips = [{ value: "all", name: "全部", count: DATA.stats.songs }].concat(
      DATA.genres.map((genre) => ({ value: genre.name, name: genre.name, count: genre.count }))
    );
    els.genreChips.innerHTML = chips
      .map((chip) => {
        const active = chip.value === state.genre;
        return `<button class="chip${active ? " is-active" : ""}" type="button"
          data-genre="${esc(chip.value)}" aria-pressed="${active}">${esc(chip.name)}<span>${chip.count}</span></button>`;
      })
      .join("");
  }

  function cssEscape(value) {
    if (window.CSS && typeof window.CSS.escape === "function") return window.CSS.escape(value);
    return String(value).replace(/["\\]/g, "\\$&");
  }

  /* ---------- dialog ---------- */

  function openDialog(id) {
    const song = DATA.songs.find((item) => item.id === id);
    if (!song) return;

    els.dialogIndex.textContent = `TRACK ${song.id}`;
    els.dialogTitle.textContent = song.title;
    els.dialogArtist.textContent = song.artist;
    els.dialogAlbum.textContent = song.album || "未知专辑";
    els.dialogQQ.href = song.qqUrl;
    els.dialogNetease.href = song.neteaseUrl;

    const tags = [song.genre];
    if (song.language && song.language !== "其他") tags.push(song.language);
    if (song.duration) tags.push(song.duration);
    els.dialogTags.innerHTML = tags.map((tag) => `<span>${esc(tag)}</span>`).join("");

    els.dialogCover.style.visibility = "visible";
    els.dialogCover.dataset.triedFallback = "";
    els.dialogCover.dataset.fallback = song.coverRemote || "";
    els.dialogCover.src = song.cover || song.coverRemote || "";
    els.dialogCover.alt = `${song.title} - ${song.artist}`;

    if (!els.dialog.open) els.dialog.showModal();
    document.body.classList.add("dialog-open");
  }

  function closeDialog() {
    if (els.dialog.open) els.dialog.close();
  }

  /* ---------- toast ---------- */

  function toast(message) {
    els.toast.textContent = message;
    els.toast.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => els.toast.classList.remove("is-visible"), 2200);
  }

  /* ---------- stats ---------- */

  function animateCount(element, target) {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      element.textContent = target;
      return;
    }
    const start = performance.now();
    const duration = 900;
    function tick(now) {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      element.textContent = Math.round(target * eased);
      if (progress < 1) requestAnimationFrame(tick);
      else element.textContent = target;
    }
    requestAnimationFrame(tick);
  }

  function initStats() {
    const targets = {
      songs: DATA.stats.songs,
      artists: DATA.stats.artists,
      albums: DATA.stats.albums,
      genres: DATA.stats.genres,
    };
    $$("[data-count]").forEach((element) => {
      const target = targets[element.dataset.stat];
      if (typeof target === "number") {
        element.dataset.count = target;
        animateCount(element, target);
      }
    });
    if (els.heroCount) els.heroCount.textContent = DATA.stats.songs;
    if (els.vinylCount) els.vinylCount.textContent = DATA.stats.songs;
  }

  /* ---------- events ---------- */

  function bindEvents() {
    els.themeToggle.addEventListener("click", () => {
      applyTheme(state.theme === "dark" ? "light" : "dark", true);
    });

    els.viewButtons.forEach((button) => {
      button.addEventListener("click", () => applyView(button.dataset.view, true));
    });

    els.search.addEventListener("input", () => {
      state.query = els.search.value;
      els.searchClear.hidden = !els.search.value;
      clearTimeout(searchTimer);
      searchTimer = window.setTimeout(render, 120);
    });

    els.search.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        if (els.search.value) {
          els.search.value = "";
          state.query = "";
          els.searchClear.hidden = true;
          render();
        } else {
          els.search.blur();
        }
      }
    });

    els.searchClear.addEventListener("click", () => {
      els.search.value = "";
      state.query = "";
      els.searchClear.hidden = true;
      render();
      els.search.focus();
    });

    els.sort.addEventListener("change", () => {
      state.sort = els.sort.value;
      render();
    });

    els.genreChips.addEventListener("click", (event) => {
      const chip = event.target.closest(".chip");
      if (!chip) return;
      state.genre = chip.dataset.genre;
      $$(".chip", els.genreChips).forEach((item) => {
        const active = item.dataset.genre === state.genre;
        item.classList.toggle("is-active", active);
        item.setAttribute("aria-pressed", String(active));
      });
      render();
    });

    els.grid.addEventListener("click", (event) => {
      if (event.target.closest("a")) return;
      const card = event.target.closest(".song-card");
      if (card) openDialog(card.dataset.id);
    });

    els.grid.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      if (event.target.closest("a")) return;
      const card = event.target.closest(".song-card");
      if (card) {
        event.preventDefault();
        openDialog(card.dataset.id);
      }
    });

    els.grid.addEventListener(
      "error",
      (event) => {
        const image = event.target;
        if (!(image instanceof HTMLImageElement)) return;
        const fallback = image.dataset.fallback;
        if (fallback && image.dataset.triedFallback !== "1") {
          image.dataset.triedFallback = "1";
          image.src = fallback;
        } else {
          image.style.visibility = "hidden";
          image.closest(".song-card__cover")?.classList.add("is-empty");
        }
      },
      true
    );

    els.dialogCover.addEventListener("error", () => {
      const fallback = els.dialogCover.dataset.fallback;
      if (fallback && els.dialogCover.dataset.triedFallback !== "1") {
        els.dialogCover.dataset.triedFallback = "1";
        els.dialogCover.src = fallback;
      } else {
        els.dialogCover.style.visibility = "hidden";
      }
    });

    els.dialogClose.addEventListener("click", closeDialog);
    els.elsewhereOpen.forEach((button) => {
      button.addEventListener("click", () => {
        if (els.elsewhereDialog && !els.elsewhereDialog.open) els.elsewhereDialog.showModal();
      });
    });
    if (els.elsewhereClose) {
      els.elsewhereClose.addEventListener("click", () => {
        if (els.elsewhereDialog && els.elsewhereDialog.open) els.elsewhereDialog.close();
      });
    }
    if (els.elsewhereDialog) {
      els.elsewhereDialog.addEventListener("click", (event) => {
        if (event.target === els.elsewhereDialog) els.elsewhereDialog.close();
      });
    }
    els.dialog.addEventListener("click", (event) => {
      if (event.target === els.dialog) closeDialog();
    });
    els.dialog.addEventListener("close", () => {
      document.body.classList.remove("dialog-open");
    });

    els.shuffle.addEventListener("click", spinShowcase);
    if (els.spin) els.spin.addEventListener("click", spinShowcase);
    if (els.heroCoverBtn) {
      els.heroCoverBtn.addEventListener("click", () => {
        if (state.heroId) openDialog(state.heroId);
      });
    }
    if (els.heroCover) {
      els.heroCover.addEventListener("error", () => {
        const fallback = els.heroCover.dataset.fallback;
        if (fallback && els.heroCover.dataset.triedFallback !== "1") {
          els.heroCover.dataset.triedFallback = "1";
          els.heroCover.src = fallback;
        } else {
          els.heroCover.style.visibility = "hidden";
        }
      });
    }

    els.emptyReset.addEventListener("click", () => {
      state.genre = "all";
      state.query = "";
      state.sort = "default";
      els.search.value = "";
      els.searchClear.hidden = true;
      els.sort.value = "default";
      $$(".chip", els.genreChips).forEach((chip) => {
        const active = chip.dataset.genre === "all";
        chip.classList.toggle("is-active", active);
        chip.setAttribute("aria-pressed", String(active));
      });
      render();
      els.search.focus();
    });

    els.toTop.addEventListener("click", () => {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" });
    });

    window.addEventListener(
      "scroll",
      () => {
        els.toTop.classList.toggle("is-visible", window.scrollY > 700);
      },
      { passive: true }
    );

    document.addEventListener("keydown", (event) => {
      const target = event.target;
      const typing =
        target instanceof HTMLElement &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable);
      if (event.key === "/" && !typing && !event.metaKey && !event.ctrlKey && !event.altKey) {
        event.preventDefault();
        els.search.focus();
      }
    });
  }

  /* ---------- init ---------- */

  applyTheme(state.theme, false);
  applyView(state.view, false);
  renderChips();
  initStats();
  bindEvents();
  render();
  spinShowcase();

  if (els.year) els.year.textContent = new Date().getFullYear();
})();
