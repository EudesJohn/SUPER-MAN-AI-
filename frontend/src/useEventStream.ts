import { useEffect, useRef, useState } from "react";
import type { BusEvent } from "./api";

/**
 * Live event feed over WebSocket (spec section 29: real-time display of what
 * the agents are doing). Auto-reconnects; keeps the last 500 events.
 */
export function useEventStream(): { events: BusEvent[]; connected: boolean } {
  const [events, setEvents] = useState<BusEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let closedByUs = false;
    let retry: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/ws/events`);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!closedByUs) retry = setTimeout(connect, 2000); // auto-reconnect
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (msg) => {
        try {
          const event = JSON.parse(msg.data as string) as BusEvent;
          setEvents((prev) => [...prev.slice(-499), event]);
        } catch {
          /* ignore malformed frames */
        }
      };
    };

    connect();
    return () => {
      closedByUs = true;
      if (retry) clearTimeout(retry);
      wsRef.current?.close();
    };
  }, []);

  return { events, connected };
}
