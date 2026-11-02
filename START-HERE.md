# Run RealityLoop AI locally

From the repository root, install the frontend dependencies and start the unified Vite application:

```powershell
npm --prefix frontend ci
npm run dev:frontend
```

Open `http://localhost:5173`. The public landing page and browser-local sample demo are at `/`; the React application is at `/app`. The sample works without backend services or API keys. Account and workspace actions need the backend, which Vite proxies from `/api/v1` to `http://127.0.0.1:8001` when it is running.

The 3D sample needs WebGL; its explanatory fallback and the rest of the demo remain usable when WebGL is unavailable. See [README.md](./README.md) for backend setup, tests, and Vercel deployment settings.
