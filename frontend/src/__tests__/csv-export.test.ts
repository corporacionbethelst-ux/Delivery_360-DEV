import { downloadCSV, serializeCSV } from '@/lib/csv-export';

const create = URL.createObjectURL, revoke = URL.revokeObjectURL;
let click: jest.SpyInstance;
beforeEach(() => {
  jest.useFakeTimers(); URL.createObjectURL = jest.fn(() => 'blob:test'); URL.revokeObjectURL = jest.fn();
  click = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
});
afterEach(() => { jest.runOnlyPendingTimers(); jest.useRealTimers(); click.mockRestore(); URL.createObjectURL = create; URL.revokeObjectURL = revoke; });

it('exports UTF-8 BOM, CRLF, quoted headers and escaped multiline text without losing commas/accents', () => {
  const csv = serializeCSV([{ 'Cliente, nombre': 'José "Pérez"\r\nSegunda línea', total: 0, ausente: null }]);
  expect(csv).toBe('\uFEFF"Cliente, nombre","total","ausente"\r\n"José ""Pérez""\r\nSegunda línea","0",""\r\n');
});
it.each(['=SUM(1,1)', '+58412', '-2+3', '@SUM(A1)', ' \t=HYPERLINK("bad")', '\r\n+1', '\uFEFF=1'])('neutralizes spreadsheet formulas in text cells (%j)', value => {
  expect(serializeCSV([{ text: value }])).toContain(`"'${value.replace(/"/g, '""')}"`);
});
it('retains typed negative numbers, zero and booleans without turning them into escaped text', () => {
  expect(serializeCSV([{ amount: -40, zero: 0, enabled: false }])).toContain('"-40","0","false"');
});
it('quotes potentially active headers and includes columns introduced by later rows', () => {
  expect(serializeCSV([{ '=header': 'a' }, { extra: 'b' }])).toBe('\uFEFF"\'=header","extra"\r\n"a",""\r\n"","b"\r\n');
});
it('does not substitute inherited object properties for absent cells', () => {
  expect(serializeCSV([{ first: 'a' }, { constructor: 'texto' }])).toContain('"a",""\r\n"","texto"');
});
it.each([{}, [], Infinity, NaN, () => 1])('rejects nonprimitive/nonfinite cells instead of corrupting CSV (%j)', value => {
  expect(() => serializeCSV([{ value }])).toThrow();
});
it('starts exactly one download and removes its link and object URL', () => {
  const filenames: string[] = [];
  click.mockImplementation(function (this: HTMLAnchorElement) { filenames.push(this.download); });
  expect(downloadCSV([{ total: 0 }], 'rango/sin_fin')).toBe(true);
  expect(click).toHaveBeenCalledTimes(1); expect(filenames[0]).toMatch(/^rango_sin_fin_\d{4}-\d{2}-\d{2}\.csv$/);
  expect(document.querySelector('a[download]')).toBeNull(); expect(URL.revokeObjectURL).not.toHaveBeenCalled();
  jest.advanceTimersByTime(1000); expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test');
});
it('cleans up the link and URL even if clicking fails', () => {
  click.mockImplementation(() => { throw new Error('blocked'); });
  expect(() => downloadCSV([{ total: 1 }], 'report')).toThrow('blocked');
  expect(document.querySelector('a[download]')).toBeNull(); jest.runOnlyPendingTimers(); expect(URL.revokeObjectURL).toHaveBeenCalledTimes(1);
});
it('does not create a URL for an invalid/empty CSV', () => {
  const alert = jest.spyOn(window, 'alert').mockImplementation(() => {});
  expect(downloadCSV([], 'empty')).toBe(false); expect(serializeCSV([])).toBe('');
  expect(() => downloadCSV([{ invalid: {} }], 'bad')).toThrow(); expect(URL.createObjectURL).not.toHaveBeenCalled(); alert.mockRestore();
});
