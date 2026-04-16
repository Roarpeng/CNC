import { useMemo } from 'react';
import * as THREE from 'three';

export interface ToolpathSegment {
  type: 'G0' | 'G1' | 'G2' | 'G3';
  from: [number, number, number];
  to: [number, number, number];
  center?: [number, number, number];
  radius?: number;
}

interface ToolpathViewerProps {
  segments: ToolpathSegment[];
  visible?: boolean;
}

const COLORS = {
  G0: new THREE.Color('#ef4444'),
  G1: new THREE.Color('#22d3ee'),
  ARC: new THREE.Color('#f59e0b'),
};

const DASH_SCALE = 0.3;
const ARC_STEPS = 24;

function tessellateArc(seg: ToolpathSegment): number[] {
  const points: number[] = [];
  const center = seg.center;
  if (!center || !seg.radius) {
    points.push(...seg.from, ...seg.to);
    return points;
  }

  const cx = center[0], cy = center[1];
  const r = seg.radius;
  const startAngle = Math.atan2(seg.from[1] - cy, seg.from[0] - cx);
  let endAngle = Math.atan2(seg.to[1] - cy, seg.to[0] - cx);

  const cw = seg.type === 'G2';
  if (cw) {
    while (endAngle >= startAngle) endAngle -= 2 * Math.PI;
  } else {
    while (endAngle <= startAngle) endAngle += 2 * Math.PI;
  }

  const zStart = seg.from[2];
  const zEnd = seg.to[2];

  for (let i = 0; i < ARC_STEPS; i++) {
    const t0 = i / ARC_STEPS;
    const t1 = (i + 1) / ARC_STEPS;
    const a0 = startAngle + (endAngle - startAngle) * t0;
    const a1 = startAngle + (endAngle - startAngle) * t1;
    const z0 = zStart + (zEnd - zStart) * t0;
    const z1 = zStart + (zEnd - zStart) * t1;
    points.push(
      cx + r * Math.cos(a0), cy + r * Math.sin(a0), z0,
      cx + r * Math.cos(a1), cy + r * Math.sin(a1), z1,
    );
  }
  return points;
}

export default function ToolpathViewer({ segments, visible = true }: ToolpathViewerProps) {
  const { rapidLines, feedLines, arcLines } = useMemo(() => {
    const rapid: number[] = [];
    const feed: number[] = [];
    const arc: number[] = [];

    for (const seg of segments) {
      if (seg.type === 'G0') {
        rapid.push(...seg.from, ...seg.to);
      } else if (seg.type === 'G1') {
        feed.push(...seg.from, ...seg.to);
      } else if (seg.type === 'G2' || seg.type === 'G3') {
        arc.push(...tessellateArc(seg));
      }
    }

    return {
      rapidLines: new Float32Array(rapid),
      feedLines: new Float32Array(feed),
      arcLines: new Float32Array(arc),
    };
  }, [segments]);

  if (!visible || segments.length === 0) return null;

  return (
    <group>
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

      {arcLines.length > 0 && (
        <lineSegments>
          <bufferGeometry>
            <bufferAttribute
              attach="attributes-position"
              args={[arcLines, 3]}
            />
          </bufferGeometry>
          <lineBasicMaterial color={COLORS.ARC} linewidth={2} />
        </lineSegments>
      )}

      {segments.length > 0 && (
        <mesh position={segments[0].from}>
          <sphereGeometry args={[0.5, 16, 16]} />
          <meshBasicMaterial color="#4ade80" />
        </mesh>
      )}

      {segments.length > 0 && (
        <mesh position={segments[segments.length - 1].to}>
          <sphereGeometry args={[0.5, 16, 16]} />
          <meshBasicMaterial color="#f87171" />
        </mesh>
      )}
    </group>
  );
}
