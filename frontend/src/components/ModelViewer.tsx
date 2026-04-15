import { Suspense, useMemo, useState, useCallback } from 'react';
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

function normalizeToolpathToModelSpace(segments: ToolpathSegment[], bounds: THREE.Box3) {
  if (segments.length === 0) return segments;

  const isMachineCoordinatePath = segments.some((segment) => segment.from[2] < -1e-6 || segment.to[2] < -1e-6);
  if (!isMachineCoordinatePath) return segments;

  const toModelPoint = ([x, y, z]: [number, number, number]): [number, number, number] => [
    bounds.min.x + x,
    bounds.min.y + y,
    bounds.max.z + z,
  ];

  return segments.map((segment) => ({
    ...segment,
    from: toModelPoint(segment.from),
    to: toModelPoint(segment.to),
  }));
}

function getObjectBounds(object3d: THREE.Group | THREE.BufferGeometry) {
  if (object3d instanceof THREE.BufferGeometry) {
    const geometry = object3d.clone();
    geometry.computeBoundingBox();
    return geometry.boundingBox?.clone() ?? new THREE.Box3();
  }

  return new THREE.Box3().setFromObject(object3d);
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
function FaceHighlight({ face }: { face: SelectedFace }) {
  const discRadius = 3;
  // 在选中面中心画一个半透明圆盘表示装夹面
  const quaternion = useMemo(() => {
    const q = new THREE.Quaternion();
    q.setFromUnitVectors(new THREE.Vector3(0, 0, 1), face.normal.clone().normalize());
    return q;
  }, [face]);

  return (
    <group position={face.center} quaternion={quaternion}>
      {/* 装夹面指示盘 */}
      <mesh>
        <circleGeometry args={[discRadius, 32]} />
        <meshBasicMaterial color="#f59e0b" transparent opacity={0.35} side={THREE.DoubleSide} depthWrite={false} />
      </mesh>
      {/* 法向箭头 */}
      <arrowHelper args={[new THREE.Vector3(0, 0, 1), new THREE.Vector3(0, 0, 0), 8, 0xf59e0b, 2, 1]} />
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
  const normalizedToolpath = useMemo(
    () => normalizeToolpathToModelSpace(toolpathSegments ?? [], objectBounds),
    [toolpathSegments, objectBounds],
  );

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
      const container = e.eventObject;
      const worldToPlaced = container.matrixWorld.clone().invert();
      const worldNormalToPlaced = new THREE.Matrix3().getNormalMatrix(worldToPlaced);

      const normal = hit.face.normal.clone();
      if (hit.object instanceof THREE.Mesh) {
        normal.transformDirection(hit.object.matrixWorld);
      }

      normal.applyMatrix3(worldNormalToPlaced).normalize();

      const face: SelectedFace = {
        faceIndex: hit.faceIndex ?? 0,
        normal,
        center: hit.point.clone().applyMatrix4(worldToPlaced),
      };
      onFaceSelect?.(face);
    }

    if (mode === 'measure') {
      const pt = hit.point.clone();
      setMeasurePoints(prev => {
        if (prev.length >= 2) {
          // 重新开始
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

  return (
    <Bounds fit clip observe margin={1.2}>
      <group onClick={handleClick}>
        <group position={placement.position} quaternion={placement.rotation}>
          {object3d instanceof THREE.BufferGeometry ? (
            <mesh geometry={object3d} material={material} castShadow receiveShadow />
          ) : renderObject ? (
            <primitive object={renderObject} />
          ) : null}

          {selectedFace && <FaceHighlight face={selectedFace} />}

          {normalizedToolpath.length > 0 && (
            <ToolpathViewer segments={normalizedToolpath} visible={showToolpath} />
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
