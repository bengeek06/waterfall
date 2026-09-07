// MS-Project-like calendar-aware duration formatting/parsing (#142): unlike a fixed
// hours/minutes-only format, a "day"/"week"/"month" here is only meaningful relative to the
// *project's own* working calendar (its minutes-per-day/week and days-per-month), so every
// formatter/parser in this module takes that calendar explicitly instead of assuming a constant.

export type ProjectCalendar = {
  minutes_per_day: number;
  minutes_per_week: number;
  days_per_month: number;
};

// Mirrors the backend's own MsProject column defaults (waterfall/models/ms_core.py): used as a
// safe fallback while the owning project hasn't loaded yet (e.g. first render before the
// ProjectRead response arrives), never as a silent substitute for a real, loaded project's
// calendar.
export const DEFAULT_PROJECT_CALENDAR: ProjectCalendar = {
  minutes_per_day: 480,
  minutes_per_week: 2400,
  days_per_month: 20,
};

type UnitDefinition = {
  abbrev: "m" | "sm" | "j" | "h" | "min";
  minutesPerUnit: (calendar: ProjectCalendar) => number;
};

// Largest-to-smallest: drives both which unit "wins" as the primary component in
// formatCalendarDuration and the ordering used to look up the adjacent smaller unit for the
// (optional) secondary component. "min" (minute) and "m" (month) are deliberately distinct
// abbreviations per the MS Project schema reference (tasks_2016_schema.xml) -- do not conflate
// them.
const UNITS: UnitDefinition[] = [
  { abbrev: "m", minutesPerUnit: (calendar) => calendar.days_per_month * calendar.minutes_per_day },
  { abbrev: "sm", minutesPerUnit: (calendar) => calendar.minutes_per_week },
  { abbrev: "j", minutesPerUnit: (calendar) => calendar.minutes_per_day },
  { abbrev: "h", minutesPerUnit: () => 60 },
  { abbrev: "min", minutesPerUnit: () => 1 },
];

// Formats a duration (always expected non-negative -- a signed value such as a predecessor link's
// lag must have its sign stripped by the caller and re-applied around this function's result, the
// same way the pre-existing lagSign/lagMinutes split in planning-links.ts already worked before
// this module existed) using at most two adjacent units (e.g. "1sm2j", "1j2h", "3j", "45min").
//
// Design choice (documented per repo convention for non-trivial decisions): this caps the output
// at exactly two *adjacent* units in the largest-to-smallest hierarchy above, rather than
// cascading all the way down to minutes. A value that doesn't land on a whole count of the
// secondary unit (e.g. 1 week + 2 days + 3 hours, with no exact day/hour split) silently drops
// whatever is finer than the secondary unit and only shows "1sm2j" -- this mirrors the pattern the
// two-max-components approach already used pre-#142 (formatDurationMinutes only ever showed
// "XhYmin", never cascading into e.g. days). Prefer this over a full cascade: it stays visually
// compact and consistent with the existing convention, at the cost of being a lossy *display*
// only (the underlying stored duration_minutes is never touched by this rounding).
// Rounds a unit's raw (undivided) count the way that unit is meant to be displayed: minutes are
// the only unit whose backend-side source of truth (PredecessorLink.lag_tenth_minute / 10, see
// planning-links.ts) can legitimately be a non-integer -- e.g. a 5 lag_tenth_minute becomes a
// genuine 0.5-minute lag -- so a "min" count is rounded to the nearest tenth of a minute (the same
// resolution as lag_tenth_minute) instead of being floored away. Every larger unit (h/j/sm/m) has
// no such fractional source and stays a whole count, matching MS Project's own convention and the
// pre-existing two-adjacent-units design above.
function roundedUnitCount(rawCount: number, abbrev: UnitDefinition["abbrev"]): number {
  if (abbrev === "min") {
    return Math.round(rawCount * 10) / 10;
  }
  return Math.floor(rawCount);
}

// Renders a unit count produced by roundedUnitCount: a whole number never carries a trailing
// ".0" (e.g. "3min", not "3.0min"), while a genuine tenth-of-a-minute value keeps its one decimal
// (e.g. "0.5min").
function formatUnitCount(count: number): string {
  return Number.isInteger(count) ? String(count) : count.toFixed(1);
}

