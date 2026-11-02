import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppRouter } from "./router";

vi.mock("./landing/LandingPage", () => ({
  default: () => (
    <main>
      <a href="/app/register">GET STARTED</a>
      <a href="#teams">USE CASES</a>
      <section id="teams">USE CASES</section>
      <p>PUBLIC SAMPLE DEMO</p>
    </main>
  ),
}));

vi.mock("./App", () => ({
  default: () => (
    <main>
      <a href="/app/verify?token=sample-token">VERIFY ACCOUNT</a>
      <a href="/">PUBLIC SAMPLE DEMO</a>
      <output data-testid="route">
        {window.location.pathname}
        {window.location.search}
      </output>
    </main>
  ),
}));

describe("single-frontend routing", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    vi.stubGlobal("scrollTo", vi.fn());
  });

  afterEach(() => {
    cleanup();
    window.history.replaceState(null, "", "/");
    vi.unstubAllGlobals();
  });

  it("navigates between the public page and app while preserving auth queries and history", async () => {
    render(
      <StrictMode>
        <AppRouter />
      </StrictMode>,
    );

    fireEvent.click(await screen.findByRole("link", { name: "GET STARTED" }));
    expect(await screen.findByRole("link", { name: "VERIFY ACCOUNT" })).toBeTruthy();

    fireEvent.click(screen.getByRole("link", { name: "VERIFY ACCOUNT" }));
    await waitFor(() =>
      expect(screen.getByTestId("route").textContent).toBe(
        "/app/verify?token=sample-token",
      ),
    );

    await new Promise<void>((resolve) => {
      window.history.back();
      window.setTimeout(resolve, 0);
    });
    await waitFor(() =>
      expect(screen.getByTestId("route").textContent).toBe("/app/register"),
    );

    await new Promise<void>((resolve) => {
      window.history.forward();
      window.setTimeout(resolve, 0);
    });
    await waitFor(() =>
      expect(screen.getByTestId("route").textContent).toBe(
        "/app/verify?token=sample-token",
      ),
    );

    fireEvent.click(screen.getByRole("link", { name: "PUBLIC SAMPLE DEMO" }));
    expect(await screen.findByText("PUBLIC SAMPLE DEMO")).toBeTruthy();
    expect(window.location.pathname).toBe("/");
  });

  it("leaves landing-page hash navigation to the browser", async () => {
    render(<AppRouter />);
    const link = await screen.findByRole("link", { name: "USE CASES" });
    expect(fireEvent.click(link)).toBe(true);
  });
});
