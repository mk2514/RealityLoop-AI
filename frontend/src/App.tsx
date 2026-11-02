import { lazy, Suspense, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { ApiError, apiRequest } from "./api";
import { AssetRegistry } from "./AssetRegistry";
import { PhotoLineStarter } from "./PhotoLineStarter";
import { navigate } from "./router";
import faviconUrl from "./landing/assets/favicon.svg";
import { SimulationRuns } from "./SimulationRuns";

const DashboardCharts = lazy(() =>
  import("./DashboardCharts").then((module) => ({ default: module.DashboardCharts })),
);
const ScenarioWorkspace = lazy(() =>
  import("./ScenarioWorkspace").then((module) => ({ default: module.ScenarioWorkspace })),
);

type OrganizationInfo = { id: string; name: string; slug: string; role: string };
type DashboardData = {
  user: { full_name: string; email: string };
  organization: OrganizationInfo;
  factory_count: number;
  onboarding: {
    completed: number;
    total: number;
    steps: { key: string; label: string; complete: boolean }[];
  };
};
function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "The application service could not be reached. Try again shortly.";
}

function useFormStatus() {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setMessage("");
    setError("");
    try {
      await action();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  return { busy, message, error, setMessage, setError, run };
}

function Feedback({ message, error }: { message: string; error: string }) {
  return (
    <>
      {message && <p className="mt-5 border-l-2 border-accent pl-4 text-sm" role="status">{message}</p>}
      {error && <p className="mt-5 border-l-2 border-red-700 pl-4 text-sm text-red-800" role="alert">{error}</p>}
    </>
  );
}

function Shell({ children }: { children: ReactNode }) {
  return (
    <main className="min-h-screen bg-paper text-ink">
      <header className="border-b border-rule">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-5">
          <a
            className="flex items-center gap-3 font-mono text-sm font-semibold tracking-widest focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent"
            href="/"
          >
            <img alt="" className="h-9 w-9" height="36" src={faviconUrl} width="36" />
            REALITYLOOP AI
          </a>
          <a className="font-mono text-xs tracking-wider text-ink/70 hover:text-accent" href="/">
            PUBLIC SAMPLE DEMO
          </a>
        </div>
      </header>
      {children}
    </main>
  );
}

function AuthLayout({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <Shell>
      <section className="mx-auto grid min-h-[72vh] max-w-3xl content-center px-6 py-14">
        <p className="font-mono text-xs tracking-[0.2em] text-accent">{eyebrow}</p>
        <h1 className="mt-4 text-4xl font-semibold tracking-tight sm:text-5xl">{title}</h1>
        <div className="mt-8 border border-rule bg-white/50 p-6 sm:p-8">{children}</div>
      </section>
    </Shell>
  );
}

function RegisterPage() {
  const form = useFormStatus();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget).entries());
    void form.run(async () => {
      const result = await apiRequest<{ message: string }>("/auth/register", {
        method: "POST",
        body: JSON.stringify({
          full_name: values.full_name,
          email: values.email,
          password: values.password,
          organization_name: values.organization_name,
        }),
      });
      form.setMessage(`${result.message} Check the configured email inbox for a link.`);
    });
  }

  return (
    <AuthLayout eyebrow="ACCOUNT / REGISTRATION" title="Create your workspace.">
      <form className="space-y-5" onSubmit={submit}>
        <label className="form-field">
          <span>Full name</span>
          <input autoComplete="name" maxLength={200} name="full_name" required />
        </label>
        <label className="form-field">
          <span>Work email</span>
          <input autoComplete="email" maxLength={320} name="email" required type="email" />
        </label>
        <label className="form-field">
          <span>Organization name</span>
          <input autoComplete="organization" maxLength={200} name="organization_name" required />
        </label>
        <label className="form-field">
          <span>Password <small>(12 characters minimum)</small></span>
          <input autoComplete="new-password" maxLength={256} minLength={12} name="password" required type="password" />
        </label>
        <button className="action-button" disabled={form.busy} type="submit">
          {form.busy ? "CREATING ACCOUNT…" : "CREATE ACCOUNT"}
        </button>
      </form>
      <Feedback error={form.error} message={form.message} />
      <p className="mt-7 border-t border-rule pt-5 text-sm text-ink/70">
        Already registered? <a className="text-link" href="/app/login">Sign in</a>
      </p>
    </AuthLayout>
  );
}

