export const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export const api = async (path, options = {}) => {
  const response = await fetch(`${API}/${path}`, {
    credentials: "include",
    ...options,
    headers: options.body instanceof FormData
      ? options.headers
      : { "Content-Type": "application/json", ...options.headers },
  });
  const data = response.headers.get("content-type")?.includes("application/json")
    ? await response.json()
    : null;
  if (!response.ok) {
    const error = new Error(data?.error || "Unable to save. Please retry.");
    error.code = data?.code;
    throw error;
  }
  return data;
};
