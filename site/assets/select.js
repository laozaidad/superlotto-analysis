/** 原生select保留值与表单语义；无JS时仍可用，有JS时增强为可访问的自定义菜单。 */
/** @typedef {{select:HTMLSelectElement,trigger:HTMLButtonElement,refresh:()=>void,destroy:()=>void}} SelectControl */
/** @type {WeakMap<HTMLSelectElement, SelectControl>} */
const controls = new WeakMap();
let nextId = 0;

/** @param {Document|Element} [root] @returns {SelectControl[]} */
export function initCustomSelects(root = document) {
  return [...root.querySelectorAll("select[data-custom-select]")].map(
    (element) => {
      const select = /** @type {HTMLSelectElement} */ (element);
      return controls.get(select) || enhanceSelect(select);
    },
  );
}

/** @param {HTMLSelectElement} select @returns {SelectControl} */
function enhanceSelect(select) {
  const doc = select.ownerDocument,
    win = /** @type {Window & typeof globalThis} */ (doc.defaultView);
  if (!win) throw new Error("选择器缺少浏览器窗口");
  if (select.multiple) throw new Error("自定义选择器仅支持单选");
  if (!select.id) select.id = `custom-select-${++nextId}`;
  const previousHidden = select.hidden,
    previousTabIndex = select.getAttribute("tabindex"),
    previousAriaHidden = select.getAttribute("aria-hidden");
  const labels = [...(select.labels || [])].map((label, index) => ({
    label,
    id: label.id,
    htmlFor: label.htmlFor,
    generatedId: `${select.id}-label-${index + 1}`,
  }));
  const wrapper = doc.createElement("div");
  wrapper.className = "select-field";
  if (select.dataset.selectSize)
    wrapper.dataset.selectSize = select.dataset.selectSize;
  const trigger = doc.createElement("button");
  trigger.type = "button";
  trigger.className = "select-trigger";
  trigger.id = `${select.id}-control`;
  trigger.setAttribute("role", "combobox");
  trigger.setAttribute("aria-haspopup", "listbox");
  trigger.setAttribute("aria-expanded", "false");
  const value = doc.createElement("span");
  value.className = "select-value";
  value.id = `${select.id}-value`;
  const chevron = doc.createElement("span");
  chevron.className = "select-chevron";
  chevron.setAttribute("aria-hidden", "true");
  trigger.append(value, chevron);
  const popup = doc.createElement("div");
  popup.className = "select-popup";
  popup.id = `${select.id}-listbox`;
  popup.setAttribute("role", "listbox");
  popup.hidden = true;
  trigger.setAttribute("aria-controls", popup.id);
  if (labels.length) {
    labels.forEach(({ label, generatedId }) => {
      if (!label.id) label.id = generatedId;
      label.htmlFor = trigger.id;
    });
    const ids = labels.map(({ label }) => label.id).join(" ");
    trigger.setAttribute("aria-labelledby", ids);
    popup.setAttribute("aria-labelledby", ids);
  } else {
    const label =
      select.getAttribute("aria-label") || select.name || "选择选项";
    trigger.setAttribute("aria-label", label);
    popup.setAttribute("aria-label", label);
  }
  const describedBy = select.getAttribute("aria-describedby");
  if (describedBy) trigger.setAttribute("aria-describedby", describedBy);
  if (select.required) trigger.setAttribute("aria-required", "true");
  select.before(wrapper);
  wrapper.append(select, trigger, popup);
  select.hidden = true;
  select.tabIndex = -1;
  select.setAttribute("aria-hidden", "true");
  /** @type {HTMLOptionElement[]} */ let options = [];
  /** @type {HTMLElement[]} */ let items = [];
  let open = false,
    active = -1,
    search = "",
    lastTyped = 0,
    destroyed = false;
  /** @param {number} index */
  function enabled(index) {
    const option = options[index];
    const group = option?.parentElement;
    return (
      !!option &&
      !option.disabled &&
      !option.hidden &&
      !(
        group?.tagName === "OPTGROUP" &&
        (group.hasAttribute("disabled") || group.hidden)
      )
    );
  }
  function enabledIndexes() {
    return options.map((_, index) => index).filter(enabled);
  }
  /** @param {HTMLOptionElement|undefined} option */
  function optionLabel(option) {
    return option ? option.getAttribute("label") || option.text.trim() : "";
  }
  function currentIndex() {
    return options.findIndex((option) => option.selected);
  }
  /** @param {number} index @param {boolean} [scroll] */
  function setActive(index, scroll = true) {
    active = enabled(index) ? index : -1;
    items.forEach((item, i) =>
      item.classList.toggle("is-active", open && i === active),
    );
    if (open && active >= 0) {
      trigger.setAttribute("aria-activedescendant", items[active].id);
      if (scroll) {
        const item = items[active],
          top = item.offsetTop,
          bottom = top + item.offsetHeight;
        if (top < popup.scrollTop) popup.scrollTop = top;
        else if (bottom > popup.scrollTop + popup.clientHeight)
          popup.scrollTop = Math.max(0, bottom - popup.clientHeight);
      }
    } else trigger.removeAttribute("aria-activedescendant");
  }
  function position() {
    if (!open || !win) return;
    const rect = trigger.getBoundingClientRect(),
      parent = wrapper.getBoundingClientRect();
    const viewport = win.visualViewport;
    const top = viewport?.offsetTop || 0,
      left = viewport?.offsetLeft || 0;
    const height = viewport?.height || win.innerHeight,
      width = viewport?.width || win.innerWidth;
    if (
      rect.bottom < top ||
      rect.top > top + height ||
      rect.right < left ||
      rect.left > left + width
    ) {
      close(false);
      return;
    }
    const gap = 8,
      margin = 16,
      below = Math.max(0, top + height - rect.bottom - gap - margin),
      above = Math.max(0, rect.top - top - gap - margin);
    const desired = Math.min(popup.scrollHeight || 280, 340);
    const upward = below < Math.min(desired, 160) && above > below;
    wrapper.dataset.placement = upward ? "top" : "bottom";
    popup.style.maxHeight = `${Math.min(340, upward ? above : below)}px`;
    const popupWidth = Math.min(
      Math.max(rect.width, select.dataset.selectSize === "compact" ? 210 : 260),
      Math.max(0, width - margin * 2),
    );
    popup.style.width = `${popupWidth}px`;
    const popupLeft = Math.max(
      left + margin,
      Math.min(rect.left, left + width - margin - popupWidth),
    );
    popup.style.left = `${popupLeft - parent.left}px`;
    popup.style.top = upward ? "auto" : `${rect.bottom - parent.top + gap}px`;
    popup.style.bottom = upward
      ? `${parent.bottom - rect.top + gap}px`
      : "auto";
  }
  function updateSelection() {
    value.textContent = optionLabel(options[currentIndex()]) || "请选择";
    items.forEach((item, index) =>
      item.setAttribute("aria-selected", String(index === currentIndex())),
    );
  }
  function commit() {
    if (!enabled(active) || trigger.disabled || select.disabled) return;
    const changed = currentIndex() !== active;
    select.selectedIndex = active;
    updateSelection();
    if (changed) {
      select.dispatchEvent(new win.Event("input", { bubbles: true }));
      select.dispatchEvent(new win.Event("change", { bubbles: true }));
    }
  }
  /** @param {boolean} apply @param {boolean} [focus] */
  function close(apply, focus = false) {
    if (!open) return;
    if (apply) commit();
    open = false;
    popup.hidden = true;
    wrapper.classList.remove("is-open");
    trigger.setAttribute("aria-expanded", "false");
    search = "";
    setActive(-1, false);
    if (focus && !trigger.disabled) trigger.focus({ preventScroll: true });
  }
  function show() {
    refreshState();
    if (trigger.disabled || open) return;
    open = true;
    popup.hidden = false;
    wrapper.classList.add("is-open");
    trigger.setAttribute("aria-expanded", "true");
    setActive(
      enabled(currentIndex()) ? currentIndex() : (enabledIndexes()[0] ?? -1),
      false,
    );
    position();
    setActive(active);
    trigger.focus({ preventScroll: true });
  }
  function refreshState() {
    trigger.disabled = select.disabled || !enabledIndexes().length;
    wrapper.classList.toggle("is-disabled", trigger.disabled);
    trigger.setAttribute("aria-disabled", String(trigger.disabled));
    if (trigger.disabled) close(false);
    updateSelection();
  }
  function rebuild() {
    options = [...select.options];
    items = [];
    popup.replaceChildren();
    options.forEach((option, index) => {
      const item = doc.createElement("div");
      item.className = "select-option";
      item.id = `${select.id}-option-${index}`;
      item.setAttribute("role", "option");
      item.dataset.index = String(index);
      item.hidden =
        option.hidden ||
        (option.parentElement?.tagName === "OPTGROUP" &&
          option.parentElement.hidden);
      item.setAttribute("aria-disabled", String(!enabled(index)));
      const title = doc.createElement("span");
      title.className = "select-option-title";
      title.textContent = optionLabel(option);
      const description = doc.createElement("span");
      description.className = "select-option-description";
      description.textContent = option.dataset.description || "";
      description.hidden = !description.textContent;
      const check = doc.createElement("span");
      check.className = "select-check";
      check.setAttribute("aria-hidden", "true");
      check.textContent = "✓";
      item.append(title, description, check);
      popup.append(item);
      items.push(item);
    });
    refreshState();
    if (open) {
      setActive(enabled(active) ? active : currentIndex());
      position();
    }
  }
  function sync() {
    refreshState();
    if (open) setActive(currentIndex());
  }
  /** @param {KeyboardEvent} event */
  function onKey(event) {
    if (trigger.disabled || select.disabled || event.isComposing) return;
    const key = event.key,
      indices = enabledIndexes();
    if (key === "Tab") {
      close(true);
      return;
    }
    if (key === "Escape") {
      if (open) {
        event.preventDefault();
        close(false, true);
      }
      return;
    }
    if (key === "Enter" || key === " ") {
      event.preventDefault();
      if (open) close(true, true);
      else show();
      return;
    }
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(key)) {
      event.preventDefault();
      const wasOpen = open;
      show();
      if (key === "Home" || (!wasOpen && key === "ArrowUp"))
        setActive(indices[0] ?? -1);
      else if (key === "End") setActive(indices.at(-1) ?? -1);
      else if (wasOpen)
        setActive(
          indices[
            Math.max(
              0,
              Math.min(
                indices.length - 1,
                indices.indexOf(active) + (key === "ArrowDown" ? 1 : -1),
              ),
            )
          ] ?? -1,
        );
      return;
    }
    if (key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      const now = Date.now();
      search = now - lastTyped > 700 ? key : search + key;
      lastTyped = now;
      show();
      const query = [...search].every(
        (char) => char.toLocaleLowerCase() === key.toLocaleLowerCase(),
      )
        ? key.toLocaleLowerCase()
        : search.toLocaleLowerCase();
      const start = Math.max(0, indices.indexOf(active));
      const ordered =
        query.length === 1
          ? [...indices.slice(start + 1), ...indices.slice(0, start + 1)]
          : [...indices.slice(start), ...indices.slice(0, start)];
      const match = ordered.find((index) =>
        optionLabel(options[index]).toLocaleLowerCase().startsWith(query),
      );
      if (match !== undefined) setActive(match);
    }
  }
  function onTrigger() {
    if (open) close(false, true);
    else show();
  }
  /** @param {MouseEvent} event */
  function onPopupClick(event) {
    const target = /** @type {Element|null} */ (event.target);
    const item = target?.closest('[role="option"]');
    if (!item || !popup.contains(item)) return;
    const index = Number(/** @type {HTMLElement} */ (item).dataset.index);
    if (enabled(index)) {
      setActive(index, false);
      close(true, true);
    }
  }
  /** @param {MouseEvent} event */
  function keepFocus(event) {
    event.preventDefault();
  }
  /** @param {PointerEvent} event */
  function onOutside(event) {
    if (
      open &&
      event.target instanceof win.Node &&
      !wrapper.contains(event.target)
    )
      close(true);
  }
  function onFocusOut() {
    queueMicrotask(() => {
      if (!destroyed && open && !wrapper.contains(doc.activeElement))
        close(true);
    });
  }
  /** @param {Event} event */
  function onScroll(event) {
    if (
      open &&
      !(event.target instanceof win.Node && popup.contains(event.target))
    )
      position();
  }
  function onReset() {
    queueMicrotask(() => {
      if (!destroyed) {
        close(false);
        sync();
      }
    });
  }
  trigger.addEventListener("click", onTrigger);
  trigger.addEventListener("keydown", onKey);
  trigger.addEventListener("blur", onFocusOut);
  popup.addEventListener("click", onPopupClick);
  popup.addEventListener("mousedown", keepFocus);
  select.addEventListener("input", sync);
  select.addEventListener("change", sync);
  doc.addEventListener("pointerdown", onOutside);
  win.addEventListener("scroll", onScroll, true);
  win.addEventListener("resize", position);
  win.visualViewport?.addEventListener("resize", position);
  win.visualViewport?.addEventListener("scroll", position);
  const form = select.form;
  form?.addEventListener("reset", onReset);
  const observer = new win.MutationObserver(rebuild);
  observer.observe(select, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: [
      "disabled",
      "selected",
      "label",
      "hidden",
      "data-description",
    ],
  });
  rebuild();
  const control = {
    select,
    trigger,
    refresh: rebuild,
    destroy() {
      close(false);
      destroyed = true;
      observer.disconnect();
      select.removeEventListener("input", sync);
      select.removeEventListener("change", sync);
      doc.removeEventListener("pointerdown", onOutside);
      win.removeEventListener("scroll", onScroll, true);
      win.removeEventListener("resize", position);
      win.visualViewport?.removeEventListener("resize", position);
      win.visualViewport?.removeEventListener("scroll", position);
      form?.removeEventListener("reset", onReset);
      labels.forEach(({ label, id, htmlFor }) => {
        label.id = id;
        label.htmlFor = htmlFor;
      });
      select.hidden = previousHidden;
      if (previousTabIndex === null) select.removeAttribute("tabindex");
      else select.setAttribute("tabindex", previousTabIndex);
      if (previousAriaHidden === null) select.removeAttribute("aria-hidden");
      else select.setAttribute("aria-hidden", previousAriaHidden);
      wrapper.before(select);
      wrapper.remove();
      controls.delete(select);
    },
  };
  controls.set(select, control);
  return control;
}
