import * as time from "@/lib/time-utils";
beforeEach(() => {
  jest.useFakeTimers();
  jest.setSystemTime(new Date("2026-11-07T12:00:00Z"));
});
afterEach(() => {
  jest.useRealTimers();
  jest.restoreAllMocks();
});
it("formats calendar tokens repeatedly without mutating the source", () => {
  const source = new Date(2026, 10, 7, 13, 5, 9);
  expect(time.formatDate(source, "DD/MM/YYYY YY HH:mm:ss DD")).toBe(
    "07/11/2026 26 13:05:09 07",
  );
  expect(source.getDate()).toBe(7);
  expect(time.formatDate("bad")).toBe("Fecha inválida");
});
it.each([
  [0, "12h", "12:05 AM"],
  [12, "12h", "12:05 PM"],
  [13, "12h", "01:05 PM"],
  [13, "24h", "13:05"],
] as const)("formats hour %s as %s", (hour, format, result) =>
  expect(time.formatTime(new Date(2026, 0, 1, hour, 5), format)).toBe(result),
);
it("does not format invalid times as a valid clock", () =>
  expect(time.formatTime("bad")).toBe("--:--"));
it.each([
  [0, "0s"],
  [59, "59s"],
  [60, "1m 0s"],
  [3600, "1h 0m 0s"],
  [3661, "1h 1m 1s"],
  [-1, "0s"],
  [Infinity, "0s"],
  [NaN, "0s"],
  [1.9, "1s"],
])("formats duration %s faithfully", (seconds, expected) =>
  expect(time.formatDuration(seconds)).toBe(expected),
);
it.each([
  ["seconds", 604800],
  ["minutes", 10080],
  ["hours", 168],
  ["days", 7],
  ["weeks", 1],
  ["months", 0],
] as const)("measures absolute calendar difference in %s", (unit, expected) => {
  expect(
    time.dateDiff("2026-11-01T00:00:00Z", "2026-11-08T00:00:00Z", unit),
  ).toBe(expected);
  expect(time.dateDiff("bad", "2026-11-08", unit)).toBe(0);
});
it("handles month calendar bounds and default units", () => {
  expect(time.dateDiff("2025-12-01", "2026-11-01", "months")).toBe(11);
  expect(time.dateDiff("2026-11-01T00:00Z", "2026-11-01T00:03Z")).toBe(3);
});
it.each([
  [new Date(2026, 10, 9, 9), {}, true],
  [new Date(2026, 10, 9, 18), {}, false],
  [new Date(2026, 10, 7, 12), {}, false],
  [
    new Date(2026, 10, 7, 12),
    { weekdays: [6], startHour: 12, endHour: 13 },
    true,
  ],
  ["bad", {}, false],
])("observes business hour boundaries %#", (date, config, expected) =>
  expect(time.isBusinessHours(date as Date, config)).toBe(expected),
);
it.each([
  [-1, "Hace un momento"],
  [0, "Ahora mismo"],
  [59, "Ahora mismo"],
  [-60, "Hace 1 minuto"],
  [60, "En 1 minuto"],
  [-119, "Hace 1 minuto"],
  [-3599, "Hace 59 minutos"],
  [-3600, "Hace 1 hora"],
  [7200, "En 2 horas"],
  [-86399, "Hace 23 horas"],
  [-86400, "Hace 1 día"],
  [172800, "En 2 días"],
])(
  "does not turn a short relative time %s into yesterday",
  (seconds, expected) =>
    expect(time.getRelativeTime(new Date(Date.now() + seconds * 1000))).toBe(
      expected,
    ),
);
it("rejects invalid relative dates", () =>
  expect(time.getRelativeTime("bad")).toBe("Fecha inválida"));
it("recognizes today and yesterday across year boundaries", () => {
  jest.setSystemTime(new Date(2026, 0, 1, 12));
  expect(time.isToday(new Date(2026, 0, 1, 0))).toBe(true);
  expect(time.isToday(new Date(2025, 11, 31))).toBe(false);
  expect(time.isYesterday(new Date(2025, 11, 31))).toBe(true);
  expect(time.isYesterday(new Date(2026, 0, 1))).toBe(false);
  expect(time.isToday("bad")).toBe(false);
});
it.each([
  ["seconds", 1000],
  ["minutes", 60000],
  ["hours", 3600000],
  ["days", 86400000],
  ["weeks", 604800000],
] as const)("adds %s without mutating the date", (unit, ms) => {
  const source = new Date("2026-11-01T00:00:00Z");
  expect(time.addTime(source, 1, unit).getTime() - source.getTime()).toBe(ms);
  expect(source.toISOString()).toBe("2026-11-01T00:00:00.000Z");
});
it("adds months and keeps invalid dates invalid", () => {
  expect(time.addTime(new Date(2026, 0, 1), 1, "months").getMonth()).toBe(1);
  expect(Number.isNaN(time.addTime("bad", 1, "days").getTime())).toBe(true);
});
it("computes day boundaries as independent dates", () => {
  const source = new Date(2026, 10, 7, 13, 2);
  expect(time.startOfDay(source).getHours()).toBe(0);
  expect(time.endOfDay(source).getHours()).toBe(23);
  expect(time.endOfDay(source).getMilliseconds()).toBe(999);
  expect(source.getHours()).toBe(13);
  expect(time.startOfDay()).toBeInstanceOf(Date);
  expect(time.endOfDay()).toBeInstanceOf(Date);
});
it.each([
  ["PT2H30M", 9000],
  ["PT0S", 0],
  ["PT1.5S", 1.5],
  ["PT1H2M3S", 3723],
  ["", 0],
  ["PT", 0],
  ["garbagePT1H", 0],
  ["PT1Htail", 0],
  ["P1D", 0],
  ["PT-1S", 0],
])("parses the entire ISO duration %s", (iso, expected) =>
  expect(time.parseISODuration(iso)).toBe(expected),
);
it.each([
  [0, "PT0S"],
  [3600, "PT1H"],
  [60, "PT1M"],
  [3661, "PT1H1M1S"],
  [1.5, "PT1.5S"],
  [-1, "PT0S"],
  [Infinity, "PT0S"],
])("roundtrips finite ISO seconds %s", (seconds, iso) => {
  expect(time.secondsToISODuration(seconds)).toBe(iso);
  if (seconds >= 0 && Number.isFinite(seconds))
    expect(time.parseISODuration(iso)).toBe(seconds);
});
it("preserves an instant through UTC/local helpers rather than applying an offset twice", () => {
  const source = new Date("2026-11-07T08:00:00-04:00");
  jest.spyOn(Date.prototype, "getTimezoneOffset").mockReturnValue(240);
  for (const convert of [time.localToUTC, time.utcToLocal]) {
    expect(convert(source).getTime()).toBe(source.getTime());
    expect(convert(source)).not.toBe(source);
    expect(Number.isNaN(convert("bad").getTime())).toBe(true);
  }
  expect(time.getTimezoneOffset(source)).toBe(240);
  expect(time.getTimezoneOffset()).toBe(new Date().getTimezoneOffset());
});
