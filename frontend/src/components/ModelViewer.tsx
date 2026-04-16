import { Suspense, useMemo, useState, useCallback, useRef, useEffect } from 'react';
import { Canvas, type ThreeEvent } from '@react-three/fiber';
import { Bounds, Environment, GizmoHelper, GizmoViewport, Html, Line, TrackballControls } from '@react-three/drei';
import { OBJLoader } from 'three-stdlib';
import { STLLoader } from 'three-stdlib';
import { GLTFLoader } from 'three-stdlib';
import { useLoader } from '@react-three/fiber';
import * as THREE from 'three';
import ToolpathViewer, { type ToolpathSegment } from './ToolpathViewer';

/* ===== 类型定义 ===== */
export type InteractionMode = 'orbit' | 'measure' | 'select_face';

export interface SelectedFace {
  faceIndex: number;
  normal: THREE.Vector3;
  center: THREE.Vector3;
}

export interface MeasureResult {
  p1: THREE.Vector3;
  p2: THREE.Vector3;
  distance: number;
}

interface HighlightData {
  geometry: THREE.BufferGeometry;
  centroid: THREE.Vector3;
  normal: THREE.Vector3;
}

export interface ModelViewerProps {
  renderUrl: string;
  topology: any;
  mode: InteractionMode;
  toolpathSegments?: ToolpathSegment[];
  showToolpath?: boolean;
  onFaceSelect?: (face: SelectedFace) => void;
  onMeasure?: (result: MeasureResult) => void;
  selectedFace?: SelectedFace | null;
}

const WORLD_DOWN = new THREE.Vector3(0, 0, -1);

function toBoxCorners(bounds: THREE.Box3) {
  return [
    new THREE.Vector3(bounds.min.x, bounds.min.y, bounds.min.z),
    new THREE.Vector3(bounds.min.x, bounds.min.y, bounds.max.z),
    new THREE.Vector3(bounds.min.x, bounds.max.y, bounds.min.z),
    new THREE.Vector3(bounds.min.x, bounds.max.y, bounds.max.z),
    new THREE.Vector3(bounds.max.x, bounds.min.y, bounds.min.z),
    new THREE.Vector3(bounds.max.x, bounds.min.y, bounds.max.z),
    new THREE.Vector3(bounds.max.x, bounds.max.y, bounds.min.z),
    new THREE.Vector3(bounds.max.x, bounds.max.y, bounds.max.z),
  ];
}

function buildPlacement(bounds: THREE.Box3, selectedFace?: SelectedFace | null) {
  const rotation = new THREE.Quaternion();
  if (selectedFace) {
    rotation.setFromUnitVectors(selectedFace.normal.clone().normalize(), WORLD_DOWN);
  }

  const rotatedBounds = new THREE.Box3();
  for (const corner of toBoxCorners(bounds)) {
    rotatedBounds.expandByPoint(corner.applyQuaternion(rotation));
  }

  const position = new THREE.Vector3(
    -(rotatedBounds.min.x + rotatedBounds.max.x) * 0.5,
    -(rotatedBounds.min.y + rotatedBounds.max.y) * 0.5,
    -rotatedBounds.min.z,
  );

  return { rotation, position };
}


function getObjectBounds(object3d: THREE.Group | THREE.BufferGeometry) {
  if (object3d instanceof THREE.BufferGeometry) {
    const geometry = object3d.clone();
    geometry.computeBoundingBox();
    return geometry.boundingBox?.clone() ?? new THREE.Box3();
  }

  return new THREE.Box3().setFromObject(object3d);
}

/* ===== 面高亮辅助 ===== */
const COPLANAR_DOT_THRESHOLD = 0.996; // cos(~5°)
const MAX_FLOOD_TRIANGLES = 50000;

