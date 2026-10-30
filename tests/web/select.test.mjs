import test, { afterEach } from "node:test";
import assert from "node:assert/strict";
import { Window } from "happy-dom";
import { initCustomSelects } from "../../site/assets/select.js";

const windows = [];
function fixture() {
  const window = new Window({
    url: "https://example.test/",
    width: 390,
    height: 844,
  });
  windows.push(window);
  const { document } = window;
  document.body.innerHTML = `<form id="form"><label for="strategy">策略</label>
    <select id="strategy" name="mode" data-custom-select aria-describedby="help">
      <option value="coverage" data-description="保持组间分散" selected>Coverage</option>
      <option value="uniform" data-description="均匀抽样基线">Uniform</option>
      <option value="unavailable" disabled>Unavailable</option>
      <option value="alternate">Alternative</option>
    </select><span id="help">选择策略</span><button id="outside" type="button">外部按钮</button>
    <button type="submit">提交</button></form>`;
  const controls = initCustomSelects(document);
  const select = document.querySelector("select"),
    trigger = document.querySelector(".select-trigger"),
    popup = document.querySelector(".select-popup");
  return {
    window,
    document,
    select,
    trigger,
    popup,
    controls,
    form: document.querySelector("form"),
    key(key, options = {}) {
      const event = new window.KeyboardEvent("keydown", {
        key,
        bubbles: true,
        cancelable: true,
        ...options,
      });
      trigger.dispatchEvent(event);
      return event;
    },
    async flush() {
      await window.happyDOM.waitUntilComplete();
      await Promise.resolve();
    },
  };
}
afterEach(async () => {
  for (const window of windows.splice(0)) {
    initCustomSelects(window.document).forEach((control) => control.destroy());
    await window.happyDOM.close();
  }
});

