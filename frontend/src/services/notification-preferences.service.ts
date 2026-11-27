import { api } from '@/lib/api';
import { capturePrivateTask } from '@/lib/private-task';

export const PREFERENCE_CHANNELS = ['IN_APP', 'EMAIL', 'SMS', 'PUSH'] as const;
export const EXTERNAL_CHANNELS = ['EMAIL', 'SMS', 'PUSH'] as const;
export type PreferenceChannel = (typeof PREFERENCE_CHANNELS)[number];
export type Preference = { event_code: string; channel: PreferenceChannel; enabled: boolean };
export type PreferenceTemplate = { code: string; channel: PreferenceChannel; is_active: boolean };
export type PreferenceSnapshot = { preferences: Preference[]; templates: PreferenceTemplate[] };
export const EVENT_LABELS = new Map([
  ['payout_solicitado', 'Retiro solicitado'],
  ['payout_aprobado', 'Retiro aprobado contablemente'],
  ['payout_rechazado', 'Retiro rechazado'],
  ['payout_fallido', 'Retiro fallido (histórico)'],
  ['nuevo_pedido_asignado', 'Asignación de orden'],
  ['entrega_completada', 'Entrega completada'],
  ['entrega_fallida', 'Intento de entrega fallido'],
  ['orden_cancelada', 'Orden cancelada'],
  ['alerta_desviacion_ruta', 'Desviación de ruta'],
  ['resumen_diario_manager', 'Resumen de gerencia'],
]);
export const CHANNEL_LABELS: Record<PreferenceChannel, string> = {
  IN_APP: 'Bandeja interna',
  EMAIL: 'Correo',
  SMS: 'SMS',
  PUSH: 'Notificación push',
};
export const preferenceKey = (row: Pick<Preference, 'event_code' | 'channel'>): string =>
  JSON.stringify([row.event_code, row.channel]);
const code = (value: unknown): value is string =>
  typeof value === 'string' && Array.from(value).length >= 1 && Array.from(value).length <= 50;
const channel = (value: unknown): value is PreferenceChannel =>
  PREFERENCE_CHANNELS.includes(value as PreferenceChannel);
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new Error('Respuesta de preferencias no válida');
  return value as Record<string, unknown>;
}
export function editablePreferenceChannels(role: string): readonly PreferenceChannel[] {
  if (!['SUPERADMIN', 'GERENTE', 'OPERADOR', 'AUDITOR', 'REPARTIDOR', 'CLIENTE'].includes(role))
    throw new Error('Rol no verificado');
  return role === 'REPARTIDOR' ? ['PUSH'] : role === 'CLIENTE' ? ['EMAIL'] : EXTERNAL_CHANNELS;
}
export function preferenceValue(
  snapshot: PreferenceSnapshot,
  event: string,
  target: PreferenceChannel,
): boolean {
  return (
    snapshot.preferences.find((row) => row.event_code === event && row.channel === target)
      ?.enabled ?? true
  );
}
export function preferenceEvents(snapshot: PreferenceSnapshot): string[] {
  return [
    ...new Set([
      ...EVENT_LABELS.keys(),
      ...snapshot.templates.map((row) => row.code),
      ...snapshot.preferences.map((row) => row.event_code),
    ]),
  ].sort((a, b) => a.localeCompare(b, 'es'));
}
export const notificationPreferences = {
  async snapshot(): Promise<PreferenceSnapshot> {
    const task = capturePrivateTask();
    const [prefs, catalog] = await Promise.all([
      api.get<unknown>('/notifications/preferences'),
      api.get<unknown>('/notifications/templates'),
    ]);
    task.assertCurrent();
    const values = record(prefs).preferences,
      templates = record(catalog).templates;
    if (!Array.isArray(values) || !Array.isArray(templates))
      throw new Error('Consulta incompleta de preferencias');
    const rows = values.map((value) => {
      const row = record(value);
      if (!code(row.event_code) || !channel(row.channel) || typeof row.enabled !== 'boolean')
        throw new Error('Preferencia no válida');
      return { event_code: row.event_code, channel: row.channel, enabled: row.enabled };
    });
    const list = templates.map((value) => {
      const row = record(value);
      if (!code(row.code) || !channel(row.channel) || typeof row.is_active !== 'boolean')
        throw new Error('Catálogo no válido');
      return { code: row.code, channel: row.channel, is_active: row.is_active };
    });
    if (
      new Set(rows.map(preferenceKey)).size !== rows.length ||
      new Set(list.map((row) => row.code)).size !== list.length
    )
      throw new Error('Consulta ambigua de preferencias');
    return { preferences: rows, templates: list };
  },
  async save(rows: readonly Preference[], role: string): Promise<void> {
    const allowed = editablePreferenceChannels(role);
    if (
      !rows.length ||
      rows.some(
        (row) =>
          !code(row.event_code) ||
          !allowed.includes(row.channel) ||
          typeof row.enabled !== 'boolean',
      ) ||
      new Set(rows.map(preferenceKey)).size !== rows.length
    )
      throw new Error('Cambios no válidos para este rol');
    const task = capturePrivateTask();
    const receipt = record(
      await api.put<unknown>('/notifications/preferences', {
        preferences: rows.map((row) => ({
          event_code: row.event_code,
          channel: row.channel,
          enabled: row.enabled,
        })),
      }),
    );
    task.assertCurrent();
    if (receipt.status !== 'ok' || receipt.updated !== rows.length)
      throw new Error('El acuse no confirma todos los cambios');
  },
};
