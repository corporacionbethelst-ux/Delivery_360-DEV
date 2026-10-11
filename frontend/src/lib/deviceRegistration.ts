/**
 * Fase 9 - Registro de dispositivo para notificaciones PUSH.
 *
 * Llamado tras un login exitoso: obtiene/genera un device_token (web), lo guarda
 * en localStorage y hace POST /notifications/register-device SOLO si cambió
 * respecto al último registrado (evita re-registrar en cada sesión).
 * Nunca lanza excepción al caller: el registro es best-effort y jamás bloquea el login.
 */

const DEVICE_TOKEN_KEY = 'd360_device_token';
const REGISTERED_TOKEN_KEY = 'd360_registered_device_token';

function getApiBase(): string {
  return process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';
}

function getToken(): string | null {
  try {
    const raw = localStorage.getItem('access_token') || localStorage.getItem('token');
    if (!raw) return null;
    try {
      const parsed = JSON.parse(raw);
      return parsed?.token || parsed?.access_token || raw;
    } catch {
      return raw;
    }
  } catch {
    return null;
  }
}

function detectPlatform(): 'android' | 'ios' | 'web' {
  if (typeof navigator === 'undefined') return 'web';
  const ua = navigator.userAgent || '';
  if (/android/i.test(ua)) return 'android';
  if (/iphone|ipad|ipod/i.test(ua)) return 'ios';
  return 'web';
}

function generateWebToken(): string {
  // En web no existe FCM token sin service worker: se genera un id estable por navegador.
  let token = localStorage.getItem(DEVICE_TOKEN_KEY);
  if (!token) {
    token =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? `web-${crypto.randomUUID()}`
        : `web-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    localStorage.setItem(DEVICE_TOKEN_KEY, token);
  }
  return token;
}

export async function registerDeviceAfterLogin(): Promise<void> {
  if (typeof window === 'undefined') return;
  try {
    const token = generateWebToken();
    const lastRegistered = localStorage.getItem(REGISTERED_TOKEN_KEY);
    if (lastRegistered === token) return; // no re-registrar si idéntico

    const jwt = getToken();
    if (!jwt) return;

    const res = await fetch(`${getApiBase()}/notifications/register-device`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${jwt}`,
      },
      body: JSON.stringify({ device_token: token, platform: detectPlatform() }),
    });

    if (res.ok) {
      localStorage.setItem(REGISTERED_TOKEN_KEY, token);
    } else {
      console.warn(`register-device respondió ${res.status} (no crítico)`);
    }
  } catch (err) {
    // Best-effort: jamás rompe el flujo de login
    console.warn('register-device falló (no crítico):', err);
  }
}
