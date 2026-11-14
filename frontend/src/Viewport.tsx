import { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import type { FaceMesh } from './types';
import { disposeScene, makeCamera, makeHead, makeRenderer, makeScene, positionCamera } from './scene';

interface Props {
  mesh: FaceMesh | null;
  yaw: { degrees: number; sequence: number };
  showRegion: boolean;
  focusNose: boolean;
  onError: (message: string) => void;
}

export default function Viewport({ mesh, yaw, showRegion, focusNose, onError }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const runtime = useRef<{ scene: THREE.Scene; camera: THREE.OrthographicCamera; controls: OrbitControls; head?: THREE.Group; draw: () => void } | null>(null);
  const [mounted, setMounted] = useState(false);
  const errorRef = useRef(onError);
  errorRef.current = onError;

  useEffect(() => {
    const container = host.current!;
    let renderer: THREE.WebGLRenderer;
    try { renderer = makeRenderer(container.clientWidth || 600, container.clientHeight || 600); }
    catch { errorRef.current('当前浏览器无法创建三维视图，请启用 WebGL 或换用支持硬件加速的浏览器。'); return; }
    renderer.domElement.setAttribute('aria-label', '可旋转的三维角色；也可使用上方视角按钮切换方向');
    renderer.domElement.setAttribute('role', 'img');
    const scene = makeScene();
    const camera = makeCamera();
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0, 0);
    controls.enablePan = false;
    controls.enableDamping = false;
    controls.minZoom = 0.7; controls.maxZoom = 2.8;
    controls.minPolarAngle = Math.PI * 0.25; controls.maxPolarAngle = Math.PI * 0.75;
    const draw = () => renderer.render(scene, camera);
    controls.addEventListener('change', draw);
    container.appendChild(renderer.domElement);
    runtime.current = { scene, camera, controls, draw };
    const resize = new ResizeObserver(() => {
      const width = container.clientWidth, height = container.clientHeight;
      if (!width || !height) return;
      const aspect = width / height;
      camera.left = -1.25 * aspect; camera.right = 1.25 * aspect;
      camera.top = 1.25; camera.bottom = -1.25;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
      draw();
    });
    resize.observe(container);
    draw();
    setMounted(true);
    return () => {
      resize.disconnect(); controls.removeEventListener('change', draw); controls.dispose();
      disposeScene(scene); renderer.dispose(); renderer.forceContextLoss();
      renderer.domElement.remove(); runtime.current = null; setMounted(false);
    };
  }, []);

  useEffect(() => {
    if (!mesh || !runtime.current) return;
    const current = runtime.current;
    if (current.head) { current.scene.remove(current.head); disposeScene(current.head); }
    current.head = makeHead(mesh, showRegion);
    current.scene.add(current.head);
    current.draw();
  }, [mesh, showRegion, mounted]);

  useEffect(() => {
    const current = runtime.current;
    if (!current) return;
    positionCamera(current.camera, yaw.degrees);
    const target = new THREE.Vector3();
    if (focusNose && mesh && current.head) {
      // Prefer the actual editable alar region; face_target is a safe asset fallback.
      let totalWeight = 0;
      mesh.vertices.forEach((vertex, index) => {
        const weight = mesh.edit_weights?.[index] ?? 0;
        if (weight > 0) {
          target.addScaledVector(new THREE.Vector3(...vertex), weight);
          totalWeight += weight;
        }
      });
      if (totalWeight > 0) target.divideScalar(totalWeight);
      else target.set(...(mesh.face_target ?? [0, 0, 0]));
      target.multiplyScalar(current.head.scale.x).add(current.head.position);
      current.camera.position.add(target);
      current.camera.lookAt(target);
    }
    current.camera.zoom = focusNose ? 2.6 : 1;
    current.camera.updateProjectionMatrix();
    current.controls.target.copy(target);
    current.controls.update(); current.draw();
  }, [yaw, focusNose, mounted]);

  return <div className="three-viewport" ref={host} />;
}
