/* Review UI adds no manuscript typography or layout rules. */
document.addEventListener("DOMContentLoaded", () => {
  const panel = document.getElementById("quarto-review");
  if (!panel) return;
  const root = document.querySelector("main") || document.body;
  const titleBlock = document.getElementById("title-block-header");
  const externalTitle = titleBlock && !root.contains(titleBlock);
  // Manuscript projects place their native title/abstract before <main>.
  const scope = externalTitle ? document.body : root;
  const inContent = node => root.contains(node) || Boolean(externalTitle && titleBlock.contains(node));
  // These elements carry manuscript content without requiring a text node.
  // Treat them as units so picture/SVG/math descendants are not marked twice.
  const atomicContent = ".math,img,picture,svg,video,audio,canvas,iframe,object,embed";
  const active = new Map();
  const items = [...panel.querySelectorAll(".qr-thread,.qr-suggestion")];
  const threads = items.filter(node => node.classList.contains("qr-thread"));
  const suggestions = items.filter(node => node.classList.contains("qr-suggestion"));
  const itemById = new Map(items.map(node => [node.dataset.reviewId, node]));
  const marksById = new Map();
  const markChanges = new Map();
  const blockContents = new Map();
  const changeAuthors = new Map();
  for (const item of suggestions) {
    if (item.dataset.status !== "pending") continue;
    const id = item.dataset.anchorId || item.dataset.reviewId;
    if (!changeAuthors.has(id)) changeAuthors.set(id, new Set());
    changeAuthors.get(id).add(item.dataset.author || "");
  }
  const anchors = new Map();
  const walker = document.createTreeWalker(scope, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    // Quarto copies heading content into its TOC. Those copies are navigation,
    // not a second review range (which could otherwise stay open into the text).
    if (!inContent(node)) continue;
    if (node.nodeType === Node.ELEMENT_NODE && node.classList.contains("qr-boundary")) {
      const {reviewKind: kind, reviewId: id, reviewEdge: edge} = node.dataset;
      const key = `${kind}:${id}`;
      if (edge === "S") {
        active.set(key, {kind, id});
        if (!anchors.has(id)) {
          anchors.set(id, node);
          node.id = `qr-anchor-${id}`;
        }
      } else active.delete(key);
      continue;
    }
    const atomic = node.nodeType === Node.ELEMENT_NODE && node.matches(atomicContent);
    const text = node.nodeType === Node.TEXT_NODE && node.textContent.length > 0;
    if ((!atomic && !text) || active.size === 0) continue;
    if (node.parentElement?.closest(`${atomicContent},script,style,.qr-panel,.qr-controls`)) continue;
    const span = document.createElement("span");
    const entries = [...active.values()];
    span.classList.add("qr-mark");
    if (entries.some(item => item.kind === "I")) span.classList.add("qr-insert");
    if (entries.some(item => item.kind === "D")) span.classList.add("qr-delete");
    if (entries.some(item => item.kind === "C")) span.classList.add("qr-comment");
    span.dataset.reviewIds = entries.map(item => item.id).join(" ");
    markChanges.set(span, entries.filter(item => item.kind === "I" || item.kind === "D"));
    for (const {id} of entries) {
      if (!marksById.has(id)) marksById.set(id, []);
      marksById.get(id).push(span);
    }
    node.replaceWith(span);
    span.append(node);
  }
  // Point-only changes need a marker. Visible ranges provide their own
  // interaction target, so badges must not split words at imported boundaries.
  const links = [];
  for (const item of items) {
    const id = item.dataset.reviewId;
    const anchor = anchors.get(item.dataset.anchorId || id);
    if (!anchor) continue;
    anchors.set(id, anchor);
    const link = document.createElement("a");
    const change = item.dataset.kind === "suggestion";
    link.className = `qr-link ${change ? "qr-change-link" : "qr-comment-link"}`;
    link.href = `#qr-${change ? "suggestion" : "thread"}-${id}`;
    link.textContent = change ? "Δ" : id;
    link.dataset.qrTarget = id;
    link.setAttribute("aria-label", change ? `Inspect ${item.querySelector("header").textContent}` : `Read comment ${id} beside this passage`);
    link.setAttribute("aria-controls", "qr-context-panel");
    link.hidden = true;
    anchor.after(link);
    links.push(link);
  }
  const attributions = new Map();
  for (const item of suggestions) {
    const id = item.dataset.reviewId;
    const attribution = `Suggested by ${item.dataset.author || "Unattributed"} (${id}; ${item.dataset.status})`;
    for (const mark of marksById.get(item.dataset.anchorId || id) || []) {
      const existing = attributions.get(mark);
      attributions.set(mark, existing ? `${existing}\n${attribution}` : attribution);
    }
    const link = links.find(link => link.dataset.qrTarget === id);
    if (link) link.title = attribution;
  }
  for (const block of scope.querySelectorAll("p,li,figcaption")) {
    if (!inContent(block)) continue;
    if (block.closest(".qr-panel")) continue;
    const textWalker = document.createTreeWalker(block, NodeFilter.SHOW_TEXT);
    const content = [...block.querySelectorAll(atomicContent)];
    while (textWalker.nextNode()) {
      if (textWalker.currentNode.textContent.trim() && !textWalker.currentNode.parentElement.closest(".qr-link")) content.push(textWalker.currentNode);
    }
    blockContents.set(block, content);
    if (!content.length && block.querySelector(".qr-boundary")) {
      block.classList.add("qr-annotation-only-block");
      if (!block.querySelector(".qr-link")) block.classList.add("qr-boundary-block");
    }
    for (const kind of ["insert", "delete"]) {
      if (content.length && content.every(node => node.parentElement.closest(`.qr-${kind}`))) {
        block.classList.add(`qr-${kind}-only`);
        if (!block.querySelector(".qr-link")) block.classList.add(`qr-${kind}-block`);
      }
    }
  }
  const controls = panel.querySelector(".qr-controls");
  controls.id = "qr-controls";
  if (externalTitle) {
    controls.classList.add("qr-controls-external");
    titleBlock.before(controls);
  } else root.prepend(controls);
  let controlsVisible = true;
  let commentsVisible = true;
  let readingView = false;
  let paneView = "passage";
  function button(label, id, action) {
    const element = document.createElement("button");
    element.type = "button";
    element.id = id;
    element.textContent = label;
    element.addEventListener("click", action);
    return element;
  }
  const toolbarHeading = document.createElement("div");
  toolbarHeading.className = "qr-toolbar-heading";
  const toolbarTitle = document.createElement("strong");
  toolbarTitle.textContent = "Review";
  const toggleComments = button("Hide review cards", "qr-toggle-comments", () => setVisibility(controlsVisible, !commentsVisible));
  toggleComments.setAttribute("aria-controls", "qr-context-panel quarto-review");
  const readingButton = button("Reading view", "qr-reading-view", () => {
    readingView = true;
    setVisibility(false, false);
  });
  readingButton.title = "Hide review controls and cards; show clean proposed text";
  const hideControls = button("Hide controls", "qr-hide-controls", () => setVisibility(false, commentsVisible));
  hideControls.setAttribute("aria-controls", "qr-controls");
  const showList = button("Review list", "qr-show-list", () => setPaneView("list"));
  showList.setAttribute("aria-controls", "qr-context-panel");
  showList.setAttribute("aria-pressed", "false");
  toolbarHeading.append(toolbarTitle, showList, toggleComments, readingButton, hideControls);
  controls.prepend(toolbarHeading);
  const restore = button("Show review", "qr-restore-review", () => {
    readingView = false;
    setVisibility(true, true);
    view.focus({preventScroll: true});
  });
  restore.className = "qr-restore-review";
  restore.setAttribute("aria-controls", "qr-controls qr-context-panel quarto-review");
  restore.hidden = true;
  document.body.append(restore);
  const view = controls.querySelector("#qr-view");
  const author = controls.querySelector("#qr-author");
  const status = controls.querySelector("#qr-status");
  const kind = controls.querySelector("#qr-kind");
  // Own the defaults and options here too, for HTML from older pinned renderers.
  // These combined states are filters only; source decisions remain independent.
  kind.value = "";
  const statusOptions = {
    "": [["open-pending", "Open comments + pending changes"],
      ["resolved-decided", "Resolved comments + decided changes"], ["", "All statuses"]],
    comment: [["open", "Open"], ["resolved", "Resolved"], ["", "All statuses"]],
    suggestion: [["pending", "Pending"], ["decided", "Accepted or rejected"],
      ["accepted", "Accepted"], ["rejected", "Rejected"], ["", "All statuses"]],
  };
  const combinedStates = {
    "open-pending": ["open", "pending"],
    "resolved-decided": ["resolved", "accepted", "rejected"],
    decided: ["accepted", "rejected"],
  };
  let statusKind;
  function updateStatusOptions(previous = status.value) {
    const options = statusOptions[kind.value];
    let next = previous;
    if (!options.some(([value]) => value === previous)) {
      if (["open-pending", "open", "pending"].includes(previous)) next = options[0][0];
      else if (["resolved-decided", "resolved", "decided", "accepted", "rejected"].includes(previous)) next = options[1][0];
      else next = "";
    }
    status.replaceChildren(...options.map(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      return option;
    }));
    status.value = next;
    statusKind = kind.value;
  }
  updateStatusOptions("open-pending");
  const authorHint = document.createElement("p");
  authorHint.id = "qr-author-hint";
  authorHint.className = "qr-author-hint";
  authorHint.setAttribute("aria-live", "polite");
  author.setAttribute("aria-describedby", authorHint.id);
  controls.append(authorHint);
  const index = document.createElement("details");
  index.className = "qr-index";
  const summary = document.createElement("summary");
  summary.textContent = "Full review index";
  index.append(summary);
  while (panel.firstChild) index.append(panel.firstChild);
  panel.append(index);

  const dock = document.createElement("aside");
  dock.id = "qr-context-panel";
  dock.className = "qr-context-panel";
  dock.setAttribute("aria-label", "Review beside the passage");
  const dockNavigation = document.createElement("nav");
  dockNavigation.setAttribute("aria-label", "Review navigation");
  for (const [label, direction] of [["Previous review item", -1], ["Next review item", 1]]) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = direction < 0 ? "Previous" : "Next";
    button.setAttribute("aria-label", label);
    button.addEventListener("click", () => navigate(direction));
    dockNavigation.append(button);
  }
  const dockContent = document.createElement("div");
  dockContent.className = "qr-context-content";
  const hideComments = button("Hide", "qr-hide-comments", () => setVisibility(controlsVisible, false));
  hideComments.setAttribute("aria-label", "Hide review cards");
  hideComments.setAttribute("aria-controls", "qr-context-panel quarto-review");
  dockNavigation.append(hideComments);
  const paneNavigation = document.createElement("div");
  paneNavigation.className = "qr-pane-views";
  paneNavigation.setAttribute("role", "group");
  paneNavigation.setAttribute("aria-label", "Review pane view");
  const passageButton = button("At passage", "qr-pane-passage", () => setPaneView("passage"));
  const listButton = button("List", "qr-pane-list", () => setPaneView("list"));
  for (const control of [passageButton, listButton]) control.setAttribute("aria-controls", "qr-context-panel");
  passageButton.setAttribute("aria-pressed", "true");
  listButton.setAttribute("aria-pressed", "false");
  paneNavigation.append(passageButton, listButton);
  dock.append(paneNavigation, dockNavigation, dockContent);
  document.body.append(dock);

  function passageFor(anchor) {
    const figure = anchor.closest("figure,.quarto-figure");
    if (figure) return figure.closest(".quarto-figure") || figure;
    const table = anchor.closest("table");
    if (table) return table.closest(".quarto-float") || table;
    const list = anchor.closest("ul,ol");
    if (list) return list;
    let passage = anchor.closest("p,h1,h2,h3,h4,h5,h6,pre,blockquote") || anchor.parentElement;
    // Keep run-in headings adjacent to their paragraph in APA and other styles.
    if (/^H[456]$/.test(passage.tagName) && passage.nextElementSibling?.tagName === "P") passage = passage.nextElementSibling;
    return passage;
  }
  const groups = new Map();
  const groupById = new Map();
  for (const item of items) {
    const id = item.dataset.reviewId;
    const anchor = anchors.get(id);
    if (!anchor) continue;
    const passage = passageFor(anchor);
    if (!groups.has(passage)) groups.set(passage, {passage, ids: [], inline: null});
    const group = groups.get(passage);
    group.ids.push(id);
    groupById.set(id, group);
  }
  // Comments and suggestions arrive in separate sections; present their union
  // in manuscript order, keeping unanchored records available at the end.
  const orderedItems = [...items].sort((a, b) => {
    const first = anchors.get(a.dataset.reviewId), second = anchors.get(b.dataset.reviewId);
    if (!first || !second) return first ? -1 : second ? 1 : 0;
    const order = first.compareDocumentPosition(second);
    return order & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : order & Node.DOCUMENT_POSITION_PRECEDING ? 1 : 0;
  });
  const expandedItems = new Set();
  let listScrollTop = 0;
  let listKey = "";
  let mode = "";
  let selectedGroup = null;
  let selectedIds = "";
  let currentId = null;
  let selectionScrollY = null;
  let frame = 0;
  const visiblePassages = new Set();
  const matching = group => group.ids.filter(id => !itemById.get(id).hidden);

  function makeCard(id) {
    const card = itemById.get(id).cloneNode(true);
    card.classList.remove("qr-thread", "qr-suggestion");
    card.classList.add("qr-card");
    card.hidden = false;
    card.id = `qr-context-${id}`;
    for (const element of card.querySelectorAll("[id]")) element.removeAttribute("id");
    if (itemById.get(id).dataset.kind === "suggestion") return card;
    const excerpt = document.createElement("blockquote");
    excerpt.className = "qr-context-quote";
    const marks = marksById.get(id) || [];
    // Read each alternative independently, including marks hidden in the other
    // view. Concatenating visible redlines joins deleted and inserted words.
    const focused = Boolean(document.body.dataset.reviewAuthor);
    const wording = excluded => marks.filter(mark => !mark.classList.contains("qr-author-hidden") && !mark.classList.contains(excluded))
      .map(mark => mark.textContent).join("").replace(/\s+/g, " ").trim();
    const original = wording(focused ? "qr-author-insert" : "qr-insert");
    const proposed = wording(focused ? "qr-author-delete" : "qr-delete");
    const shorten = text => text.length > 360 ? text.slice(0, 357) + "…" : text;
    const textView = document.body.dataset.reviewView;
    if (textView === "review" && original !== proposed) {
      const labels = focused ? [`Before ${author.value}’s edits`, `With ${author.value}’s edits`] : ["Original", "Proposed"];
      for (const [label, text] of [[labels[0], original], [labels[1], proposed]]) {
        const line = document.createElement("div");
        const heading = document.createElement("strong");
        heading.textContent = `${label}: `;
        line.append(heading, shorten(text) || "(no text in this view)");
        excerpt.append(line);
      }
    } else {
      const text = textView === "original" ? original : proposed;
      excerpt.textContent = shorten(text) || (original || proposed ? "No text in this view" : "At this point in the text");
    }
    card.insertBefore(excerpt, card.querySelector(".qr-body"));
    return card;
  }
  function passagePreview(id) {
    const passage = groupById.get(id)?.passage;
    if (!passage) return "No passage anchor is available.";
    const copy = passage.cloneNode(true);
    copy.querySelectorAll(".qr-link,.qr-inline-comments,script,style").forEach(node => node.remove());
    const original = document.body.dataset.reviewView === "original";
    copy.querySelectorAll(original ? ".qr-insert" : ".qr-delete").forEach(node => node.remove());
    const text = copy.textContent.replace(/\s+/g, " ").trim();
    return text ? (text.length > 280 ? text.slice(0, 277) + "…" : text) : "No passage text in this reading.";
  }
  function makeListEntry(item) {
    const id = item.dataset.reviewId;
    const entry = document.createElement("details");
    entry.className = "qr-list-entry";
    entry.dataset.reviewId = id;
    const summary = document.createElement("summary");
    const heading = document.createElement("span");
    heading.className = "qr-list-heading";
    const title = item.querySelector("header").textContent.trim();
    heading.textContent = item.dataset.kind === "suggestion" ? `${id} · ${title}` : title;
    const preview = document.createElement("span");
    preview.className = "qr-list-preview";
    preview.textContent = passagePreview(id);
    summary.append(heading, preview);
    entry.append(summary);
    let populated = false;
    const populate = () => {
      if (populated) return;
      populated = true;
      const card = makeCard(id);
      // Reading or expanding a card must not navigate. Keep just the explicit
      // passage action; ordinary links in the discussion remain links.
      for (const link of card.querySelectorAll("a[data-qr-target]")) {
        const label = document.createElement("span");
        label.textContent = link.textContent;
        link.replaceWith(label);
      }
      const go = button("Go to passage", `qr-go-${id}`, () => {
        setPaneView("passage");
        anchors.get(id)?.scrollIntoView({block: "center", behavior: "instant"});
        showComment(id);
      });
      go.disabled = !anchors.has(id);
      if (go.disabled) go.title = "This review record has no passage anchor";
      card.append(go);
      entry.append(card);
    };
    entry.addEventListener("toggle", () => {
      if (entry.open) { expandedItems.add(id); populate(); }
      else expandedItems.delete(id);
    });
    if (expandedItems.has(id)) { entry.open = true; populate(); }
    return entry;
  }
  function renderList() {
    if (paneView !== "list" || !commentsVisible) return;
    const available = orderedItems.filter(item => !item.hidden);
    const key = [view.value, author.value, ...available.map(item => item.dataset.reviewId)].join("\n");
    if (dockContent.dataset.view === "list" && key === listKey) return;
    const savedScroll = listScrollTop;
    listKey = key;
    dockContent.dataset.view = "list";
    const introduction = document.createElement("p");
    introduction.className = "qr-list-introduction";
    introduction.textContent = available.length
      ? `${available.length} matching review items in manuscript order. Expand an item to read it without moving the document.`
      : "No review items match these filters.";
    dockContent.replaceChildren(introduction, ...available.map(makeListEntry));
    dockContent.scrollTop = savedScroll;
  }
  dockContent.addEventListener("scroll", () => {
    if (paneView === "list") listScrollTop = dockContent.scrollTop;
  }, {passive: true});
  function setPaneView(next) {
    if (paneView === "list") listScrollTop = dockContent.scrollTop;
    keepReadingPosition(() => {
      paneView = next;
      passageButton.setAttribute("aria-pressed", String(next === "passage"));
      listButton.setAttribute("aria-pressed", String(next === "list"));
      showList.setAttribute("aria-pressed", String(next === "list"));
      dock.setAttribute("aria-label", next === "list" ? "Filtered review list" : "Review beside the passage");
      setVisibility(controlsVisible, true);
    });
  }
  function showGroup(group, force = false) {
    if (paneView === "list") return;
    const ids = group ? matching(group) : [];
    if (selectedGroup !== group) currentId = ids[0] || group?.ids[0] || null;
    selectedGroup = group;
    if (mode !== "margin" || !commentsVisible) return;
    const key = ids.join(" ");
    if (!force && key === selectedIds) return;
    selectedIds = key;
    dockContent.dataset.view = "passage";
    dockContent.replaceChildren(...ids.map(makeCard));
    dockContent.scrollTop = 0;
    if (!ids.length) {
      const empty = document.createElement("p");
      empty.className = "qr-context-empty";
      empty.textContent = items.some(item => !item.hidden)
        ? "No matching review items at this passage. Use Next to reach one."
        : "No review items match these filters.";
      dockContent.append(empty);
    }
  }
  function followPassage() {
    if (paneView === "list") return;
    // Keep an explicitly selected item until the reader moves the document.
    // This also prevents our own navigation scroll from selecting a neighbour.
    if (selectionScrollY !== null && Math.abs(scrollY - selectionScrollY) < 1) return;
    selectionScrollY = null;
    const line = readingLine();
    let nearest = null;
    let distance = Infinity;
    for (const passage of visiblePassages) {
      const group = groups.get(passage);
      const box = passage.getBoundingClientRect();
      if (box.bottom < 0 || box.top > innerHeight) continue;
      const score = box.top > line ? box.top - line : box.bottom < line ? line - box.bottom : 0;
      if (score < distance) { nearest = group; distance = score; }
    }
    showGroup(nearest);
  }
  function scheduleFollow() {
    if (frame) return;
    frame = requestAnimationFrame(() => { frame = 0; followPassage(); });
  }
  const observer = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (entry.isIntersecting) visiblePassages.add(entry.target);
      else visiblePassages.delete(entry.target);
    }
    scheduleFollow();
  });
  for (const passage of groups.keys()) observer.observe(passage);

  function renderInline() {
    if (!commentsVisible || paneView === "list") {
      for (const group of groups.values()) if (group.inline) group.inline.hidden = true;
      return;
    }
    for (const group of groups.values()) {
      if (!group.inline) {
        group.inline = document.createElement("aside");
        group.inline.className = "qr-inline-comments";
        group.inline.setAttribute("aria-label", "Review of the preceding passage");
        group.passage.after(group.inline);
      }
      const ids = matching(group);
      group.inline.hidden = !ids.length;
      group.inline.replaceChildren(...ids.map(makeCard));
    }
  }
  function layout() {
    const header = document.getElementById("quarto-header");
    const headerBox = header?.getBoundingClientRect();
    const top = headerBox && headerBox.top <= 0 && ["fixed", "sticky"].includes(getComputedStyle(header).position) ? Math.max(0, headerBox.bottom) + 8 : 8;
    controls.style.top = `${top}px`;
    const box = root.getBoundingClientRect();
    if (externalTitle) {
      controls.style.width = `${box.width}px`;
      controls.style.marginLeft = `${box.left + scrollX}px`;
    }
    document.documentElement.style.setProperty("--qr-scroll-offset", `${controlsVisible ? controls.getBoundingClientRect().height + top + 16 : 0}px`);
    const right = innerWidth - box.right - 32;
    const left = box.left - 32;
    // Leave Quarto's own TOC/margin content alone. Use the other free margin,
    // or adjacent in-flow cards when neither side has room.
    const occupied = side => [...document.querySelectorAll("#quarto-margin-sidebar,#quarto-sidebar-toc-left,#quarto-sidebar")].some(node => {
      if (!node.textContent.trim() && !node.querySelector("img,video,svg,iframe,input,button")) return false;
      const rect = node.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && (side === "right" ? rect.left >= box.right - 8 : rect.right <= box.left + 8);
    });
    const side = right >= 270 && !occupied("right") ? "right" : left >= 270 && !occupied("left") ? "left" : null;
    const nextMode = paneView === "list" ? "list" : side ? "margin" : "inline";
    dock.hidden = !commentsVisible || nextMode === "inline";
    const dockTop = paneView === "list" && !side && controlsVisible
      ? Math.min(Math.max(top, controls.getBoundingClientRect().bottom + 8), Math.max(top, innerHeight - 180)) : top;
    dock.style.top = `${dockTop}px`;
    dock.style.maxHeight = `calc(100dvh - ${dockTop + 8}px)`;
    if (side) {
      const width = Math.min(360, side === "right" ? right : left);
      dock.style.width = `${width}px`;
      dock.style.left = `${side === "right" ? box.right + 16 : box.left - width - 16}px`;
    } else if (paneView === "list") {
      const width = Math.min(440, innerWidth - 16);
      dock.style.width = `${width}px`;
      dock.style.left = `${(innerWidth - width) / 2}px`;
    }
    if (mode === nextMode) return;
    mode = nextMode;
    document.body.dataset.reviewComments = mode;
    if (mode === "inline") {
      dockContent.dataset.view = "";
      dockContent.replaceChildren();
      selectedIds = "";
      renderInline();
    } else {
      for (const group of groups.values()) { group.inline?.remove(); group.inline = null; }
      selectedIds = "";
      if (mode === "list") {
        renderList();
        dockContent.scrollTop = listScrollTop;
      } else showGroup(selectedGroup, true);
      scheduleFollow();
    }
  }
  const interactiveMarks = new Set();
  function visibleChangeMarks(item) {
    const textView = document.body.dataset.reviewView;
    return (marksById.get(item.dataset.anchorId || item.dataset.reviewId) || []).filter(mark =>
      !mark.classList.contains("qr-author-hidden") &&
      !(textView === "proposed" && mark.classList.contains("qr-delete")) &&
      !(textView === "original" && mark.classList.contains("qr-insert")) &&
      (mark.textContent.trim() || mark.querySelector(atomicContent))
    );
  }
  function update() {
    // Hiding UI never changes the text view; only Reading view requests it.
    const clean = readingView;
    document.body.dataset.reviewClean = String(clean);
    document.body.dataset.reviewControlsVisible = String(controlsVisible);
    document.body.dataset.reviewCommentsVisible = String(commentsVisible);
    document.body.dataset.reviewView = clean ? "proposed" : view.value;
    if (statusKind !== kind.value) updateStatusOptions();
    for (const item of items) {
      item.hidden = Boolean(
        kind.value && kind.value !== item.dataset.kind ||
        author.value && !item.dataset.author.split("\n").includes(author.value) ||
        status.value && !(combinedStates[status.value] || [status.value]).includes(item.dataset.status)
      );
    }
    for (const [mark, attribution] of attributions) {
      if (clean) mark.removeAttribute("title");
      else mark.title = attribution;
    }
    // Author focus projects other authors' pending edits as proposed wording.
    // Keep the original ranges intact so changing view never changes decisions.
    const focus = !clean && view.value === "review" ? author.value : "";
    document.body.dataset.reviewAuthor = focus;
    authorHint.textContent = focus
      ? `Showing ${focus}’s pending edits in Redline. Other authors’ edits use proposed wording; no decisions change.`
      : author.value
        ? `${view.selectedOptions[0].textContent} shows all authors’ wording. Review cards are filtered to ${author.value}.`
        : "Choose an author to focus Redline on their pending edits. Review selects which cards and markers appear.";
    for (const [mark, changes] of markChanges) {
      const selected = change => changeAuthors.get(change.id)?.has(focus);
      const hidden = Boolean(focus) && changes.some(change => change.kind === "D" && !selected(change));
      mark.classList.toggle("qr-author-hidden", hidden);
      mark.classList.toggle("qr-author-plain", Boolean(focus) && changes.length > 0);
      for (const [kind, name] of [["I", "insert"], ["D", "delete"]]) {
        mark.classList.toggle(`qr-author-${name}`, Boolean(focus) && changes.some(change => change.kind === kind && selected(change)));
      }
    }
    for (const mark of interactiveMarks) {
      mark.classList.remove("qr-change-target");
      for (const attribute of ["tabindex", "role", "aria-label", "aria-controls"]) mark.removeAttribute(attribute);
    }
    interactiveMarks.clear();
    for (const link of links) {
      const item = itemById.get(link.dataset.qrTarget);
      const enabled = commentsVisible && !clean && !item.hidden;
      const change = item.dataset.kind === "suggestion";
      const visible = change ? visibleChangeMarks(item) : [];
      link.hidden = !enabled || change && visible.length > 0;
      if (!enabled || !change) continue;
      // Keep native citation/lightbox links intact. Toolbar navigation also
      // reaches those changes and changes whose text is absent in this view.
      const target = visible.find(mark => !mark.closest("a,button,input,select,textarea") && !mark.querySelector("a,button,input,select,textarea"));
      if (!target) continue;
      target.classList.add("qr-change-target");
      target.tabIndex = 0;
      target.setAttribute("role", "button");
      target.setAttribute("aria-label", `Inspect tracked change: ${target.title}`);
      target.setAttribute("aria-controls", "qr-context-panel");
      interactiveMarks.add(target);
    }
    for (const [block, content] of blockContents) {
      // Remove empty space left by non-selected deletions, but keep a passage
      // carrying a matching point marker, including a nested suggestion.
      const empty = Boolean(focus) && content.length > 0 && content.every(node => node.parentElement.closest(".qr-author-hidden"));
      block.classList.toggle("qr-author-empty", empty && ![...block.querySelectorAll(".qr-link")].some(link => !link.hidden));
    }
    for (const mark of scope.querySelectorAll(".qr-comment")) {
      mark.classList.toggle("qr-comment-muted", !commentsVisible || !mark.dataset.reviewIds.split(" ").some(id => {
        const item = itemById.get(id);
        return item?.dataset.kind === "comment" && !item.hidden;
      }));
    }
    for (const block of scope.querySelectorAll(".qr-annotation-only-block")) {
      block.classList.toggle("qr-empty-annotation", ![...block.querySelectorAll(".qr-link")].some(link => !link.hidden));
    }
    const count = (records, label) => {
      const n = records.filter(item => !item.hidden).length;
      return `${n} ${label}${n === 1 ? "" : "s"}`;
    };
    const counts = [];
    if (kind.value !== "suggestion") counts.push(count(threads, "comment"));
    if (kind.value !== "comment") counts.push(count(suggestions, "change"));
    controls.querySelector("#qr-count").textContent = counts.join(", ");
    if (paneView === "list") {
      for (const group of groups.values()) if (group.inline) group.inline.hidden = true;
      renderList();
    } else if (mode === "inline") renderInline();
    else showGroup(selectedGroup, true);
    scheduleFollow();
  }
  function readingLine() {
    return Math.max(Math.min(innerHeight * .36, 320), controlsVisible ? controls.getBoundingClientRect().bottom + 16 : 32);
  }
  function keepReadingPosition(action) {
    const line = readingLine();
    const passage = scrollY > 2 ? [...scope.querySelectorAll("p,h1,h2,h3,h4,h5,h6,figure,table")].find(node => {
      if (!inContent(node)) return false;
      if (node.closest(".qr-controls,.qr-panel,.qr-inline-comments")) return false;
      const box = node.getBoundingClientRect();
      return box.height && box.bottom > line && box.top < innerHeight;
    }) : null;
    const previousTop = passage?.getBoundingClientRect().top;
    const selected = selectionScrollY !== null && Math.abs(scrollY - selectionScrollY) < 1;
    action();
    if (passage?.getClientRects().length) {
      const shift = passage.getBoundingClientRect().top - previousTop;
      if (Math.abs(shift) > 1) window.scrollBy({top: shift, behavior: "instant"});
    }
    if (selected) selectionScrollY = scrollY;
  }
  function setVisibility(showControls, showComments) {
    const focusWasInControls = controls.contains(document.activeElement);
    const focusWasInComments = dock.contains(document.activeElement) || panel.contains(document.activeElement) || Boolean(document.activeElement?.closest(".qr-inline-comments"));
    keepReadingPosition(() => {
      controlsVisible = showControls;
      commentsVisible = showComments;
      controls.hidden = !showControls;
      panel.hidden = !showComments;
      restore.hidden = showControls;
      restore.textContent = showComments ? "Show controls" : "Show review";
      restore.title = showComments ? "Show review controls" : "Restore review controls, cards, and your previous text view";
      toggleComments.textContent = showComments ? "Hide review cards" : "Show review cards";
      toggleComments.setAttribute("aria-expanded", String(showComments));
      update();
      layout();
    });
    if (!showControls && (focusWasInControls || !showComments && focusWasInComments)) restore.focus({preventScroll: true});
    else if (!showComments && focusWasInComments) toggleComments.focus({preventScroll: true});
  }
  function navigate(direction) {
    const ordered = orderedItems.filter(item => paneView === "list" || anchors.has(item.dataset.reviewId));
    const available = ordered.filter(item => !item.hidden);
    if (!available.length) return;
    const origin = ordered.findIndex(item => item.dataset.reviewId === currentId);
    const candidates = direction > 0 ? available : [...available].reverse();
    if (paneView === "list") {
      const next = candidates.find(item => origin >= 0 && direction * (ordered.indexOf(item) - origin) > 0) || candidates[0];
      const entry = [...dockContent.querySelectorAll(".qr-list-entry")].find(node => node.dataset.reviewId === next.dataset.reviewId);
      currentId = next.dataset.reviewId;
      entry.open = true;
      const top = entry.getBoundingClientRect().top - dockContent.getBoundingClientRect().top;
      dockContent.scrollTop += top;
      entry.querySelector("summary").focus({preventScroll: true});
      return;
    }
    const next = candidates.find(item => origin >= 0
      ? direction * (ordered.indexOf(item) - origin) > 0
      : direction * (groupById.get(item.dataset.reviewId).passage.getBoundingClientRect().top - readingLine()) >= 0
    ) || candidates[0];
    const id = next.dataset.reviewId;
    anchors.get(id).scrollIntoView({block: "center", behavior: "instant"});
    showComment(id);
  }
  function showComment(id) {
    if (paneView === "list") return;
    showGroup(groupById.get(id));
    currentId = id;
    selectionScrollY = scrollY;
    if (mode !== "margin" || !commentsVisible) return;
    const card = dockContent.querySelector(`[data-review-id="${id}"]`);
    if (!card) return;
    const box = card.getBoundingClientRect();
    const viewport = dockContent.getBoundingClientRect();
    if (box.top < viewport.top || box.bottom > viewport.bottom) {
      dockContent.scrollTop += box.top - viewport.top;
    }
  }
  function commentAt(target) {
    const link = target.closest(".qr-link");
    if (link && !link.hidden) return link.dataset.qrTarget;
    const mark = target.closest(".qr-mark");
    return items.find(item => !item.hidden && groupById.has(item.dataset.reviewId) && mark?.dataset.reviewIds.split(" ").includes(item.dataset.anchorId || item.dataset.reviewId))?.dataset.reviewId;
  }
  // React to pointer movement, not a stationary pointer re-entering text when
  // filtering changes the layout underneath it.
  for (const event of ["pointermove", "focusin"]) scope.addEventListener(event, e => {
    const id = commentAt(e.target);
    if (id && id !== currentId) showComment(id);
  });
  document.addEventListener("click", event => {
    const link = event.target.closest('a[data-qr-target]');
    if (!link) {
      const target = event.target.closest(".qr-change-target");
      if (target && !event.target.closest("a,button,input,select,textarea")) {
        const id = commentAt(target);
        if (id) showComment(id);
      }
      return;
    }
    const id = link.dataset.qrTarget;
    if (!groupById.has(id)) return;
    event.preventDefault();
    event.stopPropagation();
    if (link.closest(".qr-index,.qr-card")) anchors.get(id).scrollIntoView({block: "center", behavior: "instant"});
    showComment(id);
  }, true);
  scope.addEventListener("keydown", event => {
    if (!["Enter", " "].includes(event.key) || !event.target.matches(".qr-change-target")) return;
    const id = commentAt(event.target);
    if (!id) return;
    event.preventDefault();
    showComment(id);
  });
  for (const element of [view, kind, author, status]) element.addEventListener("change", () => {
    keepReadingPosition(update);
  });
  controls.querySelector("#qr-next").addEventListener("click", () => navigate(1));
  controls.querySelector("#qr-previous").addEventListener("click", () => navigate(-1));
  window.addEventListener("scroll", scheduleFollow, {passive: true});
  window.addEventListener("resize", () => { layout(); scheduleFollow(); }, {passive: true});
  new ResizeObserver(layout).observe(root);
  toggleComments.setAttribute("aria-expanded", "true");
  update();
  layout();
});
