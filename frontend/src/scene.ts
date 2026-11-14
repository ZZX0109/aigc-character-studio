import * as THREE from 'three';
import type { FaceMesh, RenderedView } from './types';
import { VIEWS } from './types';

export function makeGeometry(mesh: FaceMesh, showRegion = false): THREE.BufferGeometry {
  if (!mesh.vertices.length || !mesh.faces.length) throw new Error('角色模型没有可显示的几何数据。');
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(mesh.vertices.flat(), 3));
  geometry.setIndex(mesh.faces.flat());
  geometry.computeVertexNormals();
  if (showRegion && mesh.edit_weights) {
    const base = new THREE.Color('#c9b29b');
    const selected = new THREE.Color('#c65a2d');
    const colors = mesh.vertices.flatMap((_, index) => {
      const mix = Math.min(1, Math.max(0, mesh.edit_weights?.[index] ?? 0));
      return base.clone().lerp(selected, mix).toArray();
    });
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
  }
  return geometry;
}

export function makeHead(mesh: FaceMesh, showRegion = false, framingMesh?: FaceMesh): THREE.Group {
  const geometry = makeGeometry(mesh, showRegion);
  geometry.computeBoundingBox();
  // Pair renders use one reference frame, rather than independently fitting
  // the edited geometry and accidentally changing apparent edit magnitude.
  const box = framingMesh
    ? new THREE.Box3().setFromPoints(framingMesh.vertices.map(vertex => new THREE.Vector3(...vertex)))
    : geometry.boundingBox!;
  const center = box.getCenter(new THREE.Vector3());
  const height = Math.max(box.max.y - box.min.y, 0.00001);
  const scale = 2 / height;
  const material = new THREE.MeshStandardMaterial({
    color: showRegion && mesh.edit_weights ? '#ffffff' : '#c9b29b',
    roughness: 0.68,
    metalness: 0.03,
    vertexColors: showRegion && !!mesh.edit_weights,
    side: THREE.DoubleSide,
  });
  const head = new THREE.Mesh(geometry, material);
  head.castShadow = true;
  head.receiveShadow = true;
  const group = new THREE.Group();
  group.add(head);
  group.scale.setScalar(scale);
  group.position.copy(center.multiplyScalar(-scale));
  return group;
}

export function makeScene(): THREE.Scene {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color('#efede8');
  scene.add(new THREE.HemisphereLight('#ffffff', '#a0927f', 2.0));
  const key = new THREE.DirectionalLight('#fff8ef', 2.6);
  key.position.set(-3, 4, 5);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  key.shadow.camera.left = -2; key.shadow.camera.right = 2;
  key.shadow.camera.top = 2; key.shadow.camera.bottom = -2;
  key.shadow.normalBias = 0.015;
  scene.add(key);
  const fill = new THREE.DirectionalLight('#e8efff', 1.25);
  fill.position.set(4, 1, 3);
  scene.add(fill);
  const rim = new THREE.DirectionalLight('#fff6e5', 1.7);
  rim.position.set(1, 3, -4);
  scene.add(rim);
  const floor = new THREE.Mesh(new THREE.CircleGeometry(5, 80), new THREE.MeshStandardMaterial({ color: '#e6e3dd', roughness: 1 }));
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -1.035;
  floor.receiveShadow = true;
  scene.add(floor);
  return scene;
}

export function makeCamera(aspect = 1): THREE.OrthographicCamera {
  const halfHeight = 1.25;
  const camera = new THREE.OrthographicCamera(-halfHeight * aspect, halfHeight * aspect, halfHeight, -halfHeight, 0.01, 100);
  positionCamera(camera, 0);
  return camera;
}

export function positionCamera(camera: THREE.OrthographicCamera, yaw: number): void {
  const radians = THREE.MathUtils.degToRad(yaw);
  camera.position.set(Math.sin(radians) * 5, 0.05, Math.cos(radians) * 5);
  camera.lookAt(0, 0, 0);
  camera.updateProjectionMatrix();
}

export function makeRenderer(width: number, height: number, preserveDrawingBuffer = false): THREE.WebGLRenderer {
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer, alpha: false });
  renderer.setPixelRatio(1);
  renderer.setSize(width, height);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.0;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  return renderer;
}

export function disposeScene(scene: THREE.Object3D): void {
  scene.traverse((object) => {
    if (object instanceof THREE.Mesh) {
      object.geometry.dispose();
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) material.dispose();
    }
  });
}

export async function renderViews(mesh: FaceMesh, size = 768, framingMesh?: FaceMesh): Promise<RenderedView[]> {
  const renderer = makeRenderer(size, size, true);
  const scene = makeScene();
  scene.add(makeHead(mesh, false, framingMesh));
  const camera = makeCamera();
  const images: RenderedView[] = [];
  try {
    for (const view of VIEWS) {
      positionCamera(camera, view.yaw_degrees);
      renderer.render(scene, camera);
      images.push({ name: view.name, yaw_degrees: view.yaw_degrees, png_base64: renderer.domElement.toDataURL('image/png') });
      // Give the UI a paint opportunity between expensive 768px renders.
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    }
    return images;
  } finally {
    disposeScene(scene);
    renderer.dispose();
    renderer.forceContextLoss();
  }
}