test("渐进增强保留表单值，隐藏原select，label和ARIA对应自定义控件", () => {
  const f = fixture();
  assert.equal(f.select.value, "coverage");
  assert.equal(f.select.hidden, true);
  assert.equal(f.select.tabIndex, -1);
  assert.equal(f.trigger.type, "button");
  assert.equal(f.trigger.id, "strategy-control");
  assert.equal(f.document.querySelector("label").htmlFor, f.trigger.id);
  assert.equal(f.trigger.getAttribute("role"), "combobox");
  assert.equal(f.popup.getAttribute("role"), "listbox");
  assert.equal(f.trigger.getAttribute("aria-expanded"), "false");
  assert.equal(f.popup.hidden, true);
  assert.equal(f.trigger.getAttribute("aria-describedby"), "help");
  assert.equal(
    f.popup.querySelector('[aria-selected="true"] .select-option-title')
      .textContent,
    "Coverage",
  );
  assert.equal(new f.window.FormData(f.form).get("mode"), "coverage");
});
test("点击选项更新原value且各冒泡一次input/change，不意外提交表单", () => {
  const f = fixture(),
    events = [];
  let submissions = 0;
  for (const name of ["input", "change"])
    f.form.addEventListener(name, (e) =>
      events.push([name, e.target.id, e.target.value]),
    );
  f.form.addEventListener("submit", (event) => {
    submissions++;
    event.preventDefault();
  });
  f.trigger.click();
  f.popup.querySelector('[data-index="1"] .select-option-title').click();
  assert.equal(f.select.value, "uniform");
  assert.deepEqual(events, [
    ["input", "strategy", "uniform"],
    ["change", "strategy", "uniform"],
  ]);
  assert.equal(f.trigger.querySelector(".select-value").textContent, "Uniform");
  assert.equal(f.popup.hidden, true);
  assert.equal(f.document.activeElement, f.trigger);
  assert.equal(submissions, 0);
  f.trigger.click();
  f.popup.querySelector('[data-index="1"]').click();
  assert.equal(events.length, 2);
});
test("上下键只预览；Esc取消不改旧值，保留触发器焦点", () => {
  const f = fixture();
  f.trigger.focus();
  f.key("ArrowDown");
  assert.equal(f.trigger.getAttribute("aria-expanded"), "true");
  assert.equal(f.select.value, "coverage");
  f.key("ArrowDown");
  assert.equal(
    f.trigger.getAttribute("aria-activedescendant"),
    "strategy-option-1",
  );
  assert.equal(f.select.value, "coverage");
  assert.equal(f.key("Escape").defaultPrevented, true);
  assert.equal(f.select.value, "coverage");
  assert.equal(f.popup.hidden, true);
  assert.equal(f.document.activeElement, f.trigger);
});
test("Home/End和方向键跳过禁用项，Enter/Space提交且不提交表单", () => {
  const f = fixture();
  let submissions = 0;
  f.form.addEventListener("submit", (e) => {
    submissions++;
    e.preventDefault();
  });
  f.key("End");
  assert.equal(
    f.trigger.getAttribute("aria-activedescendant"),
    "strategy-option-3",
  );
  f.key("ArrowUp");
  assert.equal(
    f.trigger.getAttribute("aria-activedescendant"),
    "strategy-option-1",
  );
  assert.equal(f.key("Enter").defaultPrevented, true);
  assert.equal(f.select.value, "uniform");
  f.key("Home");
  assert.equal(
    f.trigger.getAttribute("aria-activedescendant"),
    "strategy-option-0",
  );
  f.key(" ");
  assert.equal(f.select.value, "coverage");
  assert.equal(submissions, 0);
});
test("Tab提交当前预览但不阻止浏览器移动焦点；重复点击trigger取消预览", () => {
  const f = fixture();
  f.trigger.click();
  f.key("ArrowDown");
  assert.equal(f.key("Tab").defaultPrevented, false);
  assert.equal(f.select.value, "uniform");
  assert.equal(f.popup.hidden, true);
  f.trigger.click();
  f.key("End");
  f.trigger.click();
  assert.equal(f.select.value, "uniform");
  assert.equal(f.popup.hidden, true);
});
test("输入字符定位并重复按键循环匹配，不立即改变选中值", () => {
  const f = fixture();
  f.key("a");
  assert.equal(
    f.trigger.getAttribute("aria-activedescendant"),
    "strategy-option-3",
  );
  assert.equal(f.select.value, "coverage");
  f.key("Enter");
  assert.equal(f.select.value, "alternate");
  f.key("u");
  assert.equal(
    f.trigger.getAttribute("aria-activedescendant"),
    "strategy-option-1",
  );
  f.key("n");
  assert.equal(
    f.trigger.getAttribute("aria-activedescendant"),
    "strategy-option-1",
  );
  f.key("Escape");
  assert.equal(f.select.value, "alternate");
});
test("点击外部按WAI约定提交预览并关闭，不抢外部焦点", async () => {
  const f = fixture();
  f.trigger.click();
  f.key("ArrowDown");
  const outside = f.document.querySelector("#outside");
  outside.dispatchEvent(
    new f.window.PointerEvent("pointerdown", { bubbles: true }),
  );
  outside.focus();
  await f.flush();
  assert.equal(f.select.value, "uniform");
  assert.equal(f.popup.hidden, true);
  assert.equal(f.document.activeElement, outside);
});
test("焦点移出提交，disabled变更关闭菜单并同步button禁用", async () => {
  const f = fixture();
  f.trigger.click();
  f.key("ArrowDown");
  f.document.querySelector("#outside").focus();
  await f.flush();
  assert.equal(f.select.value, "uniform");
  f.trigger.click();
  f.key("Home");
  f.select.disabled = true;
  await f.flush();
  assert.equal(f.trigger.disabled, true);
  assert.equal(f.popup.hidden, true);
  assert.equal(f.select.value, "uniform");
  assert.ok(f.trigger.parentElement.classList.contains("is-disabled"));
  f.trigger.click();
  assert.equal(f.popup.hidden, true);
  f.select.disabled = false;
  await f.flush();
  assert.equal(f.trigger.disabled, false);
});
test("原select的input/change事件、动态options和说明更新都同步", async () => {
  const f = fixture();
  f.select.value = "uniform";
  f.select.dispatchEvent(new f.window.Event("change", { bubbles: true }));
  assert.equal(f.trigger.querySelector(".select-value").textContent, "Uniform");
  f.select.options[1].dataset.description = "新的说明";
  await f.flush();
  assert.equal(
    f.popup.querySelector('[data-index="1"] .select-option-description')
      .textContent,
    "新的说明",
  );
  const option = f.document.createElement("option");
  option.value = "new";
  option.textContent = "New";
  f.select.append(option);
  await f.flush();
  f.key("End");
  f.key("Enter");
  assert.equal(f.select.value, "new");
  option.remove();
  await f.flush();
  assert.equal(f.popup.querySelectorAll('[role="option"]').length, 4);
});
test("form.reset恢复默认选项并刷新自定义显示", async () => {
  const f = fixture();
  f.trigger.click();
  f.key("ArrowDown");
  f.key("Enter");
  assert.equal(f.select.value, "uniform");
  f.form.reset();
  await f.flush();
  assert.equal(f.select.value, "coverage");
  assert.equal(
    f.trigger.querySelector(".select-value").textContent,
    "Coverage",
  );
});
test("重复初始化只创建一套控件，destroy可恢复原select再增强", () => {
  const f = fixture();
  const twice = initCustomSelects(f.document);
  assert.equal(twice[0], f.controls[0]);
  assert.equal(f.document.querySelectorAll(".select-field").length, 1);
  twice[0].destroy();
  assert.equal(f.select.hidden, false);
  assert.equal(f.document.querySelector("label").htmlFor, "strategy");
  assert.equal(f.document.querySelector(".select-field"), null);
  assert.equal(f.select.getAttribute("aria-hidden"), null);
  initCustomSelects(f.document);
  assert.equal(f.document.querySelectorAll(".select-field").length, 1);
});
test("屏幕底部向上展开、水平防溢出，移出屏幕后关闭", () => {
  const f = fixture();
  let rect = {
    top: 770,
    bottom: 820,
    left: 300,
    right: 380,
    width: 80,
    height: 50,
  };
  f.trigger.getBoundingClientRect = () => rect;
  f.trigger.parentElement.getBoundingClientRect = () => rect;
  f.trigger.click();
  assert.equal(f.trigger.parentElement.dataset.placement, "top");
  assert.equal(f.popup.style.width, "260px");
  assert.equal(f.popup.style.left, "-186px");
  assert.ok(Number.parseFloat(f.popup.style.maxHeight) <= 340);
  rect = {
    top: -100,
    bottom: -50,
    left: 0,
    right: 100,
    width: 100,
    height: 50,
  };
  f.window.dispatchEvent(new f.window.Event("scroll"));
  assert.equal(f.popup.hidden, true);
});