function collectCoplanarFaceIndices(
  geometry: THREE.BufferGeometry,
  startFace: number,
  refNormal: THREE.Vector3,
): number[] {
  const posAttr = geometry.getAttribute('position') as THREE.BufferAttribute;
  const indexAttr = geometry.getIndex();
  const triCount = indexAttr ? indexAttr.count / 3 : posAttr.count / 3;
  if (startFace >= triCount) return [startFace];

  const vi = (tri: number, vert: number): number =>
    indexAttr ? indexAttr.getX(tri * 3 + vert) : tri * 3 + vert;

  const s = 1e4;
  const vkey = (idx: number): string =>
    `${Math.round(posAttr.getX(idx) * s)},${Math.round(posAttr.getY(idx) * s)},${Math.round(posAttr.getZ(idx) * s)}`;

  const ekey = (a: number, b: number): string => {
    const ka = vkey(a), kb = vkey(b);
    return ka < kb ? `${ka}|${kb}` : `${kb}|${ka}`;
  };

  const edge2tris = new Map<string, number[]>();
  for (let t = 0; t < triCount; t++) {
    const a = vi(t, 0), b = vi(t, 1), c = vi(t, 2);
    for (const ek of [ekey(a, b), ekey(b, c), ekey(c, a)]) {
      const arr = edge2tris.get(ek);
      if (arr) arr.push(t);
      else edge2tris.set(ek, [t]);
    }
  }

  const _a = new THREE.Vector3(), _b = new THREE.Vector3(), _c = new THREE.Vector3();
  const triNormal = (t: number): THREE.Vector3 => {
    _a.fromBufferAttribute(posAttr, vi(t, 0));
    _b.fromBufferAttribute(posAttr, vi(t, 1));
    _c.fromBufferAttribute(posAttr, vi(t, 2));
    const cross = new THREE.Vector3().crossVectors(
      _b.clone().sub(_a), _c.clone().sub(_a),
    );
    return cross.lengthSq() > 1e-12 ? cross.normalize() : new THREE.Vector3(0, 0, 1);
  };

  const visited = new Set<number>([startFace]);
  const queue = [startFace];
  const result: number[] = [];

  while (queue.length > 0 && result.length < MAX_FLOOD_TRIANGLES) {
    const cur = queue.shift()!;
    const n = triNormal(cur);
    if (n.dot(refNormal) < COPLANAR_DOT_THRESHOLD) continue;
    result.push(cur);

    const a = vi(cur, 0), b = vi(cur, 1), c = vi(cur, 2);
    for (const ek of [ekey(a, b), ekey(b, c), ekey(c, a)]) {
      for (const neighbor of edge2tris.get(ek) ?? []) {
        if (!visited.has(neighbor)) {
          visited.add(neighbor);
          queue.push(neighbor);
        }
      }
    }
  }

  return result.length > 0 ? result : [startFace];
}

