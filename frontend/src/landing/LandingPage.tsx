import { useEffect, useRef } from "react";
import template from "./template.html?raw";
import { mountLanding } from "./demo.js";
import { mountLandingMotion } from "./motion.js";
import "./landing.css";

export default function LandingPage() {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const stopMotion = mountLandingMotion(container);
    const stopDemo = mountLanding(container);
    let hashFrame: number | undefined;
    if (window.location.hash) {
      const targetId = decodeURIComponent(window.location.hash.slice(1));
      hashFrame = requestAnimationFrame(() => {
        const target = [...container.querySelectorAll<HTMLElement>("[id]")].find(
          (element) => element.id === targetId,
        );
        target?.scrollIntoView();
      });
    }

    return () => {
      if (hashFrame !== undefined) cancelAnimationFrame(hashFrame);
      stopDemo();
      stopMotion();
    };
  }, []);

  return (
    <div
      className="landing-page"
      dangerouslySetInnerHTML={{ __html: template }}
      ref={containerRef}
    />
  );
}
