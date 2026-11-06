/* KnowledgeOS AI — front end. No build step, no external libraries. */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const store = {
    get(k, d) { try { const v = localStorage.getItem("kos_" + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("kos_" + k, JSON.stringify(v)); } catch { /* private mode */ } },
  };

  // ------------------------------------------------------------------ i18n
  const T = {
    en: {
      brandSub: "Learn from your documents.", navTalk: "Talk", navLibrary: "Library", navStudy: "Study", navSettings: "Settings",
      navGuide: "Guide", tagline: "Your AI study assistant",
      heroSub: "Ask about your PDFs and notes — every answer shows the page it came from.",
      placeholder: "Type your question...", tap: "Tap to talk", listening: "Listening… tap to stop", thinking: "Thinking…",
      speaking: "Speaking… tap to stop", libTitle: "Your library", libSub: "Upload PDF, Word, Markdown, text, CSV or Excel files. They stay in this Colab session.",
      dzTitle: "Drop files here or click to upload", progressHint: "Large PDFs can take a few minutes on a free Colab CPU.",
      studyTitle: "Study mode", studySub: "Pick a document and turn it into something you can learn from.", setTitle: "Settings",
      setAI: "AI answers", setAIsub: "Without an AI provider the app shows the most relevant passages. With one, it writes cited answers.",
      setVoice: "Voice", optCont: "Hands-free voice chat: keep listening after each answer", optSpeak: "Read answers aloud",
      optRate: "Speaking speed", voiceNote: "Voice works best in Google Chrome or Edge. Allow microphone access when the browser asks.",
      restartGuide: "Restart the guided tour", advNote: "Evaluation lab, diagnostics and advanced retrieval settings are in the classic app (CELL 64).",
      skip: "Skip tour", back: "Back", next: "Next", finish: "Finish", cited: "Cited page",
      chips: ["Summarize my document", "What are the key definitions?", "Explain the main idea simply", "Make flashcards", "Quiz me"],
      greeting: "Hi! I'm your KnowledgeOS assistant. Upload a document in Library, then ask me anything — by typing or with the mic. I'll show the exact page each answer comes from.",
    },
    hi: {
      brandSub: "अपने डॉक्यूमेंट्स से सीखें।", navTalk: "बात करें", navLibrary: "लाइब्रेरी", navStudy: "पढ़ाई", navSettings: "सेटिंग्स",
      navGuide: "गाइड", tagline: "आपका AI स्टडी असिस्टेंट",
      heroSub: "अपनी PDF और नोट्स के बारे में पूछिए — हर जवाब के साथ वो पेज दिखेगा जहाँ से वो आया।",
      placeholder: "अपना सवाल लिखिए...", tap: "बोलने के लिए टैप करें", listening: "सुन रहा हूँ… रोकने के लिए टैप करें",
      thinking: "सोच रहा हूँ…", speaking: "बोल रहा हूँ… रोकने के लिए टैप करें", libTitle: "आपकी लाइब्रेरी",
      libSub: "PDF, Word, Markdown, text, CSV या Excel फ़ाइलें अपलोड कीजिए। ये इसी Colab सेशन में रहती हैं।",
      dzTitle: "फ़ाइलें यहाँ छोड़ें या क्लिक करके अपलोड करें", progressHint: "बड़ी PDF में फ़्री Colab पर कुछ मिनट लग सकते हैं।",
      studyTitle: "पढ़ाई मोड", studySub: "एक डॉक्यूमेंट चुनिए और उससे फ़्लैशकार्ड, क्विज़ या नोट्स बनाइए।", setTitle: "सेटिंग्स",
      setAI: "AI जवाब", setAIsub: "AI के बिना ऐप सबसे मिलते-जुलते हिस्से दिखाता है। AI जोड़ने पर स्रोत के साथ पूरा जवाब लिखता है।",
      setVoice: "आवाज़", optCont: "हैंड्स-फ़्री वॉइस चैट: हर जवाब के बाद फिर से सुनना शुरू करें", optSpeak: "जवाब बोलकर सुनाएँ",
      optRate: "बोलने की रफ़्तार", voiceNote: "आवाज़ Chrome या Edge में सबसे अच्छी चलती है। ब्राउज़र पूछे तो माइक की अनुमति दीजिए।",
      restartGuide: "गाइडेड टूर फिर से शुरू करें", advNote: "Evaluation lab, diagnostics और एडवांस सेटिंग्स क्लासिक ऐप (CELL 64) में हैं।",
      skip: "टूर छोड़ें", back: "पीछे", next: "आगे", finish: "समाप्त", cited: "स्रोत वाला पेज",
      chips: ["मेरे डॉक्यूमेंट का सारांश बताओ", "मुख्य परिभाषाएँ क्या हैं?", "मुख्य विचार आसान भाषा में समझाओ", "फ़्लैशकार्ड बनाओ", "मेरा क्विज़ लो"],
      greeting: "नमस्ते! मैं आपका KnowledgeOS असिस्टेंट हूँ। Library में डॉक्यूमेंट अपलोड कीजिए, फिर टाइप करके या माइक से कुछ भी पूछिए। हर जवाब के साथ मैं वो पेज दिखाऊँगा जहाँ से जवाब आया।",
    },
  };
  const TOUR = {
    en: [
      [null, "Welcome to KnowledgeOS AI 👋", "A one-minute tour of the app. You can skip it anytime and reopen it from Guide."],
      ["#nav-library", "1 · Add your documents", "Open Library and upload your PDFs or notes. Wait until each shows “ready”."],
      ["#composer", "2 · Ask by typing", "Type a question and press Enter. Answers are written only from your documents."],
      ["#big-mic", "3 · Talk to it", "Tap the mic and speak. It answers out loud and keeps listening — a real voice conversation. Tap again to stop."],
      ["#in-mic", "Mic in the message box", "This mic starts the same voice chat right from where you type."],
      ["#chips", "Quick ideas", "Not sure what to ask? Tap a suggestion."],
      [null, "Every answer shows its proof", "Numbers like [1] and the 📄 source chips under an answer open the exact PDF page on the right, with the evidence highlighted."],
      ["#nav-study", "4 · Study mode", "Turn any document into flip-cards, a quiz, a summary or study notes in one click."],
      ["#nav-settings", "5 · Turn on AI answers", "Add a free Gemini API key in Settings. Without it you still get the matching passages."],
      ["#lang-top", "Language & voice", "Switch between English and हिंदी for the voice chat and labels. The speaker button turns spoken answers on or off."],
      ["#help-btn", "Need help later?", "Click here or Guide anytime to see this tour again. Happy learning! ✨"],
    ],
    hi: [
      [null, "KnowledgeOS AI में आपका स्वागत है 👋", "एक मिनट में ऐप समझिए। कभी भी छोड़ सकते हैं और Guide से फिर खोल सकते हैं।"],
      ["#nav-library", "1 · डॉक्यूमेंट जोड़ें", "Library खोलकर अपनी PDF या नोट्स अपलोड कीजिए। “ready” दिखने तक रुकिए।"],
      ["#composer", "2 · टाइप करके पूछें", "सवाल लिखिए और Enter दबाइए। जवाब सिर्फ़ आपके डॉक्यूमेंट से बनता है।"],
      ["#big-mic", "3 · बोलकर बात करें", "माइक टैप करके बोलिए। यह जवाब बोलकर सुनाता है और फिर सुनने लगता है — असली वॉइस बातचीत। रोकने के लिए फिर टैप करें।"],
      ["#in-mic", "मैसेज बॉक्स में माइक", "यह माइक भी वही वॉइस चैट शुरू करता है, ठीक वहीं से जहाँ आप लिखते हैं।"],
      ["#chips", "झटपट सुझाव", "क्या पूछें समझ न आए तो किसी सुझाव पर टैप कीजिए।"],
      [null, "हर जवाब का सबूत", "जवाब में [1] जैसे नंबर और नीचे 📄 चिप्स पर क्लिक करते ही दाईं ओर PDF का वही पेज खुलता है, जवाब वाला हिस्सा हाईलाइट होकर।"],
      ["#nav-study", "4 · पढ़ाई मोड", "एक क्लिक में किसी भी डॉक्यूमेंट से फ़्लैशकार्ड, क्विज़, सारांश या नोट्स बनाइए।"],
      ["#nav-settings", "5 · AI जवाब चालू करें", "Settings में Gemini की फ़्री API key डालिए। उसके बिना भी मिलते-जुलते हिस्से दिखते हैं।"],
      ["#lang-top", "भाषा और आवाज़", "वॉइस चैट और लेबल के लिए English या हिंदी चुनिए। स्पीकर बटन से बोलकर जवाब चालू/बंद होते हैं।"],
      ["#help-btn", "बाद में मदद चाहिए?", "यह टूर दोबारा देखने के लिए यहाँ या Guide पर क्लिक कीजिए। पढ़ाई मुबारक! ✨"],
    ],
  };

  const S = {
    owner: store.get("owner", null) || ("w_" + Math.random().toString(36).slice(2) + Date.now().toString(36)),
    conv: null, lang: store.get("lang", "en"), theme: store.get("theme", "dark"), speak: store.get("speak", true),
    continuous: store.get("continuous", true), rate: store.get("rate", 1), scope: [], docs: [], busy: false,
    voice: "idle", viewer: null, providerOn: false,
  };
  store.set("owner", S.owner);
  const t = (k) => (T[S.lang] && T[S.lang][k]) || T.en[k] || k;

  // ------------------------------------------------------------------ helpers
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  let toastTimer;
  function toast(msg, kind = "") {
    const el = $("#toast");
    el.textContent = msg; el.className = "toast show " + kind;
    clearTimeout(toastTimer); toastTimer = setTimeout(() => (el.className = "toast " + kind), 4200);
  }
  async function api(path, opts = {}) {
    const init = { method: opts.method || (opts.body ? "POST" : "GET"), headers: {} };
    if (opts.body instanceof FormData) init.body = opts.body;
    else if (opts.body) { init.body = JSON.stringify(opts.body); init.headers["Content-Type"] = "application/json"; }
    let res;
    try { res = await fetch(path, init); } catch { throw new Error("Can't reach the app server. Is the Colab cell still running?"); }
    let data = {};
    try { data = await res.json(); } catch { /* non-JSON */ }
    if (!res.ok || data.error) throw new Error(data.error || `Request failed (${res.status})`);
    return data;
  }

  // Small, safe markdown renderer (input is escaped first). Citations [n] become buttons.
  function inline(s, markers) {
    let h = esc(s);
    h = h.replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
      .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<i>$2</i>")
      .replace(/(^|\s)_([^_\n]+)_(?=[\s.,;:!?)]|$)/g, "$1<i>$2</i>");
    if (markers) {
      h = h.replace(/\[(\d+(?:\s*,\s*\d+)*)(\??)\]/g, (m, nums, q) => nums.split(",").map((n) => {
        n = n.trim();
        if (q || !(n in markers)) return `<span class="cite bad" title="This citation could not be verified">${n}?</span>`;
        return `<button class="cite" data-src="${markers[n]}" title="Open source ${n}">${n}</button>`;
      }).join(""));
    }
    return h;
  }
  function md(text, markers) {
    const lines = String(text || "").replace(/\r/g, "").split("\n");
    let out = [], list = null, para = [], i = 0;
    const flushP = () => { if (para.length) { out.push("<p>" + para.map((l) => inline(l, markers)).join("<br>") + "</p>"); para = []; } };
    const flushL = () => { if (list) { out.push(`</${list}>`); list = null; } };
    while (i < lines.length) {
      const line = lines[i];
      if (/^```/.test(line)) {
        flushP(); flushL(); const buf = []; i++;
        while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
        out.push("<pre><code>" + esc(buf.join("\n")) + "</code></pre>"); i++; continue;
      }
      if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
        flushP(); flushL();
        const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        let h = "<table><thead><tr>" + cells(line).map((c) => `<th>${inline(c, markers)}</th>`).join("") + "</tr></thead><tbody>";
        i += 2;
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) h += "<tr>" + cells(lines[i++]).map((c) => `<td>${inline(c, markers)}</td>`).join("") + "</tr>";
        out.push(h + "</tbody></table>"); continue;
      }
      let m;
      if ((m = line.match(/^(#{1,4})\s+(.*)$/))) { flushP(); flushL(); out.push(`<h${m[1].length + 1}>${inline(m[2], markers)}</h${m[1].length + 1}>`); }
      else if ((m = line.match(/^\s*[-*•]\s+(.*)$/))) { flushP(); if (list !== "ul") { flushL(); out.push("<ul>"); list = "ul"; } out.push(`<li>${inline(m[1], markers)}</li>`); }
      else if ((m = line.match(/^\s*\d+[.)]\s+(.*)$/))) { flushP(); if (list !== "ol") { flushL(); out.push("<ol>"); list = "ol"; } out.push(`<li>${inline(m[1], markers)}</li>`); }
      else if ((m = line.match(/^>\s?(.*)$/))) { flushP(); flushL(); out.push(`<blockquote>${inline(m[1], markers)}</blockquote>`); }
      else if (!line.trim()) { flushP(); flushL(); }
      else { flushL(); para.push(line); }
      i++;
    }
    flushP(); flushL();
    return out.join("");
  }
  const ICON_DOC = '<svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>';

  // ------------------------------------------------------------------ language & theme
  function applyLang() {
    document.documentElement.lang = S.lang;
    $$("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
    $("#q").placeholder = t("placeholder");
    $$("[data-lang-toggle] button").forEach((b) => b.classList.toggle("on", b.dataset.lang === S.lang));
    renderChips(); setVoiceState(S.voice);
  }
  function applyTheme() {
    document.documentElement.dataset.theme = S.theme;
    $("#theme-icon").innerHTML = S.theme === "dark"
      ? '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/>'
      : '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>';
  }
  $$("[data-lang-toggle] button").forEach((b) => b.addEventListener("click", () => { S.lang = b.dataset.lang; store.set("lang", S.lang); applyLang(); }));
  $("#theme-btn").addEventListener("click", () => { S.theme = S.theme === "dark" ? "light" : "dark"; store.set("theme", S.theme); applyTheme(); });
  function applySpeak() { $("#speak-btn").classList.toggle("off", !S.speak); $("#opt-speak").checked = S.speak; }
  $("#speak-btn").addEventListener("click", () => { S.speak = !S.speak; store.set("speak", S.speak); applySpeak(); if (!S.speak) speechSynthesis.cancel(); toast(S.speak ? "🔊 Answers will be read aloud" : "🔇 Spoken answers off"); });

  // ------------------------------------------------------------------ navigation
  function show(view) {
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
    $$(".nav-item[data-view]").forEach((n) => n.classList.toggle("active", n.dataset.view === view));
    $("#sidebar").classList.remove("open");
    if (view === "library" || view === "study") refresh();
    if (view === "settings") loadSettings();
  }
  $$(".nav-item[data-view]").forEach((n) => n.addEventListener("click", () => show(n.dataset.view)));
  $("#menu-btn").addEventListener("click", () => $("#sidebar").classList.toggle("open"));

  // ------------------------------------------------------------------ state
  async function refresh() {
    let st;
    try { st = await api("/api/state"); } catch (e) { toast(e.message, "err"); return; }
    S.docs = st.docs; S.limits = st.limits; S.providerOn = st.provider.available;
    $("#doc-count").textContent = st.stats.ready_documents;
    const pill = $("#status-pill");
    pill.classList.toggle("on", st.provider.available);
    $("#status-text").textContent = st.provider.available ? `AI: ${st.provider.model || st.provider.provider}` : "AI answers off";
    pill.title = st.provider.detail;
    $("#dz-sub").textContent = `PDF · DOCX · TXT · MD · CSV · XLSX — up to ${st.limits.max_file_mb} MB each`;
    renderDocs(); renderStudyDocs(); renderScope();
  }

  // ------------------------------------------------------------------ chat
  function renderChips() {
    $("#chips").innerHTML = t("chips").map((c, i) => `<button class="chip" data-i="${i}">${esc(c)}</button>`).join("");
    $$("#chips .chip").forEach((b) => b.addEventListener("click", () => {
      const i = +b.dataset.i;
      if (i === 3 || i === 4) { show("study"); setTimeout(() => runStudy(i === 3 ? "flashcards" : "quiz"), 50); return; }
      ask(b.textContent);
    }));
  }
  function setChatting() { $(".talk").classList.add("chatting"); $("#hero").classList.add("compact"); }
  function addMsg(role, html) {
    const el = document.createElement("div");
    el.className = "msg " + role; el.innerHTML = html;
    $("#messages").appendChild(el); setChatting();
    requestAnimationFrame(() => { $("#messages").scrollTop = $("#messages").scrollHeight; });
    return el;
  }
  const KIND = {
    grounded: "✓ Answer from your documents", evidence: "Evidence only — add an AI key in Settings for full answers",
    unverified: "⚠ Citations could not be verified", insufficient: "Not enough evidence in your documents",
    general: "General knowledge — not from your documents", info: "",
  };
  async function ask(question, spoken = false) {
    question = (question || "").trim();
    if (!question || S.busy) return;
    S.busy = true; $("#send").disabled = true; $("#q").value = "";
    addMsg("user", esc(question));
    const pending = addMsg("bot", '<div class="typing"><span></span><span></span><span></span></div>');
    setVoiceState(S.voice === "idle" ? "idle" : "thinking");
    let r;
    try {
      r = await api("/api/ask", { body: { question, owner: S.owner, conv_id: S.conv, doc_ids: S.scope } });
    } catch (e) {
      pending.innerHTML = `<div class="kind insufficient">⛔ ${esc(e.message)}</div>`;
      S.busy = false; $("#send").disabled = false;
      if (S.voice !== "idle") setVoiceState("idle");
      return;
    }
    S.conv = r.conv_id;
    const kind = KIND[r.kind] ? `<div class="kind ${r.kind}">${KIND[r.kind]}</div>` : "";
    const chips = r.sources.length
      ? `<div class="src-row">${r.sources.map((s) => `<button class="src-chip ${s.cited ? "cited" : ""}" data-src="${s.i}">${ICON_DOC}${esc(s.filename)}${s.page ? " · p. " + s.page : ""}</button>`).join("")}</div>` : "";
    const warns = (r.warnings || []).filter((w) => !/General-knowledge/.test(w)).slice(0, 2)
      .map((w) => `<div class="warn-line">⚠ ${esc(w)}</div>`).join("");
    pending.innerHTML = kind + md(r.answer, r.markers) + chips + warns +
      `<div class="msg-tools"><button data-act="speak">🔊 Listen</button><button data-act="copy">📋 Copy</button></div>`;
    pending.querySelectorAll("[data-src]").forEach((b) => b.addEventListener("click", () => openSource(r.aid, +b.dataset.src)));
    pending.querySelector('[data-act="speak"]').addEventListener("click", () => speakText(r.speak));
    pending.querySelector('[data-act="copy"]').addEventListener("click", () => { navigator.clipboard?.writeText(r.answer); toast("Copied"); });
    $("#messages").scrollTop = $("#messages").scrollHeight;
    S.busy = false; $("#send").disabled = false;
    const cited = r.sources.find((s) => s.cited);
    if (cited && window.innerWidth > 1180) openSource(r.aid, cited.i);
    if (spoken || S.voice !== "idle") afterAnswer(r.speak);
  }
  $("#send").addEventListener("click", () => ask($("#q").value));
  $("#q").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask($("#q").value); } });
  $("#new-chat").addEventListener("click", () => {
    S.conv = null; $("#messages").innerHTML = ""; $(".talk").classList.remove("chatting"); $("#hero").classList.remove("compact");
    closeViewer(); greet(); toast("New conversation");
  });
  function greet() { addMsg("bot", md(t("greeting"))); $(".talk").classList.remove("chatting"); $("#hero").classList.remove("compact"); }

  // search scope
  function renderScope() {
    const ready = S.docs.filter((d) => d.status === "ready");
    S.scope = S.scope.filter((id) => ready.some((d) => d.doc_id === id));
    const pop = $("#scope-pop");
    pop.innerHTML = `<h4>Search in…</h4>` + (ready.length ? ready.map((d) =>
      `<label><input type="checkbox" value="${esc(d.doc_id)}" ${S.scope.includes(d.doc_id) ? "checked" : ""}> ${esc(d.filename)}</label>`).join("")
      + `<div class="muted small" style="margin-top:6px">None selected = all documents.</div>` : `<div class="muted small">No ready documents yet.</div>`);
    pop.querySelectorAll("input").forEach((c) => c.addEventListener("change", () => {
      S.scope = [...pop.querySelectorAll("input:checked")].map((x) => x.value); badge();
    }));
    badge();
  }
  function badge() { const b = $("#scope-badge"); b.hidden = !S.scope.length; b.textContent = S.scope.length; }
  $("#scope-btn").addEventListener("click", (e) => { e.stopPropagation(); $("#scope-pop").hidden = !$("#scope-pop").hidden; });
  document.addEventListener("click", (e) => { if (!$("#scope-pop").contains(e.target)) $("#scope-pop").hidden = true; });

  // ------------------------------------------------------------------ source viewer
  async function openSource(aid, i, page) {
    const v = $("#viewer");
    v.classList.add("open"); v.setAttribute("aria-hidden", "false"); document.body.classList.add("viewer-open");
    $("#viewer-body").innerHTML = '<div class="skeleton"></div>';
    let r;
    try { r = await api(`/api/source?aid=${encodeURIComponent(aid)}&i=${i}${page ? "&page=" + page : ""}`); }
    catch (e) { $("#viewer-body").innerHTML = `<div class="empty"><b>Can't open this source</b>${esc(e.message)}</div>`; return; }
    S.viewer = { aid, i, page: r.page, n: r.n_pages, home: r.home_page };
    $("#viewer-title").textContent = r.filename;
    $("#viewer-sub").textContent = r.image
      ? (r.matched ? `Evidence highlighted · ${r.matched} match${r.matched > 1 ? "es" : ""}` : (r.page === r.home_page ? "Cited page" : "No highlight on this page"))
      : "Passage preview";
    let body = "";
    if (r.image) body += `<img src="${r.image}" alt="Page ${r.page}"><div class="hint">🔍 Click the page to zoom. 🟨 = passage used · 🟧 = sentence cited</div>`;
    if (r.html) body += r.html;
    (r.notes || []).forEach((n) => { body += `<div class="hint">${esc(n)}</div>`; });
    $("#viewer-body").innerHTML = body || '<div class="empty">Nothing to show.</div>';
    const img = $("#viewer-body img");
    if (img) img.addEventListener("click", () => { $("#lightbox-img").src = img.src; $("#lightbox").hidden = false; });
    $("#pg-label").textContent = r.n_pages ? `Page ${r.page} / ${r.n_pages}` : (r.page ? `Page ${r.page}` : "—");
    $("#pg-prev").disabled = !r.n_pages || r.page <= 1;
    $("#pg-next").disabled = !r.n_pages || r.page >= r.n_pages;
    $("#pg-home").disabled = !r.n_pages || r.page === r.home_page;
  }
  function closeViewer() { $("#viewer").classList.remove("open"); $("#viewer").setAttribute("aria-hidden", "true"); document.body.classList.remove("viewer-open"); }
  $("#viewer-close").addEventListener("click", closeViewer);
  $("#pg-prev").addEventListener("click", () => S.viewer && openSource(S.viewer.aid, S.viewer.i, S.viewer.page - 1));
  $("#pg-next").addEventListener("click", () => S.viewer && openSource(S.viewer.aid, S.viewer.i, S.viewer.page + 1));
  $("#pg-home").addEventListener("click", () => S.viewer && openSource(S.viewer.aid, S.viewer.i));
  $("#lightbox").addEventListener("click", () => { $("#lightbox").hidden = true; });

  // ------------------------------------------------------------------ voice chat
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null, mediaRec = null, chunks = [], retries = 0;
  function setVoiceState(st) {
    S.voice = st;
    const live = st !== "idle";
    $("#big-mic").classList.toggle("live", live); $("#in-mic").classList.toggle("live", live);
    $("#orb").className = "orb" + (st === "idle" ? "" : " " + st);
    $("#mic-label").textContent = st === "listening" ? t("listening") : st === "thinking" ? t("thinking") : st === "speaking" ? t("speaking") : t("tap");
  }
  function stopVoice() {
    try { rec && rec.abort(); } catch { /* ignore */ }
    try { mediaRec && mediaRec.state !== "inactive" && mediaRec.stop(); } catch { /* ignore */ }
    rec = null; speechSynthesis.cancel(); setVoiceState("idle");
  }
  function toggleVoice() {
    if (S.voice === "idle") { retries = 0; listen(); return; }
    if (S.voice === "listening") {
      if (mediaRec && mediaRec.state === "recording") { mediaRec.stop(); return; }   // finish recording → transcribe
      if (rec) { retries = 99; try { rec.stop(); } catch { stopVoice(); } return; }    // finish speaking → send
    }
    stopVoice();                                                                       // stop thinking/speaking
  }
  function listen() {
    speechSynthesis.cancel();
    if (SR) return listenBrowser();
    return listenRecorder();
  }
  function listenBrowser() {
    rec = new SR();
    rec.lang = S.lang === "hi" ? "hi-IN" : "en-IN";
    rec.interimResults = true; rec.maxAlternatives = 1; rec.continuous = false;
    let finalText = "";
    rec.onresult = (e) => {
      let interim = "";
      for (let k = e.resultIndex; k < e.results.length; k++) {
        if (e.results[k].isFinal) finalText += e.results[k][0].transcript; else interim += e.results[k][0].transcript;
      }
      $("#q").value = (finalText + interim).trim();
    };
    rec.onerror = (e) => {
      if (e.error === "no-speech" && retries < 1 && S.voice === "listening") { retries++; return; }
      if (e.error === "not-allowed" || e.error === "service-not-allowed") toast("🎤 Microphone blocked — allow mic access in the browser's address bar.", "err");
      else if (e.error === "network") { toast("Browser speech service unavailable — using the built-in recognizer instead."); rec = null; listenRecorder(); return; }
      else if (e.error !== "aborted" && e.error !== "no-speech") toast("Voice error: " + e.error, "err");
    };
    rec.onend = () => {
      if (S.voice !== "listening") return;
      const text = finalText.trim();
      if (text) { setVoiceState("thinking"); ask(text, true); }
      else if (retries === 1) { retries++; try { rec.start(); } catch { stopVoice(); } }
      else stopVoice();
    };
    try { rec.start(); setVoiceState("listening"); } catch { listenRecorder(); }
  }
  async function listenRecorder() {
    if (!navigator.mediaDevices?.getUserMedia) { toast("This browser can't record audio. Try Chrome.", "err"); return stopVoice(); }
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch { toast("🎤 Microphone blocked — allow mic access in the browser's address bar.", "err"); return stopVoice(); }
    chunks = [];
    mediaRec = new MediaRecorder(stream);
    mediaRec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    mediaRec.onstop = async () => {
      stream.getTracks().forEach((tr) => tr.stop());
      if (S.voice !== "listening") return;
      setVoiceState("thinking");
      const fd = new FormData();
      fd.append("audio", new Blob(chunks, { type: mediaRec.mimeType || "audio/webm" }), "speech.webm");
      fd.append("mode", "transcribe");
      try { const r = await api("/api/transcribe", { body: fd }); $("#q").value = r.text; ask(r.text, true); }
      catch (e) { toast(e.message, "err"); stopVoice(); }
    };
    mediaRec.start(); setVoiceState("listening");
    toast("🎤 Recording… tap the mic again when you finish speaking.");
    setTimeout(() => mediaRec && mediaRec.state === "recording" && mediaRec.stop(), 30000);
  }
  function pickVoice() {
    const want = S.lang === "hi" ? "hi" : "en";
    const vs = speechSynthesis.getVoices();
    return vs.find((v) => v.lang.toLowerCase().startsWith(want + "-in")) || vs.find((v) => v.lang.toLowerCase().startsWith(want)) || null;
  }
  function speakText(text, onDone) {
    if (!("speechSynthesis" in window) || !text) { onDone && onDone(); return; }
    speechSynthesis.cancel();
    const parts = text.match(/[^.!?।]+[.!?।]?/g) || [text];
    const voice = pickVoice();
    parts.forEach((p, idx) => {
      const u = new SpeechSynthesisUtterance(p.trim());
      if (voice) u.voice = voice;
      u.lang = voice ? voice.lang : (S.lang === "hi" ? "hi-IN" : "en-IN");
      u.rate = S.rate;
      if (idx === parts.length - 1) { u.onend = () => onDone && onDone(); u.onerror = () => onDone && onDone(); }
      speechSynthesis.speak(u);
    });
  }
  function afterAnswer(text) {
    const next = () => { if (S.voice !== "idle" && S.continuous) { retries = 0; listen(); } else setVoiceState("idle"); };
    if (S.speak) { setVoiceState("speaking"); speakText(text, () => { if (S.voice === "speaking") next(); }); }
    else next();
  }
  $("#big-mic").addEventListener("click", toggleVoice);
  $("#in-mic").addEventListener("click", toggleVoice);
  $("#orb").addEventListener("click", () => { if (S.voice === "speaking") stopVoice(); });

  // ------------------------------------------------------------------ library
  function fmtSize(n) { return n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB"; }
  function renderDocs() {
    const g = $("#doc-grid");
    if (!S.docs.length) { g.innerHTML = '<div class="empty" style="grid-column:1/-1"><b>No documents yet</b>Upload your first PDF above to get started.</div>'; return; }
    g.innerHTML = S.docs.map((d) => `
      <div class="doc glass" data-id="${esc(d.doc_id)}">
        <div class="doc-ico">${esc(d.type.replace(".", "").toUpperCase().slice(0, 4))}</div>
        <div style="min-width:0">
          <div class="doc-name">${esc(d.filename)}</div>
          <div class="doc-meta">${fmtSize(d.size)} · ${d.chunks} chunks</div>
          <span class="status ${esc(d.status)}">${esc(d.status)}</span>
          ${d.error ? `<div class="doc-meta" style="color:var(--err)">${esc(d.error)}</div>` : ""}
          ${d.warnings.length ? `<div class="doc-meta" title="${esc(d.warnings.join("\n"))}">⚠ ${d.warnings.length} note(s)</div>` : ""}
        </div>
        <button class="doc-del" title="Delete"><svg viewBox="0 0 24 24"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg></button>
      </div>`).join("");
    $$(".doc .doc-del").forEach((b) => b.addEventListener("click", async () => {
      const card = b.closest(".doc"), name = card.querySelector(".doc-name").textContent;
      if (!confirm(`Delete “${name}” and its search index? This can't be undone.`)) return;
      try { const r = await api("/api/docs/delete", { body: { doc_id: card.dataset.id } }); toast(r.message, "ok"); refresh(); }
      catch (e) { toast(e.message, "err"); }
    }));
  }
  async function upload(files) {
    files = [...files];
    if (!files.length) return;
    const max = (S.limits?.max_file_mb || 25) * 1048576;
    const big = files.filter((f) => f.size > max);
    if (big.length) toast(`Skipped (too large): ${big.map((f) => f.name).join(", ")}`, "err");
    files = files.filter((f) => f.size <= max);
    if (!files.length) return;
    const fd = new FormData(); files.forEach((f) => fd.append("files", f, f.name));
    const box = $("#progress"); box.hidden = false;
    $("#progress-msg").textContent = "Uploading…"; $("#progress-pct").textContent = "0%"; $("#progress-bar").style.width = "2%";
    let job;
    try { job = (await api("/api/upload", { body: fd })).job; } catch (e) { box.hidden = true; toast(e.message, "err"); return; }
    for (;;) {
      await new Promise((r) => setTimeout(r, 900));
      let j;
      try { j = await api("/api/job/" + job); } catch (e) { toast(e.message, "err"); break; }
      const pct = Math.round(j.progress * 100);
      $("#progress-msg").textContent = j.message; $("#progress-pct").textContent = pct + "%"; $("#progress-bar").style.width = Math.max(pct, 2) + "%";
      if (j.done) {
        const bad = j.reports.filter((r) => r.status !== "indexed");
        toast(bad.length ? bad.map((r) => `${r.filename}: ${r.message}`).join(" · ") : `✓ ${j.reports.length} file(s) ready`, bad.length ? "err" : "ok");
        setTimeout(() => { box.hidden = true; }, 1500);
        break;
      }
    }
    $("#file-input").value = ""; refresh();
  }
  $("#file-input").addEventListener("change", (e) => upload(e.target.files));
  const dz = $("#dropzone");
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
  dz.addEventListener("drop", (e) => upload(e.dataTransfer.files));

  // ------------------------------------------------------------------ study
  const ACTIONS = [
    ["summary", "📄", "Summary", "Key points in a minute"], ["flashcards", "🃏", "Flashcards", "Tap a card to flip it"],
    ["quiz", "❓", "Quiz", "Click an answer to check"], ["notes", "📝", "Study notes", "Headings and bullets"],
    ["terms", "🔑", "Key terms", "Works without AI"],
  ];
  $("#action-grid").innerHTML = ACTIONS.map(([k, i, tt, d]) => `<button class="action" data-k="${k}" id="act-${k}"><div class="ai">${i}</div><div class="at">${tt}</div><div class="ad">${d}</div></button>`).join("");
  $$(".action").forEach((b) => b.addEventListener("click", () => runStudy(b.dataset.k)));
  function renderStudyDocs() {
    const sel = $("#study-doc"), cur = sel.value;
    const ready = S.docs.filter((d) => d.status === "ready");
    sel.innerHTML = ready.length ? ready.map((d) => `<option value="${esc(d.doc_id)}">${esc(d.filename)}</option>`).join("")
      : '<option value="">Upload a document in Library first</option>';
    if (cur && ready.some((d) => d.doc_id === cur)) sel.value = cur;
  }
  async function runStudy(kind) {
    const doc = $("#study-doc").value, out = $("#study-out");
    if (!doc) { toast("Upload a document in Library first.", "err"); return; }
    const btn = $("#act-" + kind); btn.classList.add("busy");
    out.innerHTML = '<div class="skeleton" style="height:220px"></div>';
    let r;
    try { r = await api("/api/study", { body: { action: kind, doc_id: doc, count: 8 } }); }
    catch (e) { out.innerHTML = `<div class="empty"><b>Couldn't create it</b>${esc(e.message)}</div>`; btn.classList.remove("busy"); return; }
    btn.classList.remove("busy");
    const warn = (r.warnings || []).slice(0, 2).map((w) => `<div class="warn-line">⚠ ${esc(w)}</div>`).join("");
    if (r.task === "flashcards" && r.items) out.innerHTML = `<h3>${esc(r.title)}</h3>${warn}` + flashcards(r.items);
    else if (r.task === "quiz" && r.items) { out.innerHTML = `<h3>${esc(r.title)}</h3>${warn}<div class="score" id="score"></div>` + quiz(r.items); wireQuiz(r.items); }
    else out.innerHTML = `<div class="result-card glass">${warn}${md(r.markdown)}</div>`;
    $$(".fc", out).forEach((c) => c.addEventListener("click", () => c.classList.toggle("flipped")));
  }
  function flashcards(items) {
    if (!items.length) return '<div class="empty"><b>No cards</b>The AI did not return usable cards. Try again.</div>';
    return '<div class="fc-grid">' + items.map((c, i) => `
      <div class="fc"><div class="fc-inner">
        <div class="fc-face fc-front"><div class="tag">Card ${i + 1} · tap to flip</div><div class="txt">${esc(c.front)}</div></div>
        <div class="fc-face fc-back"><div class="tag">Answer</div><div class="txt">${esc(c.back)}</div>
          <div class="src">${c.verified_source ? "✅" : "⚠️"} ${esc(c.source_label || "")}</div></div>
      </div></div>`).join("") + "</div>";
  }
  function quiz(items) {
    if (!items.length) return '<div class="empty"><b>No questions</b>The AI did not return usable questions. Try again.</div>';
    return items.map((q, i) => `
      <div class="quiz-q glass" data-q="${i}"><div class="qt">${i + 1}. ${esc(q.question)}</div>
        ${q.options.map((o, j) => `<button class="opt" data-j="${j}"><b>${"ABCDEFGH"[j]}.</b> ${esc(o)}</button>`).join("")}
        <div class="exp" hidden>${esc(q.explanation || "")} <span class="muted small">· ${q.verified_source ? "✅" : "⚠️"} ${esc(q.source_label || "")}</span></div>
      </div>`).join("");
  }
  function wireQuiz(items) {
    let answered = 0, right = 0;
    $$(".quiz-q").forEach((qEl) => {
      const q = items[+qEl.dataset.q];
      qEl.querySelectorAll(".opt").forEach((b) => b.addEventListener("click", () => {
        const j = +b.dataset.j;
        qEl.querySelectorAll(".opt").forEach((x) => { x.disabled = true; if (+x.dataset.j === q.answer_index) x.classList.add("right"); });
        if (j !== q.answer_index) b.classList.add("wrong"); else right++;
        answered++; qEl.querySelector(".exp").hidden = false;
        $("#score").textContent = `Score: ${right} / ${answered}` + (answered === items.length ? (right === items.length ? " 🎉 Perfect!" : " — try again to improve!") : "");
      }));
    });
  }

  // ------------------------------------------------------------------ settings
  async function loadSettings() {
    let s;
    try { s = await api("/api/settings"); } catch (e) { toast(e.message, "err"); return; }
    $("#set-provider").innerHTML = s.providers.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
    $("#set-provider").value = s.provider;
    syncProvider(s);
    $("#set-msg").textContent = s.status.available ? "✓ " + s.status.detail : s.status.detail;
    $("#set-msg").className = "note " + (s.status.available ? "ok" : "");
    S._settings = s;
  }
  function syncProvider(s = S._settings) {
    const p = $("#set-provider").value;
    $("#base-wrap").hidden = p !== "openai_compatible";
    $("#set-model").disabled = $("#set-key").disabled = p === "none";
    if (!s) return;
    $("#set-model").value = p === "gemini" ? s.gemini_model : p === "openai_compatible" ? s.llm_model : "";
    $("#set-base").value = s.llm_base_url;
    $("#key-state").textContent = p === "none" ? "" : `(${s.keys[p] || "not set"})`;
  }
  $("#set-provider").addEventListener("change", () => syncProvider());
  $("#set-save").addEventListener("click", async () => {
    const msg = $("#set-msg");
    try {
      const s = await api("/api/settings", { body: { provider: $("#set-provider").value, model: $("#set-model").value, key: $("#set-key").value, base_url: $("#set-base").value } });
      $("#set-key").value = ""; S._settings = s; syncProvider(s);
      msg.textContent = "Saved. " + (s.status.available ? "✓ " + s.status.detail : s.status.detail); msg.className = "note " + (s.status.available ? "ok" : "");
      refresh();
    } catch (e) { msg.textContent = e.message; msg.className = "note err"; }
  });
  $("#set-test").addEventListener("click", async () => {
    const msg = $("#set-msg"); msg.textContent = "Testing…"; msg.className = "note";
    try { const r = await api("/api/settings/test", { method: "POST", body: {} }); msg.textContent = (r.ok ? "✓ " : "✗ ") + r.message; msg.className = "note " + (r.ok ? "ok" : "err"); }
    catch (e) { msg.textContent = e.message; msg.className = "note err"; }
  });
  $("#opt-continuous").checked = S.continuous;
  $("#opt-continuous").addEventListener("change", (e) => { S.continuous = e.target.checked; store.set("continuous", S.continuous); });
  $("#opt-speak").addEventListener("change", (e) => { S.speak = e.target.checked; store.set("speak", S.speak); applySpeak(); });
  $("#opt-rate").value = S.rate; $("#rate-val").textContent = (+S.rate).toFixed(2) + "×";
  $("#opt-rate").addEventListener("input", (e) => { S.rate = +e.target.value; store.set("rate", S.rate); $("#rate-val").textContent = S.rate.toFixed(2) + "×"; });

  // ------------------------------------------------------------------ guided tour
  let tourIdx = 0;
  function startTour() { show("talk"); tourIdx = 0; $("#tour").hidden = false; renderTour(); }
  function endTour() { $("#tour").hidden = true; store.set("tour_done", true); }
  function renderTour() {
    const steps = TOUR[S.lang] || TOUR.en;
    const [sel, title, text] = steps[tourIdx];
    $("#tour-step").textContent = `${tourIdx + 1} / ${steps.length}`;
    $("#tour-title").textContent = title; $("#tour-text").textContent = text;
    $("#tour-dots").innerHTML = steps.map((_, i) => `<i class="${i === tourIdx ? "on" : ""}"></i>`).join("");
    $("#tour-back").disabled = tourIdx === 0;
    $("#tour-next").textContent = tourIdx === steps.length - 1 ? t("finish") : t("next");
    let el = sel && $(sel);
    if (el && window.innerWidth <= 980 && el.closest("#sidebar")) { $("#sidebar").classList.add("open"); }
    else if (window.innerWidth <= 980) $("#sidebar").classList.remove("open");
    const spot = $("#tour-spot"), card = $("#tour-card");
    const r = el && el.getBoundingClientRect();
    if (!r || !r.width) {
      spot.classList.add("center");
      card.style.left = `calc(50% - ${card.offsetWidth / 2}px)`; card.style.top = "32%";
      return;
    }
    spot.classList.remove("center");
    const pad = 8;
    Object.assign(spot.style, { left: r.left - pad + "px", top: r.top - pad + "px", width: r.width + pad * 2 + "px", height: r.height + pad * 2 + "px" });
    const cw = card.offsetWidth, ch = card.offsetHeight, vw = window.innerWidth, vh = window.innerHeight;
    let left = r.right + 20, top = r.top + r.height / 2 - ch / 2;
    if (left + cw > vw - 16) { left = Math.min(Math.max(16, r.left + r.width / 2 - cw / 2), vw - cw - 16); top = r.top - ch - 20; if (top < 16) top = r.bottom + 20; }
    card.style.left = Math.max(16, left) + "px"; card.style.top = Math.min(Math.max(16, top), vh - ch - 16) + "px";
  }
  $("#tour-next").addEventListener("click", () => { const n = (TOUR[S.lang] || TOUR.en).length; if (tourIdx >= n - 1) endTour(); else { tourIdx++; renderTour(); } });
  $("#tour-back").addEventListener("click", () => { if (tourIdx > 0) { tourIdx--; renderTour(); } });
  $("#tour-skip").addEventListener("click", endTour);
  document.addEventListener("keydown", (e) => {
    if ($("#tour").hidden) { if (e.key === "Escape") { closeViewer(); $("#lightbox").hidden = true; } return; }
    if (e.key === "Escape") endTour(); if (e.key === "ArrowRight") $("#tour-next").click(); if (e.key === "ArrowLeft") $("#tour-back").click();
  });
  window.addEventListener("resize", () => { if (!$("#tour").hidden) renderTour(); });
  $("#help-btn").addEventListener("click", startTour);
  $("#nav-guide").addEventListener("click", startTour);
  $("#set-guide").addEventListener("click", startTour);

  // ------------------------------------------------------------------ boot
  applyTheme(); applySpeak(); applyLang(); greet(); refresh();
  if ("speechSynthesis" in window) speechSynthesis.onvoiceschanged = () => {};
  if (!store.get("tour_done", false)) setTimeout(startTour, 700);
  window.KOS = { state: S, ask, openSource, startTour, show };  // handy for debugging in the console
})();
