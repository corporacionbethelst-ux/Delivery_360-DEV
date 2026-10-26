import { act, renderHook } from '@testing-library/react';
import { useNotifications } from '@/hooks/useNotifications';

class Socket {
  static OPEN=1; static CLOSED=3; static instances:Socket[]=[];
  readyState=0; onopen: any; onmessage:any; onclose:any; onerror:any;
  send=jest.fn();
  constructor(public url:string) { Socket.instances.push(this); }
  close=jest.fn(()=>{ this.readyState=3; });
  open() { this.readyState=1; this.onopen?.({}); }
  message(value:unknown) { this.onmessage?.({ data:JSON.stringify(value) }); }
  end(code:number) { this.readyState=3; this.onclose?.({ code }); }
}
const original=global.WebSocket, originalFetch=global.fetch;
const fetcher=jest.fn();
beforeEach(()=>{
 jest.useFakeTimers(); Socket.instances=[]; fetcher.mockReset();
 fetcher.mockResolvedValue({ ok:true,json:async()=>({ items:[],unread_count:0 }) });
 Object.defineProperty(global,'WebSocket',{ configurable:true,value:Socket }); global.fetch=fetcher;
 localStorage.setItem('access_token','unit-test-token');
});
afterEach(()=>{ jest.clearAllTimers(); jest.useRealTimers(); global.WebSocket=original; global.fetch=originalFetch; localStorage.clear(); });

it('continues REST polling while an open socket has no realtime transport',async()=>{
 const { result,unmount }=renderHook(()=>useNotifications());
 await act(async()=>{});
 const socket=Socket.instances[0];
 act(()=>{ socket.open(); socket.message({ type:'CONNECTED',unread_count:3,realtime_available:false }); });
 expect(result.current.isConnected).toBe(false); expect(result.current.unreadCount).toBe(3);
 const before=fetcher.mock.calls.length;
 await act(async()=>{ jest.advanceTimersByTime(60000); });
 expect(fetcher.mock.calls.length).toBeGreaterThan(before); expect(Socket.instances).toHaveLength(1);
 unmount(); expect(socket.close).toHaveBeenCalled();
});
it('does not poll just because an authorized realtime connection is idle',async()=>{
 const { result,unmount }=renderHook(()=>useNotifications()); await act(async()=>{});
 act(()=>{ Socket.instances[0].open(); Socket.instances[0].message({ type:'CONNECTED',unread_count:0,realtime_available:true }); });
 const before=fetcher.mock.calls.length;
 await act(async()=>{ jest.advanceTimersByTime(60000); });
 expect(result.current.isConnected).toBe(true); expect(fetcher).toHaveBeenCalledTimes(before);
 expect(Socket.instances[0].send).toHaveBeenCalledWith(JSON.stringify({ type:'ping' })); unmount();
});
it('uses canonical counts and updates one item when Redis repeats an event',async()=>{
 const { result,unmount }=renderHook(()=>useNotifications()); await act(async()=>{});
 const socket=Socket.instances[0]; act(()=>socket.open());
 const message={ type:'NEW_NOTIFICATION',id:'known',title:'Persisted',channel:'IN_APP',status:'PENDIENTE',unread_count:4 };
 act(()=>{ socket.message(message); socket.message(message); });
 expect(result.current.items).toHaveLength(1); expect(result.current.unreadCount).toBe(4);
 act(()=>socket.message({ ...message,status:'LEIDO',unread_count:3 }));
 expect(result.current.items[0].status).toBe('LEIDO'); expect(result.current.unreadCount).toBe(3); unmount();
});
it('stops reconnecting after a policy close and keeps the REST fallback',async()=>{
 const { result,unmount }=renderHook(()=>useNotifications()); await act(async()=>{});
 act(()=>{ Socket.instances[0].open(); Socket.instances[0].end(1008); });
 const before=fetcher.mock.calls.length;
 await act(async()=>{ jest.advanceTimersByTime(60000); });
 expect(Socket.instances).toHaveLength(1); expect(result.current.isConnected).toBe(false);
 expect(fetcher.mock.calls.length).toBeGreaterThan(before); unmount();
});
