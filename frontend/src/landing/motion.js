export function mountLandingMotion(container) {
  const media = window.matchMedia("(prefers-reduced-motion: reduce)");
  const button = container.querySelector("#page-motion");
  const animations = new Set();
  const observers = new Set();
  const timers = new Set();
  const addedRules = [];
  const listeners = new AbortController();
  let enabled = !media.matches;
  let frame;

  function play(element, keyframes, options = {}) {
    if (!enabled || !element?.animate) return;
    const animation = element.animate(keyframes, {
      duration: 520,
      easing: "cubic-bezier(.2,.7,.2,1)",
      ...options,
    });
    animations.add(animation);
    animation.finished
      .then(() => animations.delete(animation))
      .catch(() => animations.delete(animation));
    return animation;
  }

  function applyMotion(value) {
    enabled = value;
    container.dataset.motion = enabled ? "running" : "paused";
    button.textContent = enabled ? "PAUSE EFFECTS" : "RESUME EFFECTS";
    button.setAttribute("aria-pressed", String(!enabled));
    if (!enabled) {
      for (const animation of animations) animation.cancel();
      animations.clear();
    }
    document.dispatchEvent(
      new CustomEvent("realityloop:motion", { detail: { enabled } }),
    );
  }

  function observeIntersection(observer, element) {
    observers.add(observer);
    observer.observe(element);
  }

  function schedule(callback, delay) {
    const timer = window.setTimeout(() => {
      timers.delete(timer);
      callback();
    }, delay);
    timers.add(timer);
    return timer;
  }

  button.onclick = () => applyMotion(!enabled);
  media.addEventListener("change", onMotionPreferenceChange);
  applyMotion(enabled);

  for (const [index, element] of [
    ...container.querySelectorAll(".nav,.hero-bottom h1,.hero-copy"),
  ].entries()) {
    play(
      element,
      [
        { opacity: 0.35, transform: "translateY(10px)" },
        { opacity: 1, transform: "translateY(0)" },
      ],
      { delay: index * 70, duration: 650 },
    );
  }

  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          play(entry.target, [
            { opacity: 0.55, transform: "translateY(14px)" },
            { opacity: 1, transform: "translateY(0)" },
          ]);
          observer.unobserve(entry.target);
        }
      },
      { threshold: 0.12 },
    );
    container
      .querySelectorAll(
        ".section-top,.trust-copy,.validation-panel,.closing,.footer-grid",
      )
      .forEach((element) => observeIntersection(observer, element));
  }

  function drawChart(element) {
    const path = element.querySelector('path[stroke="#343b2d"]');
    if (!path?.getTotalLength) return;
    try {
      const length = path.getTotalLength();
      if (!Number.isFinite(length) || length <= 0) return;
      play(
        path,
        [
          {
            strokeDasharray: `${length} ${length}`,
            strokeDashoffset: length,
          },
          { strokeDasharray: `${length} ${length}`, strokeDashoffset: 0 },
        ],
        { duration: 560 },
      );
    } catch {
      return;
    }
  }

  const chartTimers = new Map();
  const chartObserver = new MutationObserver((entries) => {
    for (const entry of entries) {
      const element = entry.target;
      const previous = chartTimers.get(element);
      if (previous !== undefined) {
        window.clearTimeout(previous);
        timers.delete(previous);
      }
      const timer = schedule(() => {
        drawChart(element);
        chartTimers.delete(element);
      }, 90);
      chartTimers.set(element, timer);
    }
  });
  container.querySelectorAll("#sensor-chart,#trust-chart").forEach((element) => {
    observers.add(chartObserver);
    chartObserver.observe(element, { childList: true });
    drawChart(element);
  });

  const resultObserver = new MutationObserver((entries) => {
    for (const element of new Set(entries.map((entry) => entry.target))) {
      play(element, [
        { opacity: 0.4, transform: "translateY(3px)" },
        { opacity: 1, transform: "translateY(0)" },
      ], { duration: 240 });
    }
  });
  observers.add(resultObserver);
  for (const element of container.querySelectorAll(
    "#baseline-output,#proposed-output,#decision-status",
  )) {
    resultObserver.observe(element, { childList: true });
  }

  const dialogObserver = new MutationObserver((entries) => {
    for (const entry of entries) {
      if (!entry.target.open) continue;
      play(
        entry.target,
        [
          { opacity: 0, transform: "translateY(12px)" },
          { opacity: 1, transform: "translateY(0)" },
        ],
        { duration: 200 },
      );
    }
  });
  observers.add(dialogObserver);
  for (const element of container.querySelectorAll("dialog")) {
    dialogObserver.observe(element, {
      attributes: true,
      attributeFilter: ["open"],
    });
  }

  function progress() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      const max = container.scrollHeight - window.innerHeight;
      const ratio =
        max > 0 ? Math.max(0, Math.min(1, window.scrollY / max)) : 0;
      container.querySelector(".reading-progress").style.transform =
        `scaleX(${ratio})`;
    });
  }
  window.addEventListener("scroll", progress, {
    passive: true,
    signal: listeners.signal,
  });
  window.addEventListener("resize", progress, { signal: listeners.signal });
  progress();

  for (const section of container.querySelectorAll(".section-top")) {
    const rule = document.createElement("i");
    rule.className = "draft-rule";
    rule.setAttribute("aria-hidden", "true");
    section.append(rule);
    addedRules.push(rule);
    if ("IntersectionObserver" in window) {
      const observer = new IntersectionObserver((entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        play(
          rule,
          [
            { transform: "scaleX(0)", opacity: 1 },
            { transform: "scaleX(1)", opacity: 0.75 },
            { transform: "scaleX(1)", opacity: 0 },
          ],
          { duration: 850 },
        );
        observer.disconnect();
        observers.delete(observer);
      });
      observeIntersection(observer, section);
    }
  }

  return () => {
    media.removeEventListener("change", onMotionPreferenceChange);
    listeners.abort();
    for (const observer of observers) observer.disconnect();
    observers.clear();
    for (const timer of timers) window.clearTimeout(timer);
    timers.clear();
    for (const animation of animations) animation.cancel();
    animations.clear();
    cancelAnimationFrame(frame);
    for (const rule of addedRules) rule.remove();
    button.onclick = null;
    delete container.dataset.motion;
  };

  function onMotionPreferenceChange(event) {
    applyMotion(!event.matches);
  }
}
