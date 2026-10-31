// POST + Server-Sent Events reader (EventSource only supports GET). Used by the batch view to receive one
// `batch_item` per farm as soon as it is ready.
import { API_URL } from "./api";

/** POST JSON and call `onEvent(name, data)` for every SSE event until the stream ends. */
export async function postStream(path: string, body: unknown, onEvent: (name: string, data: any) => void, signal?: AbortSignal) {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal,
  });
  if (!res.ok || !res.body) {
    const err = await res.json().catch(() => ({}));
    throw { code: err.code ?? `HTTP_${res.status}`, message: err.message ?? "Request failed", retryable: !!err.retryable };
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      let name = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) name = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trim());
      }
      if (data.length) onEvent(name, JSON.parse(data.join("\n")));
    }
  }
}