function LoginPage() {
  const form = useFormStatus();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget).entries());
    void form.run(async () => {
      await apiRequest("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email: values.email, password: values.password }),
      });
      navigate("/app/dashboard");
    });
  }

  return (
    <AuthLayout eyebrow="ACCOUNT / SIGN IN" title="Return to your workspace.">
      <form className="space-y-5" onSubmit={submit}>
        <label className="form-field">
          <span>Email</span>
          <input autoComplete="email" maxLength={320} name="email" required type="email" />
        </label>
        <label className="form-field">
          <span>Password</span>
          <input autoComplete="current-password" maxLength={256} name="password" required type="password" />
        </label>
        <button className="action-button" disabled={form.busy} type="submit">
          {form.busy ? "SIGNING IN…" : "SIGN IN"}
        </button>
      </form>
      <Feedback error={form.error} message={form.message} />
      <div className="mt-7 flex flex-wrap justify-between gap-3 border-t border-rule pt-5 text-sm text-ink/70">
        <div className="flex flex-wrap gap-4">
          <a className="text-link" href="/app/forgot-password">Forgot password?</a>
          <a className="text-link" href="/app/resend-verification">Resend verification link</a>
        </div>
        <a className="text-link" href="/app/register">Create an account</a>
      </div>
    </AuthLayout>
  );
}

function ResendVerificationPage() {
  const form = useFormStatus();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget).entries());
    void form.run(async () => {
      const result = await apiRequest<{ message: string }>("/auth/resend-verification", {
        method: "POST",
        body: JSON.stringify({ email: values.email }),
      });
      form.setMessage(`${result.message} Check the configured email inbox for a link.`);
    });
  }

  return (
    <AuthLayout eyebrow="ACCOUNT / EMAIL VERIFICATION" title="Request a verification link.">
      <form className="space-y-5" onSubmit={submit}>
        <label className="form-field">
          <span>Account email</span>
          <input autoComplete="email" maxLength={320} name="email" required type="email" />
        </label>
        <button className="action-button" disabled={form.busy} type="submit">
          {form.busy ? "SENDING…" : "SEND VERIFICATION LINK"}
        </button>
      </form>
      <Feedback error={form.error} message={form.message} />
      <a className="mt-6 inline-block text-link" href="/app/login">Return to sign in</a>
    </AuthLayout>
  );
}

function VerifyPage() {
  const form = useFormStatus();
  const token = new URLSearchParams(window.location.search).get("token") ?? "";

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void form.run(async () => {
      const result = await apiRequest<{ message: string }>("/auth/verify", {
        method: "POST",
        body: JSON.stringify({ token }),
      });
      form.setMessage(result.message);
    });
  }

  return (
    <AuthLayout eyebrow="ACCOUNT / EMAIL VERIFICATION" title="Verify your email.">
      {!token ? (
        <p role="alert">This verification link is missing its one-time token.</p>
      ) : (
        <form onSubmit={submit}>
          <p className="text-sm leading-relaxed text-ink/70">This one-time link expires after 24 hours.</p>
          <button className="action-button mt-6" disabled={form.busy} type="submit">
            {form.busy ? "VERIFYING…" : "VERIFY EMAIL"}
          </button>
        </form>
      )}
      <Feedback error={form.error} message={form.message} />
      {form.message && <a className="mt-6 inline-block text-link" href="/app/login">Continue to sign in</a>}
    </AuthLayout>
  );
}

