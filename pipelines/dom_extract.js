// Reduced accessibility tree of the WHOLE page (not only the viewport) for the DOM pipeline.
// Called by pipelines/dom.py as page.evaluate(SCRIPT, epoch).
//
// Keeps: visible interactive elements (numbered refs) and visible text-bearing elements.
// Drops: hidden elements (display/visibility/opacity, aria-hidden subtrees, zero-size or
// 1px "visually hidden" boxes), decorative images (alt=""), <label> elements (their text
// becomes the name of the field), scripts/styles.
// Each interactive element gets the attribute data-agent-ref="<epoch>:<n>" so that the
// pipeline can find it again; refs from an older observation no longer match.
(epoch) => {
  document.querySelectorAll("[data-agent-ref]").forEach((e) => e.removeAttribute("data-agent-ref"));

  const INTERACTIVE = "a[href], button, input:not([type=hidden]), select, textarea";
  const GROUPS = new Set(["LI", "NAV", "FORM", "ASIDE", "SECTION", "HEADER", "FOOTER", "DL"]);
  const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "LABEL", "SVG", "svg"]);
  const out = [];
  let n = 0;

  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();

  function visible(el) {
    if (el.hidden || el.getAttribute("aria-hidden") === "true") return false;
    const st = getComputedStyle(el);
    if (st.display === "none" || st.visibility === "hidden" || parseFloat(st.opacity) === 0) return false;
    if (st.display === "contents") return true;
    const r = el.getBoundingClientRect();
    return r.width > 1 && r.height > 1;
  }

  function role(el) {
    const tag = el.tagName;
    if (tag === "A") return "link";
    if (tag === "BUTTON") return "button";
    if (tag === "SELECT") return "combobox";
    if (tag === "TEXTAREA") return "textbox";
    const type = (el.getAttribute("type") || "text").toLowerCase();
    if (["submit", "button", "reset"].includes(type)) return "button";
    return { search: "searchbox", number: "spinbutton", checkbox: "checkbox", radio: "radio" }[type] || "textbox";
  }

  function name(el) {
    if (el.getAttribute("aria-label")) return clean(el.getAttribute("aria-label"));
    if (el.labels && el.labels.length) return clean(el.labels[0].textContent);
    if (el.tagName === "INPUT" && ["submit", "button"].includes(el.type)) return clean(el.value);
    return clean(el.textContent);
  }

  function walk(el, depth) {
    if (SKIP.has(el.tagName) || !visible(el)) return;
    if (el.matches(INTERACTIVE)) {
      n += 1;
      el.setAttribute("data-agent-ref", epoch + ":" + n);
      const item = { ref: n, role: role(el), name: name(el), depth };
      if (["INPUT", "TEXTAREA"].includes(el.tagName) && !["submit", "button"].includes(el.type)) item.value = el.value;
      if (el.getAttribute("aria-current")) item.current = true;
      out.push(item);
      return;
    }
    if (/^H[1-6]$/.test(el.tagName) && !el.querySelector(INTERACTIVE)) {
      out.push({ role: "heading", name: clean(el.textContent), depth });
      return;
    }
    const childDepth = GROUPS.has(el.tagName) ? depth + 1 : depth;
    const start = out.length;
    for (const child of el.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) {
        const text = clean(child.textContent);
        if (text) out.push({ role: "text", name: text, depth });
      } else if (child.nodeType === Node.ELEMENT_NODE) {
        walk(child, childDepth);
      }
    }
    // A list item with several elements (product card, cart line) gets a marker line, so that
    // the boundaries between items are visible in the text; single-link items stay compact.
    if (el.tagName === "LI" && out.length - start > 1) out.splice(start, 0, { role: "listitem", name: "", depth });
  }

  walk(document.body, 0);
  return out;
}
