import React, { act } from "react";
import { createRoot } from "react-dom/client";
import ProductionRoute from "./ProductionRoute";

let container, root;
const job = { id: "test-job", stock: "14pt matte", sides: 2 };
const option = { id: "press-1", printer: "Shop Press", hostname: "P2GL-2", status: "Connected", eligible: true, blockers: [], capabilitySource: "Operator verification required" };
const options = { settingsVersion: 3, options: [option], message: "Select a printer." };
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
const render = async (props = {}) => {
  const defaults = { job, api: jest.fn().mockResolvedValue(options), action: jest.fn(), busy: false, error: "", openSettings: jest.fn(), reloadJob: jest.fn() };
  const values = { ...defaults, ...props };
  await act(async () => root.render(<ProductionRoute {...values} />));
  return values;
};
const change = async (element, value) => {
  await act(async () => {
    Object.getOwnPropertyDescriptor(element.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLTextAreaElement.prototype, "value").set.call(element, value);
    element.dispatchEvent(new Event(element.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
  });
};
test("requires printer selection, evidence and compatibility confirmation before saving", async () => {
  const values = await render();
  const button = container.querySelector('[data-testid="select-route-button"]');
  expect(button.disabled).toBe(true);
  await change(container.querySelector("select"), "press-1");
  expect(button.disabled).toBe(true);
  await change(container.querySelector("textarea"), "Verified stock and duplex specifications.");
  await act(async () => container.querySelector('input[type="checkbox"]').click());
  expect(button.disabled).toBe(false);
  await act(async () => button.click());
  expect(values.action).toHaveBeenCalledWith("route", expect.objectContaining({ routeId: "press-1", settingsVersion: 3, compatibilityConfirmed: true }));
});
test("shows configuration blockers and keeps the route blocked", async () => {
  await render({ api: jest.fn().mockResolvedValue({ ...options, options: [{ ...option, eligible: false, blockers: ["Configure supported stock in Shop settings."] }] }) });
  await change(container.querySelector("select"), "press-1");
  expect(container.textContent).toContain("Configure supported stock");
  expect(container.querySelector('[data-testid="select-route-button"]').disabled).toBe(true);
});
test("displays server failure beside the button and offers status refresh", async () => {
  const reloadJob = jest.fn();
  await render({ error: "Shop settings changed. Refresh the printer list.", reloadJob });
  expect(container.querySelector('[data-testid="route-action-error"]').getAttribute("role")).toBe("alert");
  await act(async () => [...container.querySelectorAll("button")].find((button) => button.textContent === "Refresh job status").click());
  expect(reloadJob).toHaveBeenCalledTimes(1);
});
test("failed printer loading is actionable and never enables save", async () => {
  await render({ api: jest.fn().mockRejectedValue(new Error("Printer service unavailable")) });
  expect(container.textContent).toContain("Printer service unavailable");
  expect(container.querySelector('[data-testid="select-route-button"]').disabled).toBe(true);
});
test("saving is visibly busy and prevents duplicate submissions", async () => {
  await render({ busy: true });
  expect(container.querySelector('[data-testid="select-route-button"]').textContent).toBe("Saving route...");
  expect(container.querySelector('[data-testid="select-route-button"]').disabled).toBe(true);
});
test("a successful HTTP response without route data becomes an actionable error", async () => {
  await render({ api: jest.fn().mockResolvedValue(null) });
  expect(container.textContent).toContain("Printer service returned an invalid response");
  expect(container.querySelector('[data-testid="select-route-button"]').disabled).toBe(true);
});
test("a printer list request that never responds times out visibly", async () => {
  jest.useFakeTimers();
  try {
    await render({ api: jest.fn((path, { signal }) => new Promise((resolve, reject) => {
      signal.addEventListener("abort", () => { const error = new Error("Aborted"); error.name = "AbortError"; reject(error); });
    })) });
    expect(container.textContent).toContain("Loading discovered printers");
    await act(async () => jest.advanceTimersByTime(15000));
    expect(container.textContent).toContain("Printer list timed out");
    expect([...container.querySelectorAll("button")].find((button) => button.textContent === "Refresh printers").disabled).toBe(false);
  } finally { jest.useRealTimers(); }
});
