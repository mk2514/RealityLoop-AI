const apiBaseUrl = process.env.VITE_API_BASE_URL?.trim();
const usesLocalProxy =
  apiBaseUrl === "/api/v1" && process.env.VERCEL !== "1";
if (apiBaseUrl && !usesLocalProxy) {
  let url;
  try {
    url = new URL(apiBaseUrl);
  } catch {
    throw new Error("VITE_API_BASE_URL must be an absolute API URL ending in /api/v1.");
  }

  const isLocalDevelopment =
    url.protocol === "http:" &&
    ["localhost", "127.0.0.1"].includes(url.hostname);
  if (
    (url.protocol !== "https:" && !isLocalDevelopment) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    url.pathname.replace(/\/+$/, "") !== "/api/v1"
  ) {
    throw new Error(
      "VITE_API_BASE_URL must be an HTTPS URL ending in /api/v1 (HTTP is allowed for localhost development).",
    );
  }
}
