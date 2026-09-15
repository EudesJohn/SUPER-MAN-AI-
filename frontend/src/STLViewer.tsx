import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";
import type { CadFileInfo } from "./api";

/** 3D viewer: loads the STL groups produced by the CAD engine.
 *  Drag = orbit, wheel = zoom. The body/hood group can be hidden so the
 *  electrical circuit and harness routed inside stay visible. */
export default function STLViewer({ files }: { files: CadFileInfo[] }) {
  const mountRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<THREE.Group | null>(null);
  const [visible, setVisible] = useState<Record<string, boolean>>({});
  const [spin, setSpin] = useState(true);        // turntable animation
  const spinRef = useRef(spin);
  spinRef.current = spin;

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount || files.length === 0) return;

    const width = mount.clientWidth || 800;
    const height = 460;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x14161a);

    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 200);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(window.devicePixelRatio);
    mount.appendChild(renderer.domElement);

    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const dir = new THREE.DirectionalLight(0xffffff, 1.1);
    dir.position.set(3, 5, 4);
    scene.add(dir);
    const dir2 = new THREE.DirectionalLight(0x88aaff, 0.4);
    dir2.position.set(-4, 2, -3);
    scene.add(dir2);

    const grid = new THREE.GridHelper(16, 32, 0x333333, 0x222222);
    scene.add(grid);

    const root = new THREE.Group();
    sceneRef.current = root;
    scene.add(root);

    const loader = new STLLoader();
    let disposed = false;
    const group = new THREE.Group();
    root.add(group);

    let pending = files.length;
    const center = new THREE.Vector3();

    files.forEach((f) => {
      loader.load(
        `/api/artifacts/${f.path}`,
        (geometry) => {
          if (disposed) return;
          geometry.computeBoundingBox();
          const bb = geometry.boundingBox!;
          bb.getCenter(center);
          geometry.translate(-center.x, -center.y, -center.z);
          geometry.computeVertexNormals();
          const material = new THREE.MeshStandardMaterial({
            color: new THREE.Color(f.color),
            metalness: 0.35,
            roughness: 0.55,
          });
          const obj = new THREE.Mesh(geometry, material);
          obj.name = f.path;
          group.add(obj);
          pending -= 1;
          if (pending === 0) {
            const box = new THREE.Box3().setFromObject(group);
            const size = box.getSize(new THREE.Vector3()).length();
            camera.position.set(size * 0.55, size * 0.45, size * 0.65);
            camera.lookAt(0, 0, 0);
            (camera as THREE.PerspectiveCamera & { userData: { radius: number } }).userData.radius = size;
          }
        },
        undefined,
        () => {
          if (!disposed) pending -= 1;
        }
      );
    });

    // Orbit controls (lightweight implementation: drag + wheel).
    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    let theta = 0.7;
    let phi = 0.5;
    let radius = 12;

    const onDown = (e: PointerEvent) => {
      dragging = true;
      lastX = e.clientX;
      lastY = e.clientY;
    };
    const onMove = (e: PointerEvent) => {
      if (!dragging) return;
      theta -= (e.clientX - lastX) * 0.006;
      phi = Math.max(0.05, Math.min(1.5, phi - (e.clientY - lastY) * 0.006));
      lastX = e.clientX;
      lastY = e.clientY;
    };
    const onUp = () => {
      dragging = false;
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      radius *= e.deltaY > 0 ? 1.1 : 0.9;
    };
    renderer.domElement.addEventListener("pointerdown", onDown);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    renderer.domElement.addEventListener("wheel", onWheel, { passive: false });

    let raf = 0;
    const animate = () => {
      raf = requestAnimationFrame(animate);
      if (spinRef.current && !dragging) theta += 0.004; // turntable, paused while user drags
      const target = radius || 12;
      camera.position.set(
        target * Math.sin(phi) * Math.cos(theta),
        target * Math.cos(phi),
        target * Math.sin(phi) * Math.sin(theta)
      );
      camera.lookAt(0, 0, 0);
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      renderer.domElement.removeEventListener("pointerdown", onDown);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      renderer.domElement.removeEventListener("wheel", onWheel);
      renderer.dispose();
      if (renderer.domElement.parentElement === mount) mount.removeChild(renderer.domElement);
    };
  }, [files]);

  // Apply visibility toggles + electrical-circuit pulse (harness glow).
  useEffect(() => {
    const root = sceneRef.current;
    if (!root) return;
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const t = 0.5 + 0.5 * Math.sin(performance.now() / 240); // 0..1 slow pulse
      root.traverse((o) => {
        const mesh = o as THREE.Mesh;
        if (!mesh.isMesh || !mesh.name) return;
        const key = files.find((f) => f.path === mesh.name)?.path ?? "";
        const isHarness = key.includes("harness");
        const isBody = key.includes("_body");
        if (isHarness) {
          mesh.visible = visible["harness"] !== false;
          const mat = mesh.material as THREE.MeshStandardMaterial;
          if (mat && mat.emissive) {
            mat.emissive = new THREE.Color(0xff5522);
            mat.emissiveIntensity = 0.25 + 0.75 * t; // circuit "alive"
          }
        } else if (isBody) {
          mesh.visible = visible["body"] !== false;
        }
      });
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [visible, files]);

  const chip = (label: string, key: string, color: string) => (
    <button
      key={key}
      onClick={() => setVisible((v) => ({ ...v, [key]: v[key] === false }))}
      style={{
        border: `2px solid ${color}`,
        opacity: visible[key] === false ? 0.35 : 1,
        borderRadius: 6,
        padding: "2px 8px",
        marginRight: 6,
        cursor: "pointer",
        background: "#1d2026",
        color: "#ddd",
        fontSize: 12,
      }}
      title="Clic pour masquer / afficher"
    >
      {label}
    </button>
  );

  return (
    <div>
      <div ref={mountRef} style={{ borderRadius: 8, overflow: "hidden" }} />
      <div style={{ marginTop: 6 }}>
        <button
          onClick={() => setSpin((s) => !s)}
          style={{
            border: "2px solid #4a90d9",
            borderRadius: 6,
            padding: "2px 10px",
            marginRight: 8,
            cursor: "pointer",
            background: spin ? "#1d3a55" : "#1d2026",
            color: "#ddd",
            fontSize: 12,
          }}
          title="Animation : rotation automatique du produit"
        >
          {spin ? "⏸ Arrêter la rotation" : "▶ Faire tourner le produit"}
        </button>
        <span className="dim" style={{ marginRight: 8 }}>Clic sur une pièce = masquer/afficher :</span>
        {chip("Carrosserie / Capot", "body", "#4caf50")}
        {chip("Circuit électrique", "harness", "#e8590c")}
      </div>
      <p className="dim">
        Glisser = pivoter · Molette = zoom · Le circuit électrique pulse à l'intérieur
        ; masquez la carrosserie pour le voir routé en 3D.
      </p>
    </div>
  );
}