function buildHighlightGeometry(
  srcGeometry: THREE.BufferGeometry,
  faceIndices: number[],
): THREE.BufferGeometry {
  const posAttr = srcGeometry.getAttribute('position') as THREE.BufferAttribute;
  const indexAttr = srcGeometry.getIndex();
  const vi = (tri: number, vert: number): number =>
    indexAttr ? indexAttr.getX(tri * 3 + vert) : tri * 3 + vert;

  const positions = new Float32Array(faceIndices.length * 9);
  let offset = 0;
  for (const fi of faceIndices) {
    for (let v = 0; v < 3; v++) {
      const idx = vi(fi, v);
      positions[offset++] = posAttr.getX(idx);
      positions[offset++] = posAttr.getY(idx);
      positions[offset++] = posAttr.getZ(idx);
    }
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  return geo;
}

/* ===== 加载提示 ===== */
function LoadingSpinner() {
  return (
    <Html center>
      <div className="flex flex-col items-center gap-2 text-slate-400">
        <svg className="w-8 h-8 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="10" strokeOpacity="0.2" />
          <path d="M12 2a10 10 0 0 1 10 10" strokeLinecap="round" />
        </svg>
        <span className="text-xs font-medium whitespace-nowrap">加载模型中...</span>
      </div>
    </Html>
  );
}

/* ===== 面高亮 ===== */
const highlightMaterial = new THREE.MeshBasicMaterial({
  color: 0xf59e0b,
  transparent: true,
  opacity: 0.4,
  side: THREE.DoubleSide,
  depthWrite: false,
  polygonOffset: true,
  polygonOffsetFactor: -1,
  polygonOffsetUnits: -1,
});

function FaceHighlight({ highlight, arrowScale }: {
  highlight: HighlightData;
  arrowScale: number;
}) {
  const arrowLen = Math.max(arrowScale * 0.2, 1);
  return (
    <group>
      <mesh geometry={highlight.geometry} material={highlightMaterial} />
      <arrowHelper args={[
        highlight.normal.clone().negate().normalize(),
        highlight.centroid,
        arrowLen,
        0xf59e0b,
        arrowLen * 0.25,
        arrowLen * 0.12,
      ]} />
    </group>
  );
}

/* ===== 测量线 ===== */
function MeasureLine({ p1, p2 }: { p1: THREE.Vector3; p2: THREE.Vector3 }) {
  const mid = useMemo(() => p1.clone().add(p2).multiplyScalar(0.5), [p1, p2]);
  const dist = useMemo(() => p1.distanceTo(p2), [p1, p2]);

  return (
    <group>
      <Line points={[p1, p2]} color="#facc15" lineWidth={2} />
      {/* 端点标记 */}
      <mesh position={p1}><sphereGeometry args={[0.4, 12, 12]} /><meshBasicMaterial color="#facc15" /></mesh>
      <mesh position={p2}><sphereGeometry args={[0.4, 12, 12]} /><meshBasicMaterial color="#facc15" /></mesh>
      {/* 距离标签 */}
      <Html position={mid} center>
        <div className="bg-slate-900/90 border border-yellow-500/60 rounded px-2 py-0.5 text-yellow-400 text-xs font-mono whitespace-nowrap select-none pointer-events-none">
          {dist.toFixed(2)} mm
        </div>
      </Html>
    </group>
  );
}

/* ===== 单点标记 (测量第一击) ===== */
function PointMarker({ point }: { point: THREE.Vector3 }) {
  return (
    <mesh position={point}>
      <sphereGeometry args={[0.5, 12, 12]} />
      <meshBasicMaterial color="#facc15" />
    </mesh>
  );
}

/* ===== 交互式模型 ===== */
function InteractiveModel({
  url, mode, onFaceSelect, onMeasure, setMeasurePoints, selectedFace, toolpathSegments, showToolpath,
}: {
  url: string;
  mode: InteractionMode;
  onFaceSelect?: (face: SelectedFace) => void;
  onMeasure?: (result: MeasureResult) => void;
  setMeasurePoints: React.Dispatch<React.SetStateAction<THREE.Vector3[]>>;
  selectedFace?: SelectedFace | null;
  toolpathSegments?: ToolpathSegment[];
  showToolpath: boolean;
}) {
  const placedRef = useRef<THREE.Group>(null!);
  const [highlight, setHighlight] = useState<HighlightData | null>(null);

  const ext = useMemo(() => url.split('?')[0].split('.').pop()?.toLowerCase() ?? 'obj', [url]);
  const loaderClass = useMemo(() => {
    if (ext === 'stl') return STLLoader;
    if (ext === 'glb' || ext === 'gltf') return GLTFLoader;
    return OBJLoader;
  }, [ext]);
  const loaded = useLoader(loaderClass as any, url) as THREE.Group | THREE.BufferGeometry | { scene: THREE.Group };
  const object3d = useMemo(() => {
    if ((loaded as { scene?: THREE.Group }).scene) return (loaded as { scene: THREE.Group }).scene;
    return loaded as THREE.Group | THREE.BufferGeometry;
  }, [loaded]);
  const objectBounds = useMemo(() => getObjectBounds(object3d), [object3d]);
  const placement = useMemo(() => buildPlacement(objectBounds, selectedFace), [objectBounds, selectedFace]);

  const modelSize = useMemo(() => {
    const size = new THREE.Vector3();
    objectBounds.getSize(size);
    return Math.max(size.x, size.y, size.z);
  }, [objectBounds]);

  useEffect(() => {
    if (!selectedFace) setHighlight(null);
  }, [selectedFace]);

  useEffect(() => {
    return () => { highlight?.geometry.dispose(); };
  }, [highlight]);

  const material = useMemo(() => new THREE.MeshStandardMaterial({
    color: '#94a3b8',
    metalness: 0.6,
    roughness: 0.3,
    envMapIntensity: 1,
  }), []);

  const renderObject = useMemo(() => {
    if (object3d instanceof THREE.BufferGeometry) return null;

    const clone = object3d.clone(true);
    clone.traverse((child) => {
      if ((child as THREE.Mesh).isMesh) {
        const mesh = child as THREE.Mesh;
        mesh.material = material;
        mesh.castShadow = true;
        mesh.receiveShadow = true;
      }
    });
    return clone;
  }, [object3d, material]);

  const handleClick = useCallback((e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    if (mode === 'orbit') return;

    const hit = e.intersections[0];
    if (!hit || !hit.face) return;

    if (mode === 'select_face') {
      const hitMesh = hit.object as THREE.Mesh;
      const hitGeometry = hitMesh.geometry as THREE.BufferGeometry;
      const faceIdx = hit.faceIndex ?? 0;

      const placedWorldInv = placedRef.current.matrixWorld.clone().invert();
      const hitToModel = placedWorldInv.clone().multiply(hitMesh.matrixWorld);
      const normalMat3 = new THREE.Matrix3().getNormalMatrix(hitToModel);

      const modelNormal = hit.face.normal.clone();
      modelNormal.applyMatrix3(normalMat3).normalize();
      const modelCenter = hit.point.clone().applyMatrix4(placedWorldInv);

      const face: SelectedFace = {
        faceIndex: faceIdx,
        normal: modelNormal,
        center: modelCenter,
      };
      onFaceSelect?.(face);

      const localNormal = hit.face.normal.clone();
      const faceIndices = collectCoplanarFaceIndices(hitGeometry, faceIdx, localNormal);
      const highlightGeo = buildHighlightGeometry(hitGeometry, faceIndices);
      highlightGeo.applyMatrix4(hitToModel);

      highlightGeo.computeBoundingBox();
      const centroid = new THREE.Vector3();
      highlightGeo.boundingBox!.getCenter(centroid);

      setHighlight({
        geometry: highlightGeo,
        centroid,
        normal: modelNormal.clone(),
      });
    }

    if (mode === 'measure') {
      const pt = hit.point.clone();
      setMeasurePoints(prev => {
        if (prev.length >= 2) {
          return [pt];
        }
        const next = [...prev, pt];
        if (next.length === 2) {
          onMeasure?.({ p1: next[0], p2: next[1], distance: next[0].distanceTo(next[1]) });
        }
        return next;
      });
    }
  }, [mode, onFaceSelect, onMeasure, setMeasurePoints]);

  const segments = toolpathSegments ?? [];

  return (
    <Bounds fit clip observe margin={1.2}>
      <group onClick={handleClick}>
        <group ref={placedRef} position={placement.position} quaternion={placement.rotation}>
          {object3d instanceof THREE.BufferGeometry ? (
            <mesh geometry={object3d} material={material} castShadow receiveShadow />
          ) : renderObject ? (
            <primitive object={renderObject} />
          ) : null}

          {highlight && <FaceHighlight highlight={highlight} arrowScale={modelSize} />}

          {segments.length > 0 && (
            <ToolpathViewer segments={segments} visible={showToolpath} />
          )}
        </group>
      </group>
    </Bounds>
  );
}

/* ===== 主组件 ===== */
export default function ModelViewer({
  renderUrl, mode, toolpathSegments, showToolpath = true,
  onFaceSelect, onMeasure, selectedFace,
}: ModelViewerProps) {
  const [measurePoints, setMeasurePoints] = useState<THREE.Vector3[]>([]);

  return (
    <Canvas shadows camera={{ position: [50, 50, 50], fov: 45 }}>
      <color attach="background" args={['#0f172a']} />
      <ambientLight intensity={0.7} />
      <directionalLight position={[80, 120, 60]} intensity={1.2} castShadow />
      <Environment preset="city" />

      <Suspense fallback={<LoadingSpinner />}>
        <InteractiveModel
          url={renderUrl}
          mode={mode}
          onFaceSelect={onFaceSelect}
          onMeasure={onMeasure}
          setMeasurePoints={setMeasurePoints}
          selectedFace={selectedFace}
          toolpathSegments={toolpathSegments}
          showToolpath={showToolpath}
        />

        {/* 测量辅助 */}
        {measurePoints.length === 1 && <PointMarker point={measurePoints[0]} />}
        {measurePoints.length === 2 && <MeasureLine p1={measurePoints[0]} p2={measurePoints[1]} />}
      </Suspense>

      <TrackballControls makeDefault noPan={mode !== 'orbit'} />

      <GizmoHelper alignment="bottom-right" margin={[80, 80]}>
        <GizmoViewport labelColor="white" axisHeadScale={1} />
      </GizmoHelper>
    </Canvas>
  );
}
