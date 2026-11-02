import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Application rendering failed.", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <main className="mx-auto max-w-3xl px-6 py-24" role="alert">
          <p className="font-mono text-xs tracking-widest text-accent">APPLICATION ERROR</p>
          <h1 className="mt-4 text-3xl font-semibold">This screen could not be displayed.</h1>
          <p className="mt-4 text-ink/70">
            Reload the page to try again. If the problem persists, contact your system
            administrator.
          </p>
          <button
            className="mt-8 border border-ink px-5 py-3 font-mono text-sm hover:bg-ink hover:text-paper focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            onClick={() => window.location.reload()}
            type="button"
          >
            RELOAD APPLICATION
          </button>
        </main>
      );
    }

    return this.props.children;
  }
}
