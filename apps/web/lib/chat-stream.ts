import { API_URL, ApiError } from "./api";
import type { ChatEvent, ChatTurn } from "./types";

const TYPES = new Set<ChatEvent["type"]>(["token", "sources", "action", "done", "error"]);

export interface ChatRequest {
  message: string;
  history: ChatTurn[];
  trip_id?: string;
  client_id?: string;
}

/**
 * POST /api/chat and yield its SSE events. EventSource can't POST, so this reads the response body
 * and parses the `event:` / `data:` frames itself (sse-starlette separates lines with CRLF).
 */
export async function* streamChat(body: ChatRequest, signal: AbortSignal): AsyncGenerator<ChatEvent> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
      cache: "no-store",
    });
  } catch (err) {
    if (signal.aborted) throw err;
    throw new ApiError("unreachable", "Can't reach the planner right now — it may be waking up. Try again in a moment.");
  }
  if (!res.ok || !res.body) {
    let detail = `HTTP ${res.status}`;
    try {
      const data = (await res.json()) as { detail?: unknown };
      if (typeof data.detail === "string") detail = data.detail;
    } catch {
      /* non-JSON body */
    }
    const retry = Number(res.headers.get("Retry-After"));
    if (res.status === 429) {
      throw new ApiError("rate_limited", `You're sending messages quickly — try again in ${Number.isFinite(retry) && retry > 0 ? retry : 30} s.`, 429, retry);
    }
    throw new ApiError(res.status < 500 ? "bad_request" : "server", detail, res.status);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n?/g, "\n");
      let cut: number;
      while ((cut = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, cut);
        buffer = buffer.slice(cut + 2);
        let type = "message";
        const data: string[] = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith(":")) continue; // keep-alive comment
          if (line.startsWith("event:")) type = line.slice(6).trim();
          else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
        }
        if (!data.length || !TYPES.has(type as ChatEvent["type"])) continue;
        try {
          yield { type, data: JSON.parse(data.join("\n")) } as ChatEvent;
        } catch {
          /* malformed frame: skip */
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
