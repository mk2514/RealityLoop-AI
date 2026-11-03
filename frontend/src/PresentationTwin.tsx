import { useEffect, useRef, useState } from "react";
import * as THREE from "three";

export function PresentationTwin() {
  const mountRef = useRef<HTMLDivElement>(null);
  const speedRef = useRef(1500);
  const pausedRef = useRef(false);
  const resetViewRef = useRef<(() => void) | null>(null);
  const [speed, setSpeed] = useState(1500);
  const [paused, setPaused] = useState(false);
  const [anomaly, setAnomaly] = useState(false);

  useEffect(() => {
    speedRef.current = speed;
  }, [speed]);

  useEffect(() => {
    pausedRef.current = paused;
  }, [paused]);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch {
      mount.textContent = "3D preview unavailable: WebGL is not enabled.";
      return;
    }

    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(mount.clientWidth || 900, 420);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    mount.replaceChildren(renderer.domElement);
    renderer.domElement.setAttribute("aria-label", "Presentation conveyor 3D twin");

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf5f5ee);
    const camera = new THREE.PerspectiveCamera(35, (mount.clientWidth || 900) / 420, 0.1, 100);
    camera.position.set(9, 7, 10);
    camera.lookAt(0, 0.8, 0);
    const homePosition = camera.position.clone();

    scene.add(new THREE.HemisphereLight(0xffffff, 0xc7c5b8, 2.2));
    const keyLight = new THREE.DirectionalLight(0xffffff, 2);
    keyLight.position.set(6, 10, 8);
    scene.add(keyLight);

    const ink = new THREE.MeshStandardMaterial({ color: 0x36382f, roughness: 0.75 });
    const ivory = new THREE.MeshStandardMaterial({ color: 0xe9e7dc, roughness: 0.82 });
    const orange = new THREE.MeshStandardMaterial({ color: 0xf0441a, roughness: 0.7 });
    const beltMaterial = new THREE.MeshStandardMaterial({ color: 0x737a6f, roughness: 0.9 });

    const conveyor = new THREE.Group();
    scene.add(conveyor);
    const belt = new THREE.Mesh(new THREE.BoxGeometry(10, 0.16, 2.8), beltMaterial);
    belt.position.y = 1.2;
    conveyor.add(belt);

    for (const x of [-4.5, -3, -1.5, 0, 1.5, 3, 4.5]) {
      const roller = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.16, 2.5, 16), ink);
      roller.rotation.x = Math.PI / 2;
      roller.position.set(x, 1.32, 0);
      conveyor.add(roller);
    }

    for (const x of [-4.7, 4.7]) {
      for (const z of [-1.15, 1.15]) {
        const leg = new THREE.Mesh(new THREE.BoxGeometry(0.16, 1.2, 0.16), ink);
        leg.position.set(x, 0.55, z);
        conveyor.add(leg);
      }
    }

    const motor = new THREE.Group();
    motor.position.set(-3.8, 0.95, 1.9);
    const motorBody = new THREE.Mesh(new THREE.CylinderGeometry(0.65, 0.65, 1.4, 20), ivory);
    motorBody.rotation.z = Math.PI / 2;
    motor.add(motorBody);
    motor.add(new THREE.Mesh(new THREE.TorusGeometry(0.45, 0.08, 10, 24), ink));
    conveyor.add(motor);

    const rotor = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 1.8, 16), orange);
    rotor.rotation.z = Math.PI / 2;
    rotor.position.set(-3.8, 0.95, 1.9);
    conveyor.add(rotor);

    const packages: THREE.Mesh[] = [];
    for (let index = 0; index < 3; index += 1) {
      const packageMesh = new THREE.Mesh(new THREE.BoxGeometry(0.75, 0.65, 0.75), ivory);
      packageMesh.position.set(-2.5 + index * 2.1, 1.72, index % 2 === 0 ? 0.5 : -0.5);
      conveyor.add(packageMesh);
      packages.push(packageMesh);
    }

    const grid = new THREE.GridHelper(14, 14, 0xc7c5b8, 0xdedbd0);
    grid.position.y = -0.08;
    scene.add(grid);

    resetViewRef.current = () => {
      camera.position.copy(homePosition);
      camera.lookAt(0, 0.8, 0);
    };

    let frame = 0;
    let pointerDown = false;
    let lastX = 0;
    const onPointerDown = (event: PointerEvent) => {
      pointerDown = true;
      lastX = event.clientX;
    };
    const onPointerMove = (event: PointerEvent) => {
      if (!pointerDown) return;
      const delta = event.clientX - lastX;
      lastX = event.clientX;
      const offset = camera.position.clone().sub(new THREE.Vector3(0, 0.8, 0));
      const spherical = new THREE.Spherical().setFromVector3(offset);
      spherical.theta -= delta * 0.008;
      camera.position.copy(new THREE.Vector3(0, 0.8, 0).add(new THREE.Vector3().setFromSpherical(spherical)));
      camera.lookAt(0, 0.8, 0);
    };
    const onPointerUp = () => { pointerDown = false; };
    renderer.domElement.addEventListener("pointerdown", onPointerDown);
    renderer.domElement.addEventListener("pointermove", onPointerMove);
    renderer.domElement.addEventListener("pointerup", onPointerUp);
    renderer.domElement.addEventListener("pointerleave", onPointerUp);

    const onResize = () => {
      if (!mount) return;
      const width = mount.clientWidth || 900;
      renderer.setSize(width, 420);
      camera.aspect = width / 420;
      camera.updateProjectionMatrix();
    };
    window.addEventListener("resize", onResize);

    const clock = new THREE.Clock();
    const animate = () => {
      frame = window.requestAnimationFrame(animate);
      const delta = clock.getDelta();
      if (!pausedRef.current) {
        const normalized = Math.max(0.2, Math.min(1, speedRef.current / 1500));
        packages.forEach((packageMesh, index) => {
          packageMesh.position.x += delta * normalized * 0.8;
          if (packageMesh.position.x > 4.7) packageMesh.position.x = -4.5 + index * 0.8;
        });
        rotor.rotation.x += delta * normalized * 4;
      }
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", onResize);
      renderer.domElement.removeEventListener("pointerdown", onPointerDown);
      renderer.domElement.removeEventListener("pointermove", onPointerMove);
      renderer.domElement.removeEventListener("pointerup", onPointerUp);
      renderer.domElement.removeEventListener("pointerleave", onPointerUp);
      resetViewRef.current = null;
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh) {
          object.geometry.dispose();
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          materials.forEach((material) => material.dispose());
        }
      });
      renderer.dispose();
      mount.replaceChildren();
    };
  }, []);

  function setDemoSpeed(value: number, warning = false) {
    setSpeed(value);
    setAnomaly(warning);
  }

  return (
    <section className="border border-rule bg-white/40 p-6" aria-labelledby="presentation-twin-title">
      <p className="font-mono text-xs tracking-widest text-ink/60">3D DEMO TWIN · SIMULATED MOVEMENT</p>
      <h2 className="mt-2 text-2xl font-semibold" id="presentation-twin-title">Miniature conveyor</h2>
      <p className="mt-2 text-sm text-ink/65">
        Presentation-only 3D model. Animation does not represent measured ESP32 speed.
      </p>
      <div className="mt-4 flex flex-wrap gap-3">
        <button className="secondary-button" type="button" onClick={() => setDemoSpeed(1500)}>NORMAL SPEED</button>
        <button className="secondary-button" type="button" onClick={() => setDemoSpeed(900, true)}>DEMO REDUCED SPEED</button>
        <button className="secondary-button" type="button" onClick={() => setPaused((value) => !value)}>{paused ? "RESUME" : "PAUSE"}</button>
        <button className="secondary-button" type="button" onClick={() => resetViewRef.current?.()}>RESET VIEW</button>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-5 text-sm">
        <span className="font-mono">RPM {speed}</span>
        <span className={anomaly ? "text-red-800" : "text-ink/65"}>
          {anomaly ? "ANOMALY CANDIDATE · DEMO" : "NORMAL DEMO STATE"}
        </span>
        <label className="form-field min-w-48"><span>Motor speed</span><input type="range" min="300" max="1500" step="50" value={speed} onChange={(event) => setDemoSpeed(Number(event.target.value), Number(event.target.value) < 1275)} /></label>
      </div>
      <div ref={mountRef} className="mt-4 h-[420px] w-full overflow-hidden border border-rule" />
    </section>
  );
}
