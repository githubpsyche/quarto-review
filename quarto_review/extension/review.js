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
  const threadById = new Map(threads.map(node => [node.dataset.reviewId, node]));
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
        if (kind === "C" && threadById.has(id)) {
          const link = document.createElement("a");
          link.className = "qr-link";
          link.href = `#qr-thread-${id}`;
          link.textContent = id;
          link.dataset.commentId = id;
          link.setAttribute("aria-label", `Read comment ${id} beside this passage`);
          link.setAttribute("aria-controls", "qr-context-panel");
          node.after(link);
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
  const toggleComments = button("Hide comments", "qr-toggle-comments", () => setVisibility(controlsVisible, !commentsVisible));
  toggleComments.setAttribute("aria-controls", "qr-context-panel quarto-review");
  const readingButton = button("Reading view", "qr-reading-view", () => setVisibility(false, false));
  readingButton.title = "Hide review controls and comments; show clean proposed text";
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
  dock.setAttribute("aria-label", "Comments beside the passage");
  const dockHeading = document.createElement("h2");
  dockHeading.textContent = "Comments on this passage";
  const dockHint = document.createElement("p");
  dockHint.className = "qr-context-hint";
  dockHint.textContent = "Follows the text as you read. Hover over a marked passage to see its comments.";
  const dockNavigation = document.createElement("nav");
  dockNavigation.setAttribute("aria-label", "Comment navigation");
  for (const [label, direction] of [["Previous comment", -1], ["Next comment", 1]]) {
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
  for (const thread of threads) {
    const id = thread.dataset.reviewId;
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
  let current = -1;
  let frame = 0;
  const visiblePassages = new Set();
  const matching = group => group.ids.filter(id => !threadById.get(id).hidden);

  function makeCard(id) {
    const card = threadById.get(id).cloneNode(true);
    card.classList.remove("qr-thread");
    card.classList.add("qr-card");
    card.hidden = false;
    card.id = `qr-context-${id}`;
    for (const element of card.querySelectorAll("[id]")) element.removeAttribute("id");
    const excerpt = document.createElement("blockquote");
    excerpt.className = "qr-context-quote";
    const marks = marksById.get(id) || [];
    const text = marks.filter(mark => mark.getClientRects().length).map(mark => mark.innerText).join("").replace(/\s+/g, " ").trim();
    excerpt.textContent = text ? (text.length > 360 ? text.slice(0, 357) + "…" : text) : "At this point in the text";
    card.insertBefore(excerpt, card.querySelector(".qr-body"));
    return card;
  }
  function showGroup(group, force = false) {
    if (mode !== "margin" || !commentsVisible) return;
    const ids = group ? matching(group) : [];
    const key = ids.join(" ");
    if (!force && key === selectedIds) return;
    selectedGroup = group;
    selectedIds = key;
    dockContent.replaceChildren(...ids.map(makeCard));
    dockContent.scrollTop = 0;
    if (!ids.length) {
      const empty = document.createElement("p");
      empty.className = "qr-context-empty";
      empty.textContent = "Comments appear here when an annotated passage is on screen.";
      dockContent.append(empty);
    }
  }
  function followPassage() {
    if (mode !== "margin" || !commentsVisible) return;
    const line = Math.min(innerHeight * .36, 320);
    let nearest = null;
    let distance = Infinity;
    for (const passage of visiblePassages) {
      const group = groups.get(passage);
      if (!matching(group).length) continue;
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
        group.inline.setAttribute("aria-label", "Comments on the preceding passage");
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
    const visible = new Set();
    for (const item of items) {
      const match = (!author.value || item.dataset.author.split("\n").includes(author.value)) && (!status.value || status.value === item.dataset.status);
      item.hidden = !match;
      if (match) {
        visible.add(item.dataset.reviewId);
        if (item.dataset.anchorId) visible.add(item.dataset.anchorId);
      }
    }
    for (const mark of scope.querySelectorAll(".qr-mark")) mark.classList.toggle("qr-filtered", Boolean(author.value || status.value) && !mark.dataset.reviewIds.split(" ").some(id => visible.has(id)));
    controls.querySelector("#qr-count").textContent = `${threads.filter(item => !item.hidden).length} comments shown`;
    current = -1;
    if (mode === "inline") renderInline();
    else showGroup(selectedGroup, true);
    scheduleFollow();
  }
  function setVisibility(showControls, showComments) {
    // Hold the passage in place when a toolbar or in-flow comments disappear.
    const readingLine = Math.max(32, controlsVisible ? controls.getBoundingClientRect().bottom + 16 : 32);
    const passage = scrollY > 2 ? [...scope.querySelectorAll("p,h1,h2,h3,h4,h5,h6,figure,table")].find(node => {
      if (!inContent(node)) return false;
      if (node.closest(".qr-controls,.qr-panel,.qr-inline-comments")) return false;
      const box = node.getBoundingClientRect();
      return box.height && box.bottom > readingLine && box.top < innerHeight;
    }) : null;
    const previousTop = passage?.getBoundingClientRect().top;
    const focusWasInControls = controls.contains(document.activeElement);
    const focusWasInComments = dock.contains(document.activeElement) || panel.contains(document.activeElement) || Boolean(document.activeElement?.closest(".qr-inline-comments"));
    controlsVisible = showControls;
    commentsVisible = showComments;
    controls.hidden = !showControls;
    panel.hidden = !showComments;
    restore.hidden = showControls;
    restore.textContent = showComments ? "Show controls" : "Show review";
    restore.title = showComments ? "Show review controls" : "Restore review controls, comments, and your previous text view";
    toggleComments.textContent = showComments ? "Hide comments" : "Show comments";
    toggleComments.setAttribute("aria-expanded", String(showComments));
    update();
    layout();
    if (passage?.getClientRects().length) {
      const shift = passage.getBoundingClientRect().top - previousTop;
      if (Math.abs(shift) > 1) window.scrollBy({top: shift, behavior: "instant"});
    }
    if (!showControls && (focusWasInControls || !showComments && focusWasInComments)) restore.focus({preventScroll: true});
    else if (!showComments && focusWasInComments) toggleComments.focus({preventScroll: true});
  }
  function navigate(direction) {
    const available = threads.filter(item => !item.hidden && anchors.has(item.dataset.reviewId));
    if (!available.length) return;
    current = current < 0 ? (direction > 0 ? 0 : available.length - 1) : (current + direction + available.length) % available.length;
    const id = available[current].dataset.reviewId;
    anchors.get(id).scrollIntoView({block: "center"});
    showGroup(groupById.get(id));
  }
  function showComment(id) {
    showGroup(groupById.get(id));
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
    if (link) return link.dataset.commentId;
    const mark = target.closest(".qr-comment");
    return mark?.dataset.reviewIds.split(" ").find(id => groupById.has(id) && !threadById.get(id).hidden);
  }
  for (const event of ["pointerover", "focusin"]) scope.addEventListener(event, e => {
    const id = commentAt(e.target);
    if (id) showComment(id);
  });
  document.addEventListener("click", event => {
    const link = event.target.closest('a[href^="#qr-thread-"],.qr-card a[href^="#qr-anchor-"]');
    if (!link) return;
    const id = link.getAttribute("href").replace(/^#qr-(?:thread|anchor)-/, "");
    if (!groupById.has(id)) return;
    event.preventDefault();
    event.stopPropagation();
    if (link.closest(".qr-index,.qr-card")) anchors.get(id).scrollIntoView({block: "center"});
    showComment(id);
  }, true);
  for (const element of [view, author, status]) element.addEventListener("change", update);
  controls.querySelector("#qr-next").addEventListener("click", () => navigate(1));
  controls.querySelector("#qr-previous").addEventListener("click", () => navigate(-1));
  window.addEventListener("scroll", scheduleFollow, {passive: true});
  window.addEventListener("resize", () => { layout(); scheduleFollow(); }, {passive: true});
  new ResizeObserver(layout).observe(root);
  toggleComments.setAttribute("aria-expanded", "true");
  update();
  layout();
});
