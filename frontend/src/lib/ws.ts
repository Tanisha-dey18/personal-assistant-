import { getToken, wsUrl } from "./api";

export type ServerEvent =
  | { type: "ready" }
  | { type: "pong" }
  | { type: "start"; conversation_id: string; user_message_id: string; mode: string; mode_source: string; title: string }
  | { type: "context"; memories: any[]; past_conversations: any[]; documents: any[] }
  | { type: "token"; content: string }
  | { type: "tool"; name: string; status: string; args?: any; error?: string }
  | { type: "pending_action"; action: any }
  | { type: "done"; message: any; conversation_id: string }
  | { type: "title"; conversation_id: string; title: string }
  | { type: "memory_update"; created: any[]; updated: any[]; pending: any[] }
  | { type: "error"; message: string; code?: string };

type Listener = (e: ServerEvent) => void;

/** Persistent, auto-reconnecting chat socket. Auth is sent as the first message (not in the URL). */
export class ChatSocket {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private queue: string[] = [];
  private ready = false;
  private closed = false;
  private retry = 0;
  private pingTimer?: number;
  status: "connecting" | "online" | "offline" = "connecting";
  onStatus?: (s: ChatSocket["status"]) => void;

  connect() {
    this.closed = false;
    this.setStatus("connecting");
    const ws = new WebSocket(wsUrl("/api/chat/ws"));
    this.ws = ws;
    ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token: getToken() }));
    ws.onmessage = (m) => {
      const ev = JSON.parse(m.data) as ServerEvent;
      if (ev.type === "ready") {
        this.ready = true;
        this.retry = 0;
        this.setStatus("online");
        this.queue.splice(0).forEach((q) => ws.send(q));
        this.pingTimer = window.setInterval(() => this.send({ type: "ping" }), 25000);
        return;
      }
      this.listeners.forEach((l) => l(ev));
    };
    ws.onclose = () => {
      this.ready = false;
      window.clearInterval(this.pingTimer);
      this.setStatus("offline");
      if (!this.closed) {
        const delay = Math.min(10000, 500 * 2 ** this.retry++);
        setTimeout(() => !this.closed && this.connect(), delay);
      }
    };
  }

  private setStatus(s: ChatSocket["status"]) {
    this.status = s;
    this.onStatus?.(s);
  }

  send(data: object) {
    const s = JSON.stringify(data);
    if (this.ready && this.ws?.readyState === WebSocket.OPEN) this.ws.send(s);
    else this.queue.push(s);
  }

  on(l: Listener) {
    this.listeners.add(l);
    return () => this.listeners.delete(l);
  }

  close() {
    this.closed = true;
    window.clearInterval(this.pingTimer);
    this.ws?.close();
  }
}
