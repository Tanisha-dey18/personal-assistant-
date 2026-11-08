import { API_URL, api, getToken } from "./api";

/**
 * Push-to-talk recorder with automatic end-of-speech detection.
 * The microphone is only open between start() and stop() — there is no background listening.
 */
export class VoiceRecorder {
  private stream?: MediaStream;
  private recorder?: MediaRecorder;
  private ctx?: AudioContext;
  private raf = 0;
  private chunks: Blob[] = [];
  private resolve?: (b: Blob | null) => void;
  active = false;

  constructor(private onLevel: (n: number) => void, private onAutoStop?: () => void) {}

  async start(): Promise<Promise<Blob | null>> {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"].find((m) => MediaRecorder.isTypeSupported(m)) || "";
    this.recorder = new MediaRecorder(this.stream, mime ? { mimeType: mime } : undefined);
    this.chunks = [];
    this.recorder.ondataavailable = (e) => e.data.size && this.chunks.push(e.data);
    const done = new Promise<Blob | null>((res) => (this.resolve = res));
    this.recorder.onstop = () => {
      const blob = this.chunks.length ? new Blob(this.chunks, { type: this.recorder?.mimeType || "audio/webm" }) : null;
      this.cleanup();
      this.resolve?.(blob);
    };
    this.recorder.start(250);
    this.active = true;

    // level meter + silence detection
    this.ctx = new AudioContext();
    const src = this.ctx.createMediaStreamSource(this.stream);
    const an = this.ctx.createAnalyser();
    an.fftSize = 512;
    src.connect(an);
    const buf = new Uint8Array(an.fftSize);
    let spoke = false;
    let silentSince = performance.now();
    const started = performance.now();
    const tick = () => {
      an.getByteTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) sum += ((v - 128) / 128) ** 2;
      const rms = Math.sqrt(sum / buf.length);
      const level = Math.min(1, rms * 6);
      this.onLevel(level);
      const now = performance.now();
      if (level > 0.12) {
        spoke = true;
        silentSince = now;
      }
      const silentFor = now - silentSince;
      if ((spoke && silentFor > 1400) || (!spoke && now - started > 8000) || now - started > 60000) {
        this.onAutoStop?.();
        this.stop();
        return;
      }
      this.raf = requestAnimationFrame(tick);
    };
    tick();
    return done;
  }

  stop() {
    if (this.recorder && this.recorder.state !== "inactive") this.recorder.stop();
    else this.cleanup();
  }

  private cleanup() {
    cancelAnimationFrame(this.raf);
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close().catch(() => {});
    this.ctx = undefined;
    this.active = false;
    this.onLevel(0);
  }
}

export async function transcribe(blob: Blob): Promise<string> {
  const ext = blob.type.includes("mp4") ? "m4a" : blob.type.includes("ogg") ? "ogg" : "webm";
  const form = new FormData();
  form.append("file", blob, `speech.${ext}`);
  const r = await api<{ text: string }>("/api/voice/transcribe", { method: "POST", form });
  return r.text;
}

/** Turns markdown into something pleasant to hear. */
export function speakable(md: string): string {
  return md
    .replace(/```[\s\S]*?```/g, " I've put the code on screen. ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/^\s*[-*+]\s+/gm, "")
    .replace(/^\s*#+\s*/gm, "")
    .replace(/\|/g, " ")
    .replace(/[*_~>#]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** Interruptible TTS playback with an analyser so the orb can react to JARVIS's voice. */
export class VoicePlayer {
  private audio?: HTMLAudioElement;
  private ctx?: AudioContext;
  private raf = 0;
  private abort?: AbortController;
  playing = false;

  constructor(private onLevel: (n: number) => void) {}

  async speak(text: string, voice?: string, speed?: number): Promise<void> {
    this.stop();
    const clean = speakable(text).slice(0, 4000);
    if (!clean) return;
    this.playing = true;
    this.abort = new AbortController();
    try {
      const res = await fetch(`${API_URL}/api/voice/speak`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
        body: JSON.stringify({ text: clean, voice, speed }),
        signal: this.abort.signal,
      });
      if (!res.ok) throw new Error(`tts ${res.status}`);
      const blob = await res.blob();
      if (!this.playing) return;
      await this.playBlob(blob);
    } catch (e: any) {
      if (e?.name === "AbortError" || !this.playing) return;
      await this.browserFallback(clean); // server TTS unavailable → browser voice
    } finally {
      this.playing = false;
      this.onLevel(0);
    }
  }

  private playBlob(blob: Blob) {
    return new Promise<void>((resolve) => {
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      this.audio = audio;
      this.ctx = new AudioContext();
      const src = this.ctx.createMediaElementSource(audio);
      const an = this.ctx.createAnalyser();
      an.fftSize = 256;
      src.connect(an);
      an.connect(this.ctx.destination);
      const buf = new Uint8Array(an.frequencyBinCount);
      const tick = () => {
        an.getByteFrequencyData(buf);
        const avg = buf.reduce((a, b) => a + b, 0) / buf.length / 255;
        this.onLevel(Math.min(1, avg * 2.2));
        this.raf = requestAnimationFrame(tick);
      };
      const end = () => {
        cancelAnimationFrame(this.raf);
        URL.revokeObjectURL(url);
        this.ctx?.close().catch(() => {});
        resolve();
      };
      audio.onended = end;
      audio.onpause = end;
      audio.onerror = end;
      audio.play().then(tick).catch(end);
    });
  }

  private browserFallback(text: string) {
    return new Promise<void>((resolve) => {
      if (!("speechSynthesis" in window)) return resolve();
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 1.03;
      let t = 0;
      const pulse = () => {
        this.onLevel(0.3 + 0.25 * Math.abs(Math.sin((t += 0.25))));
        this.raf = requestAnimationFrame(pulse);
      };
      u.onstart = pulse;
      u.onend = u.onerror = () => {
        cancelAnimationFrame(this.raf);
        resolve();
      };
      speechSynthesis.speak(u);
    });
  }

  stop() {
    this.playing = false;
    this.abort?.abort();
    cancelAnimationFrame(this.raf);
    if (this.audio) {
      this.audio.pause();
      this.audio = undefined;
    }
    if ("speechSynthesis" in window) speechSynthesis.cancel();
    this.onLevel(0);
  }
}