export function formatCalendarDuration(minutes: number | null | undefined, calendar: ProjectCalendar): string {
  if (minutes === null || minutes === undefined) {
    return "-";
  }
  if (minutes === 0) {
    return "0";
  }
  const sizes = UNITS.map((unit) => ({ abbrev: unit.abbrev, size: unit.minutesPerUnit(calendar) }));
  let primaryIndex = sizes.findIndex((unit) => minutes >= unit.size);
  if (primaryIndex === -1) {
    // Smaller than even one minute (e.g. a fractional lag): fall back to the finest unit so the
    // function never throws/returns an empty string for an in-range but sub-minute value.
    primaryIndex = sizes.length - 1;
  }
  const primary = sizes[primaryIndex];
  const primaryRawCount = minutes / primary.size;
  // Guard against a misconfigured calendar (e.g. minutes_per_day/minutes_per_week/days_per_month
  // stored as 0, or even negative -- nothing in the backend model/schema currently forbids either,
  // see planning-calendar review notes) making `primary.size` 0 (division -> Infinity/NaN, caught
  // by the Number.isFinite check) or negative (division stays finite but produces a nonsensical
  // count): fall back to the raw minute count, the same safety net
  // formatCalendarDurationForEditing already has for its own fallback case, rather than surfacing
  // a corrupted string like "InfinitymNaNsm" or a meaningless negative/inverted count.
  if (!Number.isFinite(primaryRawCount) || primary.size <= 0) {
    return String(minutes);
  }
  const primaryCount = roundedUnitCount(primaryRawCount, primary.abbrev);
  const remainder = minutes - primaryCount * primary.size;
  const isFinestUnit = primaryIndex === sizes.length - 1;
  if (remainder === 0 || isFinestUnit) {
    return `${formatUnitCount(primaryCount)}${primary.abbrev}`;
  }
  const secondary = sizes[primaryIndex + 1];
  const secondaryRawCount = remainder / secondary.size;
  // Same guard as the primary component above: a secondary unit whose calendar-derived size is
  // <= 0 must not be allowed to contribute a nonsensical count -- fall back to the primary
  // component alone, exactly like the !Number.isFinite (division-by-zero) case just below.
  if (!Number.isFinite(secondaryRawCount) || secondary.size <= 0) {
    return `${formatUnitCount(primaryCount)}${primary.abbrev}`;
  }
  const secondaryCount = roundedUnitCount(secondaryRawCount, secondary.abbrev);
  if (secondaryCount === 0) {
    return `${formatUnitCount(primaryCount)}${primary.abbrev}`;
  }
  return `${formatUnitCount(primaryCount)}${primary.abbrev}${formatUnitCount(secondaryCount)}${secondary.abbrev}`;
}

// formatCalendarDuration is lossy by design (see above) once a value needs more than two adjacent
// units to be represented exactly. That is an acceptable trade-off for a *read-only* cell, but the
// editable Duration field must never visually misrepresent the value it holds -- re-displaying a
// task's committed duration_minutes as e.g. "1j" when it is actually 500 (1 day + 20 minutes)
// would look like a silent, unexplained change every time the row re-renders without an edit. So
// this variant only returns the calendar-formatted string when it round-trips losslessly back
// through parseCalendarDuration; otherwise it falls back to the plain minute count, which is
// always exact. Symmetric use: parseCalendarDuration must accept whatever this returns.
//
// This function is only ever called with a task's PlanningTaskRead.duration_minutes (see
// use-planning-schedule-drafts.ts), an always-integer field per the backend schema -- unlike
// formatCalendarDuration's other caller (predecessorsLabel in planning-links.ts, which divides
// lag_tenth_minute by 10 and can legitimately produce e.g. 0.5), so the round-trip check above
// never actually has to reconcile a fractional "min" component here. If that ever changes, note
// that the round-trip is *not* guaranteed for a fractional minutes remainder: parseCalendarDuration
// only accepts an integer amount before a unit suffix (its token regex is `\d+`), so a formatted
// string like "0.5min" or "1h30.5min" fails to parse and this function would (correctly, if
// conservatively) fall back to the plain `String(minutes)` instead of silently misparsing it.
export function formatCalendarDurationForEditing(minutes: number, calendar: ProjectCalendar): string {
  const formatted = formatCalendarDuration(minutes, calendar);
  const parsed = parseCalendarDuration(formatted, calendar);
  if ("minutes" in parsed && parsed.minutes === minutes) {
    return formatted;
  }
  return String(minutes);
}

