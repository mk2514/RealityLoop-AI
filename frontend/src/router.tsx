import { lazy, Suspense, useEffect, useState } from "react";

const LandingPage = lazy(() => import("./landing/LandingPage"));
const Application = lazy(() => import("./App"));

type RouteLocation = {
  pathname: string;
  search: string;
  hash: string;
};

function currentLocation(): RouteLocation {
  return {
    pathname: window.location.pathname,
    search: window.location.search,
    hash: window.location.hash,
  };
}

export function navigate(path: string): void {
  const target = new URL(path, window.location.href);
  if (target.origin !== window.location.origin) {
    window.location.assign(target.href);
    return;
  }
  window.history.pushState(null, "", target);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function onDocumentClick(event: MouseEvent): void {
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  ) {
    return;
  }

  const target = event.target;
  if (!(target instanceof Element)) return;
  const anchor = target.closest<HTMLAnchorElement>("a[href]");
  if (
    !anchor ||
    anchor.hasAttribute("download") ||
    (anchor.target && anchor.target !== "_self")
  ) {
    return;
  }

  const destination = new URL(anchor.href, window.location.href);
  if (
    destination.origin !== window.location.origin ||
    (destination.pathname === window.location.pathname &&
      destination.search === window.location.search)
  ) {
    return;
  }
  if (
    destination.pathname !== "/" &&
    destination.pathname !== "/app" &&
    !destination.pathname.startsWith("/app/")
  ) {
    return;
  }

  event.preventDefault();
  navigate(`${destination.pathname}${destination.search}${destination.hash}`);
}

export function AppRouter() {
  const [location, setLocation] = useState(currentLocation);

  useEffect(() => {
    const updateLocation = () => setLocation(currentLocation());
    window.addEventListener("popstate", updateLocation);
    document.addEventListener("click", onDocumentClick);
    return () => {
      window.removeEventListener("popstate", updateLocation);
      document.removeEventListener("click", onDocumentClick);
    };
  }, []);

  useEffect(() => {
    document.title =
      location.pathname === "/"
        ? "RealityLoop AI | Test the change. Trust the model."
        : "RealityLoop AI | Application";
    if (!location.hash) window.scrollTo(0, 0);
  }, [location.pathname, location.search, location.hash]);

  const isApplicationRoute =
    location.pathname === "/app" || location.pathname.startsWith("/app/");
  return (
    <Suspense
      fallback={
        <main className="min-h-screen bg-paper px-6 py-16 text-ink">
          <p className="font-mono text-sm" role="status">
            LOADING REALITYLOOP…
          </p>
        </main>
      }
    >
      {isApplicationRoute ? <Application /> : <LandingPage />}
    </Suspense>
  );
}
