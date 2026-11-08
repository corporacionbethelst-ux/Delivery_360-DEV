import {
  WebSocketClient,
  createWebSocketClient,
  parseWSMessage,
  formatWSMessage,
  getWebSocketUrl,
  WSMessageTypes,
} from "@/lib/websocket";
class Socket {
  static OPEN = 1;
  static CONNECTING = 0;
  static instances: Socket[] = [];
  readyState = 0;
  onopen: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  send = jest.fn();
  close = jest.fn(() => {
    this.readyState = 3;
    this.onclose?.({ code: 1000, reason: "closed" } as CloseEvent);
  });
  constructor(public url: string) {
    Socket.instances.push(this);
  }
  open() {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }
  message(value: unknown) {
    this.onmessage?.({
      data: typeof value === "string" ? value : JSON.stringify(value),
    } as MessageEvent);
  }
}
const original = window.WebSocket;
let clients: WebSocketClient[] = [];
const client = (extra: Record<string, number> = {}) => {
  const value = createWebSocketClient({
    url: "ws://localhost/test",
    reconnectInterval: 10,
    heartbeatInterval: 100,
    ...extra,
  });
  clients.push(value);
  return value;
};
beforeEach(() => {
  jest.useFakeTimers();
  Socket.instances = [];
  Object.defineProperty(window, "WebSocket", {
    value: Socket,
    configurable: true,
  });
  jest.spyOn(console, "error").mockImplementation(() => undefined);
  jest.spyOn(console, "log").mockImplementation(() => undefined);
  jest.spyOn(console, "warn").mockImplementation(() => undefined);
});
afterEach(() => {
  clients.forEach((value) => value.disconnect());
  clients = [];
  Object.defineProperty(window, "WebSocket", {
    value: original,
    configurable: true,
  });
  jest.useRealTimers();
  jest.restoreAllMocks();
});
it("shares a pending connection and opens only one socket", async () => {
  const c = client(),
    first = c.connect(),
    second = c.connect();
  expect(second).toBe(first);
  expect(Socket.instances).toHaveLength(1);
  Socket.instances[0].open();
  await first;
  expect(c.isConnected()).toBe(true);
  await c.connect();
  expect(Socket.instances).toHaveLength(1);
});
it("queues bounded pre-connect messages and preserves correlation IDs across flush", async () => {
  const c = client();
  for (let i = 0; i < 101; i++)
    c.send({ type: "test", data: i, correlationId: "id-" + i });
  const work = c.connect(),
    s = Socket.instances[0];
  s.open();
  await work;
  expect(s.send).toHaveBeenCalledTimes(100);
  expect(JSON.parse(s.send.mock.calls[0][0])).toMatchObject({
    data: 1,
    correlationId: "id-1",
    timestamp: expect.any(Number),
  });
});
it("contains send failure and flush failure without losing ordering", async () => {
  const c = client();
  c.send({ type: "queued", data: 1 });
  const work = c.connect(),
    s = Socket.instances[0];
  s.send.mockImplementationOnce(() => {
    throw new Error("blocked");
  });
  s.open();
  await work;
  s.send.mockImplementationOnce(() => {
    throw new Error("blocked");
  });
  c.send({ type: "later", data: 2 });
  s.close();
  jest.advanceTimersByTime(10);
  const next = Socket.instances[1];
  next.open();
  await Promise.resolve();
  expect(JSON.parse(next.send.mock.calls[0][0]).data).toBe(1);
  expect(JSON.parse(next.send.mock.calls[1][0]).data).toBe(2);
});
it("does not reconnect or replay private messages after explicit disconnect", async () => {
  const c = client();
  const work = c.connect(),
    s = Socket.instances[0];
  s.open();
  await work;
  const late = s.onmessage,
    listener = jest.fn();
  c.subscribe("private", listener);
  c.disconnect();
  c.send({ type: "private", data: "retired" });
  late?.({
    data: JSON.stringify({ type: "private", data: "late" }),
  } as MessageEvent);
  jest.advanceTimersByTime(10000);
  expect(Socket.instances).toHaveLength(1);
  expect(listener).not.toHaveBeenCalled();
  const next = c.connect();
  Socket.instances[1].open();
  await next;
  expect(Socket.instances[1].send).not.toHaveBeenCalled();
});
it("rejects a pending connect when disconnected or closed before opening", async () => {
  const c = client({ maxReconnectAttempts: 0 }),
    pending = c.connect();
  c.disconnect();
  await expect(pending).rejects.toThrow("cancelled");
  const again = c.connect();
  Socket.instances[1].close();
  await expect(again).rejects.toThrow("closed");
});
it("rejects browser connection errors and contains constructor failure", async () => {
  const c = client(),
    pending = c.connect();
  Socket.instances[0].onerror?.(new Event("error"));
  await expect(pending).rejects.toThrow("connection error");
  expect(c.getStatus()).toBe("error");
  c.disconnect();
  Object.defineProperty(window, "WebSocket", {
    value: class {
      constructor() {
        throw new Error("private URL");
      }
    },
    configurable: true,
  });
  await expect(c.connect()).rejects.toThrow("connection failed");
  expect(console.error).not.toHaveBeenCalledWith(
    expect.stringContaining("private URL"),
  );
});
it("reconnects with backoff, stops at the configured bound and clears delayed reconnects", async () => {
  const c = client({ maxReconnectAttempts: 1 }),
    pending = c.connect();
  Socket.instances[0].close();
  await expect(pending).rejects.toThrow();
  jest.advanceTimersByTime(9);
  expect(Socket.instances).toHaveLength(1);
  jest.advanceTimersByTime(1);
  expect(Socket.instances).toHaveLength(2);
  Socket.instances[1].close();
  await Promise.resolve();
  jest.advanceTimersByTime(100);
  expect(Socket.instances).toHaveLength(2);
});
it("sends heartbeat only while connected and honors a disabled interval", async () => {
  const c = client(),
    pending = c.connect(),
    s = Socket.instances[0];
  s.open();
  await pending;
  jest.advanceTimersByTime(100);
  expect(JSON.parse(s.send.mock.calls[0][0]).type).toBe("ping");
  c.disconnect();
  const count = s.send.mock.calls.length;
  jest.advanceTimersByTime(1000);
  expect(s.send).toHaveBeenCalledTimes(count);
  const disabled = client({ heartbeatInterval: 0 }),
    ready = disabled.connect(),
    other = Socket.instances[1];
  other.open();
  await ready;
  jest.advanceTimersByTime(1000);
  expect(other.send).not.toHaveBeenCalled();
});
it("contains individual subscriber failures and honors unsubscribe", async () => {
  const c = client(),
    pending = c.connect(),
    s = Socket.instances[0];
  s.open();
  await pending;
  const typed = jest.fn(),
    generic = jest.fn();
  const remove = c.subscribe("order", typed),
    removeGeneric = c.subscribe("*", generic);
  c.subscribe("order", () => {
    throw new Error("subscriber private");
  });
  c.subscribe("*", () => {
    throw new Error("generic private");
  });
  s.message({ type: "order", data: { id: "o" } });
  expect(typed).toHaveBeenCalledWith({ id: "o" });
  expect(generic).toHaveBeenCalledWith(
    expect.objectContaining({ type: "order" }),
  );
  remove();
  removeGeneric();
  s.message({ type: "order", data: { id: "other" } });
  expect(typed).toHaveBeenCalledTimes(1);
  s.message("invalid-json");
  s.message("null");
  expect(typed).toHaveBeenCalledTimes(1);
});
it("notifies status immediately and contains throwing listeners", async () => {
  const c = client(),
    listener = jest.fn();
  c.onStatusChange(() => {
    throw new Error("status private");
  });
  const remove = c.onStatusChange(listener);
  expect(listener).toHaveBeenLastCalledWith("disconnected");
  const work = c.connect();
  Socket.instances[0].open();
  await work;
  expect(listener).toHaveBeenLastCalledWith("connected");
  remove();
  const count = listener.mock.calls.length;
  c.disconnect();
  expect(listener).toHaveBeenCalledTimes(count);
});
it.each(["null", "[]", "true", "{}", '{"type":1}', '{"type":" "}', "broken"])(
  "rejects malformed wire message %s",
  (raw) => expect(parseWSMessage(raw)).toBeNull(),
);
it("formats display messages with real clock values and preserved IDs", () => {
  const now = Date.now();
  expect(formatWSMessage("test", 0, "explicit")).toMatchObject({
    type: "test",
    data: 0,
    correlationId: "explicit",
    timestamp: now,
  });
  expect(formatWSMessage("test", null).correlationId).toMatch(/^msg_\d+_/);
  expect(parseWSMessage('{"type":"test","data":0}')).toEqual({
    type: "test",
    data: 0,
  });
  expect(WSMessageTypes.ORDER_CREATED).toBe("order_created");
  expect(getWebSocketUrl()).toMatch(/^wss?:\/\//);
});
