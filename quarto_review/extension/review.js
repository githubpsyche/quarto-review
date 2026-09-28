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
  const active = new Map();
  const items = [...panel.querySelectorAll(".qr-thread,.qr-suggestion")];
  const threads = items.filter(node => node.classList.contains("qr-thread"));
  const suggestions = items.filter(node => node.classList.contains("qr-suggestion"));
  const itemById = new Map(items.map(node => [node.dataset.reviewId, node]));
  const marksById = new Map();
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
    const math = node.nodeType === Node.ELEMENT_NODE && node.classList.contains("math");
    const text = node.nodeType === Node.TEXT_NODE && node.textContent.length > 0;
    if ((!math && !text) || active.size === 0) continue;
    if (node.parentElement?.closest(".math,script,style,.qr-panel,.qr-controls")) continue;
    const span = document.createElement("span");
    const entries = [...active.values()];
    span.classList.add("qr-mark");
    if (entries.some(item => item.kind === "I")) span.classList.add("qr-insert");
    if (entries.some(item => item.kind === "D")) span.classList.add("qr-delete");
    if (entries.some(item => item.kind === "C")) span.classList.add("qr-comment");
    span.dataset.reviewIds = entries.map(item => item.id).join(" ");
    for (const {id} of entries) {
      if (!marksById.has(id)) marksById.set(id, []);
      marksById.get(id).push(span);
    }
    node.replaceWith(span);
    span.append(node);
  }
  // Even an accepted deletion has a point anchor. Give it a discoverable
  // marker when changes are selected, without restoring its deleted prose.
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
    const content = [];
    while (textWalker.nextNode()) {
      if (textWalker.currentNode.textContent.trim() && !textWalker.currentNode.parentElement.closest(".qr-link")) content.push(textWalker.currentNode);
    }
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
  const readingButton = button("Reading view", "qr-reading-view", () => setVisibility(false, false));
  readingButton.title = "Hide review controls and cards; show clean proposed text";
  const hideControls = button("Hide controls", "qr-hide-controls", () => setVisibility(false, commentsVisible));
  hideControls.setAttribute("aria-controls", "qr-controls");
  toolbarHeading.append(toolbarTitle, toggleComments, readingButton, hideControls);
  controls.prepend(toolbarHeading);
  const restore = button("Show review", "qr-restore-review", () => {
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
  const dockHeading = document.createElement("h2");
  dockHeading.textContent = "Review of this passage";
  const dockHint = document.createElement("p");
  dockHint.className = "qr-context-hint";
  dockHint.textContent = "Follows the text as you read. Use Next to reach a matching comment or change. Δ marks a change location.";
  const dockNavigation = document.createElement("nav");
  dockNavigation.setAttribute("aria-label", "Comment navigation");
  for (const [label, direction] of [["Previous review item", -1], ["Next review item", 1]]) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = direction < 0 ? "Previous" : "Next";
    button.setAttribute("aria-label", label + " beside text");
    button.addEventListener("click", () => navigate(direction));
    dockNavigation.append(button);
  }
  const dockContent = document.createElement("div");
  dockContent.className = "qr-context-content";
  const dockTitle = document.createElement("div");
  dockTitle.className = "qr-dock-heading";
  const hideComments = button("Hide", "qr-hide-comments", () => setVisibility(controlsVisible, false));
  hideComments.setAttribute("aria-label", "Hide comments");
  hideComments.setAttribute("aria-controls", "qr-context-panel quarto-review");
  dockTitle.append(dockHeading, hideComments);
  dock.append(dockTitle, dockHint, dockNavigation, dockContent);
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
    const wording = excluded => marks.filter(mark => !mark.classList.contains(excluded))
      .map(mark => mark.textContent).join("").replace(/\s+/g, " ").trim();
    const original = wording("qr-insert");
    const proposed = wording("qr-delete");
    const shorten = text => text.length > 360 ? text.slice(0, 357) + "…" : text;
    const textView = document.body.dataset.reviewView;
    if (textView === "review" && original !== proposed) {
      for (const [label, text] of [["Original", original], ["Proposed", proposed]]) {
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
  function showGroup(group, force = false) {
    const ids = group ? matching(group) : [];
    if (selectedGroup !== group) currentId = ids[0] || group?.ids[0] || null;
    selectedGroup = group;
    if (mode !== "margin" || !commentsVisible) return;
    const key = ids.join(" ");
    if (!force && key === selectedIds) return;
    selectedIds = key;
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
    if (!commentsVisible) {
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
    const nextMode = side ? "margin" : "inline";
    dock.hidden = !commentsVisible || nextMode !== "margin";
    if (side) {
      const width = Math.min(360, side === "right" ? right : left);
      dock.style.width = `${width}px`;
      dock.style.left = `${side === "right" ? box.right + 16 : box.left - width - 16}px`;
    }
    if (mode === nextMode) return;
    mode = nextMode;
    document.body.dataset.reviewComments = mode;
    if (mode === "inline") {
      dockContent.replaceChildren();
      selectedIds = "";
      renderInline();
    } else {
      for (const group of groups.values()) { group.inline?.remove(); group.inline = null; }
      selectedIds = "";
      showGroup(selectedGroup, true);
      scheduleFollow();
    }
  }
  function update() {
    const clean = !controlsVisible && !commentsVisible;
    document.body.dataset.reviewClean = String(clean);
    document.body.dataset.reviewControlsVisible = String(controlsVisible);
    document.body.dataset.reviewCommentsVisible = String(commentsVisible);
    document.body.dataset.reviewView = clean ? "proposed" : view.value;
    for (const option of status.options) {
      option.hidden = option.disabled = Boolean(kind.value && option.dataset.kind && option.dataset.kind !== kind.value);
    }
    if (status.selectedOptions[0]?.disabled) status.value = "";
    for (const item of items) {
      item.hidden = Boolean(
        kind.value && kind.value !== item.dataset.kind ||
        author.value && !item.dataset.author.split("\n").includes(author.value) ||
        status.value && status.value !== item.dataset.status
      );
    }
    for (const [mark, attribution] of attributions) {
      if (clean) mark.removeAttribute("title");
      else mark.title = attribution;
    }
    // Filters select review records, not manuscript wording or redline colour.
    for (const link of links) link.hidden = !commentsVisible || clean || itemById.get(link.dataset.qrTarget).hidden;
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
    controls.querySelector("#qr-count").textContent = `${count(threads, "comment")}, ${count(suggestions, "change")} shown`;
    if (mode === "inline") renderInline();
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
    const ordered = items.filter(item => anchors.has(item.dataset.reviewId)).sort((a, b) => {
      const order = anchors.get(a.dataset.reviewId).compareDocumentPosition(anchors.get(b.dataset.reviewId));
      return order & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : order & Node.DOCUMENT_POSITION_PRECEDING ? 1 : 0;
    });
    const available = ordered.filter(item => !item.hidden);
    if (!available.length) return;
    const origin = ordered.findIndex(item => item.dataset.reviewId === currentId);
    const candidates = direction > 0 ? available : [...available].reverse();
    const next = candidates.find(item => origin >= 0
      ? direction * (ordered.indexOf(item) - origin) > 0
      : direction * (groupById.get(item.dataset.reviewId).passage.getBoundingClientRect().top - readingLine()) >= 0
    ) || candidates[0];
    const id = next.dataset.reviewId;
    anchors.get(id).scrollIntoView({block: "center", behavior: "instant"});
    showComment(id);
  }
  function showComment(id) {
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
    if (!link) return;
    const id = link.dataset.qrTarget;
    if (!groupById.has(id)) return;
    event.preventDefault();
    event.stopPropagation();
    if (link.closest(".qr-index,.qr-card")) anchors.get(id).scrollIntoView({block: "center", behavior: "instant"});
    showComment(id);
  }, true);
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
