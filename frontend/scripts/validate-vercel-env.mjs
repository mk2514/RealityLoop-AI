if (process.env.VERCEL === "1") {
  const apiBaseUrl = process.env.VITE_API_BASE_URL;
  if (!apiBaseUrl) {
    throw new Error(
      "Set VITE_API_BASE_URL to the HTTPS Render API URL ending in /api/v1 in the Vercel project environment.",
    );
  }
  if (!apiBaseUrl.startsWith("https://") || !apiBaseUrl.endsWith("/api/v1")) {
    throw new Error(
      "VITE_API_BASE_URL must be an HTTPS URL ending in /api/v1.",
    );
  }
}
