/**
 * Time utilities for Delivery360
 * Handles time formatting, duration calculations, and business hours
 * Safe for SSR environments
 */

export type TimeFormat = '24h' | '12h';

/**
 * Format a date to a readable string
 */
export function formatDate(date: Date | string, format: string = 'DD/MM/YYYY'): string {
  const d = new Date(date);
  
  if (isNaN(d.getTime())) {
    return 'Fecha inválida';
  }

  const day = String(d.getDate()).padStart(2, '0');
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const year = d.getFullYear();
  const hours = String(d.getHours()).padStart(2, '0');
  const minutes = String(d.getMinutes()).padStart(2, '0');
  const seconds = String(d.getSeconds()).padStart(2, '0');

  const tokens: Record<string,string> = { DD:day, MM:month, YYYY:String(year), YY:String(year).slice(-2), HH:hours, mm:minutes, ss:seconds };
  return format.replace(/YYYY|YY|DD|MM|HH|mm|ss/g, token=>tokens[token]);
}

/**
 * Format time with optional 12/24 hour format
 */
export function formatTime(date: Date | string, format: TimeFormat = '24h'): string {
  const d = new Date(date);
  
  if (isNaN(d.getTime())) {
    return '--:--';
  }

  let hours = d.getHours();
  const minutes = String(d.getMinutes()).padStart(2, '0');
  let period = '';

  if (format === '12h') {
    period = hours >= 12 ? ' PM' : ' AM';
    hours = hours % 12 || 12;
  }

  return `${String(hours).padStart(2, '0')}:${minutes}${period}`;
}

/**
 * Format duration in seconds to human readable string
 */
export function formatDuration(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return '0s';
  
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  const parts: string[] = [];
  
  if (hours > 0) {
    parts.push(`${hours}h`);
  }
  if (minutes > 0 || hours > 0) {
    parts.push(`${minutes}m`);
  }
  parts.push(`${secs}s`);

  return parts.join(' ');
}

/**
 * Calculate difference between two dates in various units
 */
export function dateDiff(
  date1: Date | string,
  date2: Date | string,
  unit: 'seconds' | 'minutes' | 'hours' | 'days' | 'weeks' | 'months' = 'minutes'
): number {
  const d1 = new Date(date1);
  const d2 = new Date(date2);

  if (isNaN(d1.getTime()) || isNaN(d2.getTime())) {
    return 0;
  }

  const diffMs = Math.abs(d2.getTime() - d1.getTime());

  switch (unit) {
    case 'seconds':
      return Math.floor(diffMs / 1000);
    case 'minutes':
      return Math.floor(diffMs / (1000 * 60));
    case 'hours':
      return Math.floor(diffMs / (1000 * 60 * 60));
    case 'days':
      return Math.floor(diffMs / (1000 * 60 * 60 * 24));
    case 'weeks':
      return Math.floor(diffMs / (1000 * 60 * 60 * 24 * 7));
    case 'months':
      return Math.floor(diffMs / (1000 * 60 * 60 * 24 * 30.44)); // Average days per month
    default:
      return 0;
  }
}

/**
 * Check if a date is within business hours
 * Default: Monday-Friday, 9:00-18:00
 */
export function isBusinessHours(
  date: Date | string,
  config: {
    startHour?: number;
    endHour?: number;
    weekdays?: number[];
  } = {}
): boolean {
  const d = new Date(date);
  
  if (isNaN(d.getTime())) {
    return false;
  }

  const {
    startHour = 9,
    endHour = 18,
    weekdays = [1, 2, 3, 4, 5], // Monday to Friday
  } = config;

  const dayOfWeek = d.getDay();
  const hour = d.getHours();

  return weekdays.includes(dayOfWeek) && hour >= startHour && hour < endHour;
}

/**
 * Get relative time description (e.g., "Hace 5 minutos", "En 2 horas")
 */
