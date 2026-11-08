import { useEffect, useRef } from "react";
import { useStore } from "../lib/store";

/**
 * JARVIS's living orb, drawn on canvas.
 *  idle      – slow breathing glow
 *  listening – surface ripples with the microphone level
 *  thinking  – swirling orbiting particles
 *  speaking  – waveform rings driven by JARVIS's voice
 */
export default function Orb({ size = 220, onClick }: { size?: number; onClick?: () => void }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current!;
    const ctx = canvas.getContext("2d")!;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const S = size * 1.6; // extra room for glow/rings
    canvas.width = S * dpr;
    canvas.height = S * dpr;
    ctx.scale(dpr, dpr);
    let raf = 0;
    let t = 0;
    let smooth = 0;
    let stateMix = { listening: 0, thinking: 0, speaking: 0 };
    const particles = Array.from({ length: 36 }, (_, i) => ({ a: (i / 36) * Math.PI * 2, r: 0.62 + Math.random() * 0.35, s: 0.4 + Math.random() * 0.9, z: Math.random() }));

    const draw = () => {
      const { orb, level } = useStore.getState();
      t += 0.016;
      smooth += (level - smooth) * 0.25;
      const target = { listening: orb === "listening" ? 1 : 0, thinking: orb === "thinking" ? 1 : 0, speaking: orb === "speaking" ? 1 : 0 };
      (Object.keys(stateMix) as (keyof typeof stateMix)[]).forEach((k) => (stateMix[k] += (target[k] - stateMix[k]) * 0.06));

      const cx = S / 2, cy = S / 2;
      const base = size * 0.36;
      const breathe = 1 + Math.sin(t * 1.4) * 0.025;
      const R = base * breathe * (1 + smooth * 0.12 * (stateMix.listening + stateMix.speaking));
      ctx.clearRect(0, 0, S, S);

      // outer glow
      const glow = ctx.createRadialGradient(cx, cy, R * 0.6, cx, cy, R * 2.1);
      const ga = 0.28 + smooth * 0.25 + stateMix.thinking * 0.1;
      glow.addColorStop(0, `rgba(99,102,241,${ga})`);
      glow.addColorStop(0.5, `rgba(59,130,246,${ga * 0.35})`);
      glow.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, S, S);

      // speaking rings
      if (stateMix.speaking > 0.02) {
        for (let i = 0; i < 3; i++) {
          const p = ((t * 0.6 + i / 3) % 1);
          ctx.beginPath();
          ctx.arc(cx, cy, R * (1.05 + p * 0.8 + smooth * 0.2), 0, Math.PI * 2);
          ctx.strokeStyle = `rgba(167,139,250,${(1 - p) * 0.35 * stateMix.speaking})`;
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }
      }

      // blob surface
      const amp = 0.025 + stateMix.listening * (0.04 + smooth * 0.18) + stateMix.speaking * (0.03 + smooth * 0.14) + stateMix.thinking * 0.05;
      const pts = 96;
      ctx.beginPath();
      for (let i = 0; i <= pts; i++) {
        const a = (i / pts) * Math.PI * 2;
        const n = Math.sin(a * 3 + t * 2.1) * 0.5 + Math.sin(a * 5 - t * 1.7) * 0.3 + Math.sin(a * 7 + t * 3.3) * 0.2 * (stateMix.listening + stateMix.speaking);
        const r = R * (1 + n * amp);
        const x = cx + Math.cos(a) * r, y = cy + Math.sin(a) * r;
        i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.closePath();
      const body = ctx.createRadialGradient(cx - R * 0.35, cy - R * 0.4, R * 0.05, cx, cy, R * 1.05);
      const swirl = stateMix.thinking * Math.sin(t * 3) * 20;
      body.addColorStop(0, "rgba(224,231,255,0.95)");
      body.addColorStop(0.25, `hsla(${215 + swirl}, 95%, 66%, 0.95)`);
      body.addColorStop(0.65, `hsla(${258 + swirl}, 85%, 55%, 0.92)`);
      body.addColorStop(1, "rgba(30,27,75,0.9)");
      ctx.fillStyle = body;
      ctx.shadowColor = "rgba(129,140,248,0.8)";
      ctx.shadowBlur = 30 + smooth * 30;
      ctx.fill();
      ctx.shadowBlur = 0;

      // inner sheen
      ctx.save();
      ctx.clip();
      ctx.globalCompositeOperation = "screen";
      for (let k = 0; k < 2; k++) {
        const ang = t * (0.4 + k * 0.3) + k * 2;
        const gx = cx + Math.cos(ang) * R * 0.45, gy = cy + Math.sin(ang * 1.3) * R * 0.45;
        const g = ctx.createRadialGradient(gx, gy, 0, gx, gy, R * 0.8);
        g.addColorStop(0, k ? "rgba(34,211,238,0.25)" : "rgba(217,70,239,0.22)");
        g.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = g;
        ctx.fillRect(cx - R * 1.5, cy - R * 1.5, R * 3, R * 3);
      }
      ctx.restore();

      // thinking particles
      if (stateMix.thinking > 0.02) {
        particles.forEach((p) => {
          p.a += 0.02 * p.s;
          const rr = R * (1.15 + p.r * 0.5);
          const x = cx + Math.cos(p.a) * rr, y = cy + Math.sin(p.a) * rr * (0.55 + p.z * 0.45);
          ctx.beginPath();
          ctx.arc(x, y, 1.2 + p.z * 1.6, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(165,180,252,${0.65 * stateMix.thinking * (0.4 + p.z * 0.6)})`;
          ctx.fill();
        });
      }

      // listening equaliser ring
      if (stateMix.listening > 0.02) {
        const bars = 64;
        for (let i = 0; i < bars; i++) {
          const a = (i / bars) * Math.PI * 2;
          const h = (4 + smooth * 26 * (0.5 + 0.5 * Math.sin(a * 6 + t * 8))) * stateMix.listening;
          const r1 = R * 1.18;
          ctx.beginPath();
          ctx.moveTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1);
          ctx.lineTo(cx + Math.cos(a) * (r1 + h), cy + Math.sin(a) * (r1 + h));
          ctx.strokeStyle = `rgba(56,189,248,${0.6 * stateMix.listening})`;
          ctx.lineWidth = 2;
          ctx.lineCap = "round";
          ctx.stroke();
        }
      }
      raf = requestAnimationFrame(draw);
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, [size]);

  return (
    <canvas
      ref={ref}
      onClick={onClick}
      style={{ width: size * 1.6, height: size * 1.6, margin: -size * 0.3 }}
      className={onClick ? "cursor-pointer select-none" : "select-none"}
      aria-label="JARVIS orb"
      role={onClick ? "button" : "img"}
    />
  );
}
