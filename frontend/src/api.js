export const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const failureMessage = (response, data) => {
  if (data?.error) return data.error;
  if (response.status === 409) {
    return "The shop could not accept this step. Retry, or choose Proof only. Nothing was sent to a press.";
  }
  return "Unable to save. Please retry.";
};

export const api = async (path, options = {}) => {
  const { timeoutMs, signal, ...rest } = options;
  const controller = new AbortController();
  const onAbort = () => controller.abort();
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener("abort", onAbort, { once: true });
  }
  const timer = timeoutMs ? setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    const response = await fetch(`${API}/${path}`, {
      credentials: "include",
      ...rest,
      signal: (timeoutMs || signal) ? controller.signal : undefined,
      headers: rest.body instanceof FormData
        ? rest.headers
        : { "Content-Type": "application/json", ...rest.headers },
    });
    const data = response.headers.get("content-type")?.includes("application/json")
      ? await response.json()
      : null;
    if (!response.ok) {
      const error = new Error(failureMessage(response, data));
      error.code = data?.code || (response.status === 409 ? "conflict" : undefined);
      error.status = response.status;
      throw error;
    }
    return data;
  } catch (error) {
    if (error?.code === "timeout" || error?.code === "network" || error?.code === "conflict" || error?.code === "machine-required" || error?.status) {
      throw error;
    }
    if (error?.name === "AbortError" || error?.name === "TimeoutError") {
      const timeout = new Error("This took too long. Retry. Nothing was sent to a press.");
      timeout.code = "timeout";
      throw timeout;
    }
    if (error instanceof TypeError) {
      const network = new Error("The shop could not be reached. Check your connection and retry.");
      network.code = "network";
      throw network;
    }
    throw error;
  } finally {
    if (timer) clearTimeout(timer);
    if (signal) signal.removeEventListener("abort", onAbort);
  }
};