export function getRelativeTime(date: Date | string): string {
  const d = new Date(date);
  
  if (isNaN(d.getTime())) {
    return 'Fecha inválida';
  }

  const now = new Date();
  const diffMs = d.getTime() - now.getTime();
  const seconds = Math.floor(Math.abs(diffMs) / 1000);
  for (const [scale,label] of [[86400,'día'],[3600,'hora'],[60,'minuto']] as const) {
    const count = Math.floor(seconds/scale);
    if (count) return `${diffMs>=0?'En':'Hace'} ${count} ${label}${count>1?'s':''}`;
  }
  return diffMs >= 0 ? 'Ahora mismo' : 'Hace un momento';
}

/**
 * Check if a date is today
 */
export function isToday(date: Date | string): boolean {
  const d = new Date(date);
  const today = new Date();
  
  return (
    d.getDate() === today.getDate() &&
    d.getMonth() === today.getMonth() &&
    d.getFullYear() === today.getFullYear()
  );
}

/**
 * Check if a date is yesterday
 */
export function isYesterday(date: Date | string): boolean {
  const d = new Date(date);
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  
  return (
    d.getDate() === yesterday.getDate() &&
    d.getMonth() === yesterday.getMonth() &&
    d.getFullYear() === yesterday.getFullYear()
  );
}

/**
 * Add time to a date
 */
export function addTime(
  date: Date | string,
  amount: number,
  unit: 'seconds' | 'minutes' | 'hours' | 'days' | 'weeks' | 'months'
): Date {
  const d = new Date(date);
  
  if (isNaN(d.getTime())) {
    return new Date(NaN);
  }

  switch (unit) {
    case 'seconds':
      d.setSeconds(d.getSeconds() + amount);
      break;
    case 'minutes':
      d.setMinutes(d.getMinutes() + amount);
      break;
    case 'hours':
      d.setHours(d.getHours() + amount);
      break;
    case 'days':
      d.setDate(d.getDate() + amount);
      break;
    case 'weeks':
      d.setDate(d.getDate() + amount * 7);
      break;
    case 'months':
      d.setMonth(d.getMonth() + amount);
      break;
  }

  return d;
}

/**
 * Get start of day
 */
export function startOfDay(date: Date | string = new Date()): Date {
  const d = new Date(date);
  if (isNaN(d.getTime())) return new Date();
  d.setHours(0, 0, 0, 0);
  return d;
}

/**
 * Get end of day
 */
export function endOfDay(date: Date | string = new Date()): Date {
  const d = new Date(date);
  if (isNaN(d.getTime())) return new Date();
  d.setHours(23, 59, 59, 999);
  return d;
}

/**
 * Parse ISO duration string (e.g., "PT2H30M") to seconds
 */
export function parseISODuration(isoDuration: string): number {
  if (!isoDuration) return 0;
  
  const match = isoDuration.match(/^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$/);
  
  if (!match || !match.slice(1).some(Boolean)) {
    return 0;
  }

  const hours = parseInt(match[1] || '0', 10);
  const minutes = parseInt(match[2] || '0', 10);
  const seconds = Number(match[3] || '0');
  const total = hours * 3600 + minutes * 60 + seconds;
  return Number.isFinite(total) ? total : 0;
}

/**
 * Convert seconds to ISO duration string
 */
export function secondsToISODuration(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return 'PT0S';

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;

  let result = 'PT';
  if (hours > 0) result += `${hours}H`;
  if (minutes > 0) result += `${minutes}M`;
  if (secs > 0 || result === 'PT') result += `${secs}S`;

  return result;
}

/**
 * Get timezone offset in minutes
 */
export function getTimezoneOffset(date: Date = new Date()): number {
  return date.getTimezoneOffset();
}

/**
 * Convert local time to UTC
 */
export function localToUTC(date: Date | string): Date {
  // Date represents an instant already; formatting selects its display timezone.
  return new Date(date);
}

/**
 * Convert UTC to local time
 */
export function utcToLocal(date: Date | string): Date {
  return new Date(date);
}