function RecoveryPage() {
  const form = useFormStatus();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget).entries());
    void form.run(async () => {
      const result = await apiRequest<{ message: string }>("/auth/password-reset/request", {
        method: "POST",
        body: JSON.stringify({ email: values.email }),
      });
      form.setMessage(`${result.message} Check the configured email inbox for a link.`);
    });
  }

  return (
    <AuthLayout eyebrow="ACCOUNT / RECOVERY" title="Reset your password.">
      <form className="space-y-5" onSubmit={submit}>
        <label className="form-field">
          <span>Account email</span>
          <input autoComplete="email" maxLength={320} name="email" required type="email" />
        </label>
        <button className="action-button" disabled={form.busy} type="submit">
          {form.busy ? "SENDING…" : "SEND RESET LINK"}
        </button>
      </form>
      <Feedback error={form.error} message={form.message} />
      <a className="mt-6 inline-block text-link" href="/app/login">Return to sign in</a>
    </AuthLayout>
  );
}

function ResetPasswordPage() {
  const form = useFormStatus();
  const token = new URLSearchParams(window.location.search).get("token") ?? "";

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget).entries());
    void form.run(async () => {
      const result = await apiRequest<{ message: string }>("/auth/password-reset/confirm", {
        method: "POST",
        body: JSON.stringify({ token, password: values.password }),
      });
      form.setMessage(result.message);
    });
  }

  return (
    <AuthLayout eyebrow="ACCOUNT / PASSWORD RESET" title="Choose a new password.">
      {!token ? (
        <p role="alert">This reset link is missing its one-time token.</p>
      ) : (
        <form className="space-y-5" onSubmit={submit}>
          <label className="form-field">
            <span>New password <small>(12 characters minimum)</small></span>
            <input autoComplete="new-password" maxLength={256} minLength={12} name="password" required type="password" />
          </label>
          <button className="action-button" disabled={form.busy} type="submit">
            {form.busy ? "UPDATING…" : "UPDATE PASSWORD"}
          </button>
        </form>
      )}
      <Feedback error={form.error} message={form.message} />
      {form.message && <a className="mt-6 inline-block text-link" href="/app/login">Continue to sign in</a>}
    </AuthLayout>
  );
}

