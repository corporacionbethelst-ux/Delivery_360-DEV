import type { User } from '../src/types/user';
export const profile: User = {
  id: 'owner-a',
  email: 'owner@example.test',
  first_name: 'Owner',
  last_name: 'Test',
  role: 'GERENTE',
  is_active: true,
  created_at: '',
  updated_at: '',
};
export const credentials = {
  access_token: 'realtime-access-a',
  refresh_token: 'realtime-refresh-a',
};
export class TestSocket {
  static OPEN = 1;
  static CONNECTING = 0;
  static CLOSED = 3;
  static instances: TestSocket[] = [];
  readyState = 0;
  onopen: ((event: Event) => unknown) | null = null;
  onmessage: ((event: MessageEvent) => unknown) | null = null;
  onclose: ((event: CloseEvent) => unknown) | null = null;
  onerror: ((event: Event) => unknown) | null = null;
  send = jest.fn();
  close = jest.fn(() => {
    this.readyState = 3;
  });
  constructor(public url: string) {
    TestSocket.instances.push(this);
  }
  open() {
    this.readyState = 1;
    this.onopen?.(new Event('open'));
  }
  message(value: unknown) {
    this.onmessage?.({ data: JSON.stringify(value) } as MessageEvent);
  }
  end(code: number) {
    this.readyState = 3;
    this.onclose?.({ code } as CloseEvent);
  }
}
export function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
