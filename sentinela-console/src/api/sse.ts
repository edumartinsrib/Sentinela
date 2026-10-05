// SSE sobre fetch + ReadableStream (não EventSource), para poder enviar o cabeçalho de
// autenticação. Reconecta com backoff exponencial e ignora os comentários `: ping`.

import { useSyncExternalStore } from 'react';
import { API_BASE, authHeaders, notifyUnauthorized } from './client';

export type StreamStatus = 'connecting' | 'open' | 'reconnecting' | 'closed';

export interface StreamHandlers {
  onEvent: (type: string, data: unknown) => void;
  onStatus?: (status: StreamStatus) => void;
}

const MAX_BACKOFF_MS = 30_000;

export async function readEventStream(
  body: ReadableStream<Uint8Array>,
  onEvent: (type: string, data: unknown) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let eventType = '';
  let dataLines: string[] = [];

  const dispatch = () => {
    if (dataLines.length) {
      const raw = dataLines.join('\n');
      let parsed: unknown = raw;
      try {
        parsed = JSON.parse(raw);
      } catch {
        // dado não-JSON: entrega o texto cru
      }
      onEvent(eventType || 'message', parsed);
    }
    eventType = '';
    dataLines = [];
  };

  const processLine = (rawLine: string) => {
    const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;
    if (line === '') {
      dispatch();
      return;
    }
    if (line.startsWith(':')) return;
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === 'event') eventType = value;
    else if (field === 'data') dataLines.push(value);
  };

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newline = buffer.indexOf('\n');
    while (newline !== -1) {
      processLine(buffer.slice(0, newline));
      buffer = buffer.slice(newline + 1);
      newline = buffer.indexOf('\n');
    }
  }
  buffer += decoder.decode();
  if (buffer) processLine(buffer);
  dispatch();
}

/** Abre um stream SSE autenticado. Retorna a função que fecha a conexão. */
export function openStream(path: string, handlers: StreamHandlers): () => void {
  let closed = false;
  let attempt = 0;
  let controller: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const scheduleReconnect = () => {
    if (closed) return;
    attempt += 1;
    const base = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** (attempt - 1));
    handlers.onStatus?.('reconnecting');
    timer = setTimeout(connect, base * (0.8 + Math.random() * 0.4));
  };

  async function connect() {
    if (closed) return;
    controller = new AbortController();
    handlers.onStatus?.(attempt === 0 ? 'connecting' : 'reconnecting');
    try {
      const headers = { Accept: 'text/event-stream', ...(await authHeaders()) };
      const res = await fetch(`${API_BASE}${path}`, { headers, signal: controller.signal, cache: 'no-store' });
      if (res.status === 401) {
        notifyUnauthorized();
        throw new Error('401');
      }
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
      attempt = 0;
      handlers.onStatus?.('open');
      await readEventStream(res.body, handlers.onEvent);
    } catch {
      if (closed) return;
    }
    scheduleReconnect();
  }

  void connect();

  return () => {
    closed = true;
    if (timer) clearTimeout(timer);
    controller?.abort();
    handlers.onStatus?.('closed');
  };
}

// ---------------------------------------------------------------- status global da conexão
let globalStatus: StreamStatus = 'closed';
const statusListeners = new Set<() => void>();

export function setGlobalStreamStatus(status: StreamStatus): void {
  if (status === globalStatus) return;
  globalStatus = status;
  statusListeners.forEach((l) => l());
}

export function useGlobalStreamStatus(): StreamStatus {
  return useSyncExternalStore(
    (cb) => {
      statusListeners.add(cb);
      return () => statusListeners.delete(cb);
    },
    () => globalStatus,
  );
}
