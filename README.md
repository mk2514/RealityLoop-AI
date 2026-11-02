# RealityLoop AI landing page

Approved ivory / black / vermilion editorial landing page. Static ES-module application with locally vendored Three.js 0.180.0 (MIT license in `dist/assets/THREE-LICENSE.txt`).

## Features

- Two procedural WebGL factory views with orbit, zoom, keyboard view controls, selectable machines, flow playback, top view and an additional parallel drilling station.
- Validated browser-local CSV temperature import and sample export.
- Sensor selection, time ranges, expected and threshold overlays, normalized cross-metric comparison and selected-event context.
- Synthetic calibration example using 40 training and 20 held-out samples.
- Deterministic capacity comparison with demand, downtime, drilling cycles, parallel equipment and disruptions.
- Local demo configuration, decision history, JSON report export, privacy and terms dialogs.

## Run and verify

Serve `dist/` from a standard static HTTP server. Do not open index.html as a file URL because ES modules need HTTP. Run `npm test` for the model and CSV checks. No build step is required.

## Scope

This is a landing page with an interactive browser-local demonstration, not the production backend. There is no account authentication, MQTT/OPC UA connection, real machine control, photogrammetry service, cost/energy model or validated production simulation. All demo controls have corresponding behavior. Production accounts should replace the explicitly labelled demo setup only when an authentication backend is implemented.

No user data is sent to an application server by this page. Demo configuration and decision history use localStorage, while imported readings remain in memory. Read the page privacy notice for hosting limitations.

## Drafting style and motion

Machines use ivory surfaces, screen-space pencil hatching, crisp ink outlines, faint hidden edges, construction guides and projected station labels. Factory assembly draws on once, camera changes ease between views, and charts reveal their observed curve. Page effects can be paused globally. System reduced-motion preferences disable automatic motion. Offscreen scenes skip rendering and animation advances only while visible.