function DashboardPage() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const form = useFormStatus();

  async function loadWorkspace() {
    setLoading(true);
    setLoadError("");
    try {
      const dashboardData = await apiRequest<DashboardData>("/dashboard");
      setDashboard(dashboardData);
    } catch (error) {
      setLoadError(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadWorkspace();
  }, []);

  function refreshDashboard() {
    void apiRequest<DashboardData>("/dashboard")
      .then(setDashboard)
      .catch((error: unknown) => setLoadError(errorMessage(error)));
  }

  function logout() {
    void form.run(async () => {
      await apiRequest("/auth/logout", { method: "POST" });
      navigate("/app/login");
    });
  }

  return (
    <Shell>
      <section className="mx-auto min-h-[72vh] max-w-7xl px-6 py-12">
        {loading && <p aria-live="polite" className="font-mono text-sm">LOADING WORKSPACE…</p>}
        {!loading && loadError && (
          <div className="max-w-2xl border border-rule bg-white/50 p-6" role="alert">
            <p className="font-mono text-xs tracking-widest text-accent">WORKSPACE UNAVAILABLE</p>
            <p className="mt-4">{loadError}</p>
            <button className="action-button mt-5" onClick={() => void loadWorkspace()} type="button">RETRY</button>
            <a className="ml-5 text-link" href="/app/login">Sign in</a>
          </div>
        )}
        {!loading && dashboard && (
          <>
            <div className="flex flex-wrap items-start justify-between gap-5 border-b border-rule pb-7">
              <div>
                <p className="font-mono text-xs tracking-[0.2em] text-accent">PRIVATE WORKSPACE / OVERVIEW</p>
                <h1 className="mt-4 text-4xl font-semibold tracking-tight">{dashboard.organization.name}</h1>
                <p className="mt-3 text-sm text-ink/65">Factory records and onboarding progress for this organization.</p>
              </div>
              <details className="relative">
                <summary className="cursor-pointer border border-ink px-4 py-3 font-mono text-xs tracking-wider focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
                  ACCOUNT / {dashboard.organization.role.toUpperCase()}
                </summary>
                <div className="absolute right-0 z-10 mt-2 min-w-64 border border-rule bg-paper p-4 shadow-sm">
                  <p className="font-semibold">{dashboard.organization.name}</p>
                  <p className="mt-1 text-sm text-ink/65">{dashboard.user.full_name}</p>
                  <p className="mt-1 text-sm text-ink/65">{dashboard.user.email}</p>
                  <p className="mt-1 text-sm text-ink/65">{dashboard.organization.slug}</p>
                  <p className="mt-1 text-sm text-ink/65">{dashboard.organization.role}</p>
                  <button className="mt-4 border-t border-rule pt-3 text-left font-mono text-xs tracking-wider hover:text-accent" onClick={logout} type="button">
                    SIGN OUT
                  </button>
                </div>
              </details>
            </div>
            <Feedback error={form.error} message="" />

            <div className="mt-8 grid gap-8">
              <AssetRegistry
                onChanged={refreshDashboard}
                onSignOut={logout}
                role={dashboard.organization.role}
              />
              <PhotoLineStarter />
              <Suspense fallback={<p className="font-mono text-sm">LOADING OBSERVED DATA…</p>}>
                <DashboardCharts />
              </Suspense>
              <Suspense fallback={<p className="font-mono text-sm">LOADING SCENARIOS…</p>}>
                <ScenarioWorkspace />
              </Suspense>
              <SimulationRuns />

              <aside className="border border-rule bg-white/40 p-6" aria-labelledby="onboarding-title">
                <p className="font-mono text-xs tracking-widest text-ink/60">ONBOARDING</p>
                <h2 className="mt-2 text-2xl font-semibold" id="onboarding-title">Workspace setup</h2>
                <p className="mt-3 font-mono text-sm">
                  {dashboard.onboarding.completed} / {dashboard.onboarding.total} COMPLETE
                </p>
                <ol className="mt-5 divide-y divide-rule border-y border-rule">
                  {dashboard.onboarding.steps.map((step) => (
                    <li className="flex items-center justify-between gap-4 py-3 text-sm" key={step.key}>
                      <span>{step.label}</span>
                      <span className="font-mono text-xs">{step.complete ? "COMPLETE" : "NOT STARTED"}</span>
                    </li>
                  ))}
                </ol>
              </aside>
            </div>
          </>
        )}
      </section>
    </Shell>
  );
}

function WelcomePage() {
  return (
    <AuthLayout eyebrow="APPLICATION / WORKSPACE" title="A private production workspace.">
      <p className="max-w-2xl text-sm leading-relaxed text-ink/75">
        Create an account and verify your email to set up an organization-scoped workspace. The public sample remains separate and is not copied into an account.
      </p>
      <div className="mt-7 flex flex-wrap gap-3">
        <a className="action-button" href="/app/register">GET STARTED</a>
        <a className="secondary-button" href="/app/login">SIGN IN</a>
      </div>
    </AuthLayout>
  );
}

export default function App() {
  const pathname = window.location.pathname.replace(/\/+$/, "") || "/";
  if (pathname === "/app/register") return <RegisterPage />;
  if (pathname === "/app/login") return <LoginPage />;
  if (pathname === "/app/verify") return <VerifyPage />;
  if (pathname === "/app/resend-verification") return <ResendVerificationPage />;
  if (pathname === "/app/forgot-password") return <RecoveryPage />;
  if (pathname === "/app/reset-password") return <ResetPasswordPage />;
  if (pathname === "/app/dashboard") return <DashboardPage />;
  return <WelcomePage />;
}