export const DURATION_PARSE_ERROR_MESSAGE = "Format de durée non reconnu. Exemples : 3j, 1sm2j, 480 (minutes).";

// Mirrors the backend's own upper bound for PlanningTaskScheduleUpdate.duration_minutes
// (apps/backend/src/waterfall/schemas/projects.py, `Field(default=None, ge=0, le=7_884_000)`):
// rejecting the same range client-side avoids round-tripping an obviously-invalid value through
// a failed request, and doubles as the ceiling that also catches numeric overflow (see below).
const MAX_DURATION_MINUTES = 7_884_000;

export type ParsedDuration = { minutes: number } | { error: string };

// Symmetric counterpart of formatCalendarDuration: accepts either a bare integer (raw minutes,
// preserving the pre-#142 behaviour so existing scripted/copy-pasted values keep working) or a
// sequence of "<int><unit>" tokens using the same abbreviations ("m"/"sm"/"j"/"h"/"min"), in any
// order, each unit used at most once (e.g. "3j", "1sm2j", "1j2h"). Only integers are accepted,
// matching the pre-existing `step={1}` on the (now-text) duration input.
export function parseCalendarDuration(text: string, calendar: ProjectCalendar): ParsedDuration {
  const trimmed = text.trim();
  if (trimmed === "") {
    return { error: DURATION_PARSE_ERROR_MESSAGE };
  }
  if (/^\d+$/.test(trimmed)) {
    // A digit-only string long enough (e.g. 320 nines) overflows `Number(...)` to Infinity,
    // which JSON.stringify would later silently turn into null instead of surfacing an error --
    // reject it here instead, the same way lag parsing in use-planning-task-links.ts already does
    // for its own numeric field.
    const rawMinutes = Number(trimmed);
    if (!Number.isFinite(rawMinutes) || rawMinutes > MAX_DURATION_MINUTES) {
      return { error: DURATION_PARSE_ERROR_MESSAGE };
    }
    return { minutes: rawMinutes };
  }
  // Alternation order matters: "min" must be tried before "m" so "1min" isn't misread as "1m" +
  // a dangling "in".
  const tokenPattern = /(\d+)(min|sm|m|j|h)/g;
  let match: RegExpExecArray | null;
  let consumedLength = 0;
  let totalMinutes = 0;
  const seenUnits = new Set<string>();
  while ((match = tokenPattern.exec(trimmed)) !== null) {
    if (match.index !== consumedLength) {
      return { error: DURATION_PARSE_ERROR_MESSAGE };
    }
    const [fullMatch, amountText, unitAbbrev] = match;
    if (seenUnits.has(unitAbbrev)) {
      return { error: DURATION_PARSE_ERROR_MESSAGE };
    }
    seenUnits.add(unitAbbrev);
    const unitDefinition = UNITS.find((unit) => unit.abbrev === unitAbbrev);
    if (!unitDefinition) {
      return { error: DURATION_PARSE_ERROR_MESSAGE };
    }
    const unitMinutes = unitDefinition.minutesPerUnit(calendar);
    // A misconfigured project calendar (minutes_per_day/minutes_per_week/days_per_month stored as
    // 0, or some other non-finite value -- nothing in the backend model/schema currently forbids
    // it) must not be allowed to silently turn e.g. "2j" into 0 minutes: formatCalendarDuration
    // already has an explicit fallback for this same misconfiguration, so parsing should surface
    // an error too rather than accepting a token whose unit is worth nothing/undefined here. The
    // bare-minutes branch above is unaffected: it never depends on the calendar.
    if (!Number.isFinite(unitMinutes) || unitMinutes <= 0) {
      return { error: DURATION_PARSE_ERROR_MESSAGE };
    }
    totalMinutes += Number(amountText) * unitMinutes;
    consumedLength = match.index + fullMatch.length;
  }
  if (consumedLength === 0 || consumedLength !== trimmed.length) {
    return { error: DURATION_PARSE_ERROR_MESSAGE };
  }
  // Same overflow guard as the raw-number branch above: a token amount large enough (e.g. 320
  // nines followed by a unit suffix) overflows the multiplication/sum to Infinity.
  if (!Number.isFinite(totalMinutes) || totalMinutes > MAX_DURATION_MINUTES) {
    return { error: DURATION_PARSE_ERROR_MESSAGE };
  }
  return { minutes: totalMinutes };
}
