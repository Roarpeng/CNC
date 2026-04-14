import { useMemo } from 'react';
import * as THREE from 'three';

export interface ToolpathSegment {
  type: 'G0' | 'G1';
  from: [number, number, number];
  to: [number, number, number];
}

interface ToolpathViewerProps {
  segments: ToolpathSegment[];
  visible?: boolean;
}

const COLORS = {
  G0: new THREE.Color('#ef4444'), // 快速移动 — 红色
  G1: new THREE.Color('#22d3ee'), // 切削进给 — 青色
};

const DASH_SCALE = 0.3;

export default function ToolpathViewer({ segments, visible = true }: ToolpathViewerProps) {
  const { rapidLines, feedLines } = useMemo(() => {
    const rapid: number[] = [];
    const feed: number[] = [];

    for (const seg of segments) {
      const arr = seg.type === 'G0' ? rapid : feed;
      arr.push(...seg.from, ...seg.to);
    }

    return {
      rapidLines: new Float32Array(rapid),
      feedLines: new Float32Array(feed),
    };
  }, [segments]);

  if (!visible || segments.length === 0) return null;

  return (
    <group>
      {/* G0 快速移动 — 红色虚线 */}
      {rapidLines.length > 0 && (
        <lineSegments>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              args={[rapidLines, 3]}
            />
          </bufferGeometry>
          <lineDashedMaterial
            color={COLORS.G0}
            dashSize={DASH_SCALE}
            gapSize={DASH_SCALE}
            linewidth={1}
            transparent
            opacity={0.7}
          />
        </lineSegments>
      )}

      {/* G1 切削进给 — 青色实线 */}
      {feedLines.length > 0 && (
        <lineSegments>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              args={[feedLines, 3]}
            />
          </bufferGeometry>
          <lineBasicMaterial color={COLORS.G1} linewidth={2} />
        </lineSegments>
      )}

      {/* 起点标记球 */}
      {segments.length > 0 && (
        <mesh position={segments[0].from}>
          <sphereGeometry args={[0.5, 16, 16]} />
          <meshBasicMaterial color="#4ade80" />
        </mesh>
      )}

      {/* 终点标记球 */}
      {segments.length > 0 && (
        <mesh position={segments[segments.length - 1].to}>
          <sphereGeometry args={[0.5, 16, 16]} />
          <meshBasicMaterial color="#f87171" />
        </mesh>
      )}
    </group>
  );
}
