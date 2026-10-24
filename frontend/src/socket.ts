/** Live socket: snapshots in, viewport out, reconnecting on its own. */

import type { BBox, ServerMessage } from "./types.ts";

type Handlers = {
  onMessage: (message: ServerMessage) => void;
  onStatus: (status: "connecting" | "open" | "closed") => void;
};

export class LiveSocket {
  private socket: WebSocket | null = null;
  private attempt = 0;
  private closedByUs = false;
  private timer: number | undefined;
  /** Remembered so a reconnect restores the viewport the user is looking at. */
  private bbox: BBox | null = null;

  private readonly userId: string;
  private readonly handlers: Handlers;

  // assigned in the body rather than as parameter properties: the project
  // compiles with `erasableSyntaxOnly`, which forbids that shorthand
  constructor(userId: string, handlers: Handlers) {
    this.userId = userId;
    this.handlers = handlers;
  }

  connect(): void {
    this.closedByUs = false;
    this.handlers.onStatus("connecting");

    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const url = `${scheme}://${location.host}/ws/client?user_id=${encodeURIComponent(this.userId)}`;
    const socket = new WebSocket(url);
    this.socket = socket;

    socket.onopen = () => {
      this.attempt = 0;
      this.handlers.onStatus("open");
      if (this.bbox !== null) this.sendBBox(this.bbox);
    };

    socket.onmessage = (event: MessageEvent<string | Blob>) => {
      const deliver = (text: string) => {
        try {
          this.handlers.onMessage(JSON.parse(text) as ServerMessage);
        } catch (error) {
          console.error("Undecodable frame", error);
        }
      };
      if (typeof event.data === "string") deliver(event.data);
      else void event.data.text().then(deliver);
    };

    socket.onclose = () => {
      this.socket = null;
      this.handlers.onStatus("closed");
      if (this.closedByUs) return;
      // the server closes with 1013 when this client is too slow for alerts;
      // reconnecting (and backfilling over REST) is the intended answer
      this.attempt += 1;
      const delay = Math.min(10_000, 500 * 2 ** (this.attempt - 1));
      this.timer = window.setTimeout(() => this.connect(), delay);
    };
  }

  close(): void {
    this.closedByUs = true;
    window.clearTimeout(this.timer);
    this.socket?.close();
    this.socket = null;
  }

  /** `null` asks for the whole fleet; a box asks the server to filter. */
  sendBBox(bbox: BBox | null): void {
    this.bbox = bbox;
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: "bbox", bbox }));
    }
  }
}
