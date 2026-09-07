import { describe, expect, it } from "vitest";

import {
  DEFAULT_PROJECT_CALENDAR,
  DURATION_PARSE_ERROR_MESSAGE,
  formatCalendarDuration,
  formatCalendarDurationForEditing,
  parseCalendarDuration,
  type ProjectCalendar,
} from "./planning-calendar";

// A calendar deliberately different from DEFAULT_PROJECT_CALENDAR on every field, to prove the
// formatter/parser actually use the project's own calendar rather than a hardcoded constant.
const customCalendar: ProjectCalendar = {
  minutes_per_day: 360, // 6h working day
  minutes_per_week: 1440, // 4-day working week
  days_per_month: 18,
};

describe("formatCalendarDuration", () => {
  it("returns '-' for null/undefined", () => {
    expect(formatCalendarDuration(null, DEFAULT_PROJECT_CALENDAR)).toBe("-");
    expect(formatCalendarDuration(undefined, DEFAULT_PROJECT_CALENDAR)).toBe("-");
  });

  it("returns '0' for a zero duration", () => {
    expect(formatCalendarDuration(0, DEFAULT_PROJECT_CALENDAR)).toBe("0");
  });

  it("formats a bare number of minutes under an hour", () => {
    expect(formatCalendarDuration(45, DEFAULT_PROJECT_CALENDAR)).toBe("45min");
  });

  it("formats whole hours, with a minutes remainder when not round", () => {
    expect(formatCalendarDuration(60, DEFAULT_PROJECT_CALENDAR)).toBe("1h");
    expect(formatCalendarDuration(90, DEFAULT_PROJECT_CALENDAR)).toBe("1h30min");
  });

  it("formats whole days using the calendar's minutes_per_day, not a fixed constant", () => {
    // Default calendar: 480 min/day.
    expect(formatCalendarDuration(480, DEFAULT_PROJECT_CALENDAR)).toBe("1j");
    expect(formatCalendarDuration(600, DEFAULT_PROJECT_CALENDAR)).toBe("1j2h");
    // Custom calendar: 360 min/day -- the same 480 raw minutes now reads as more than one day.
    expect(formatCalendarDuration(480, customCalendar)).toBe("1j2h");
    expect(formatCalendarDuration(360, customCalendar)).toBe("1j");
  });

  it("formats whole weeks using the calendar's minutes_per_week", () => {
    expect(formatCalendarDuration(2400, DEFAULT_PROJECT_CALENDAR)).toBe("1sm");
    expect(formatCalendarDuration(3360, DEFAULT_PROJECT_CALENDAR)).toBe("1sm2j");
    expect(formatCalendarDuration(1440, customCalendar)).toBe("1sm");
  });

  it("formats whole months using days_per_month * minutes_per_day", () => {
    // Default calendar: 20 days/month * 480 min/day = 9600 min/month.
    expect(formatCalendarDuration(9600, DEFAULT_PROJECT_CALENDAR)).toBe("1m");
    // Custom calendar: 18 days/month * 360 min/day = 6480 min/month.
    expect(formatCalendarDuration(6480, customCalendar)).toBe("1m");
  });

  it("caps at two adjacent units and silently drops a finer remainder", () => {
    // 1 week (2400) + 2 days (960) + 30 minutes = 3390; the 30 leftover minutes are finer than the
    // secondary "day" unit and are dropped by design (see the comment in planning-calendar.ts).
    expect(formatCalendarDuration(3390, DEFAULT_PROJECT_CALENDAR)).toBe("1sm2j");
  });

  it("falls back to the raw minute count instead of dividing by zero on a misconfigured calendar", () => {
    // Nothing in the backend model/schema currently forbids a zero-valued calendar field; without
    // the Number.isFinite guard this would produce a corrupted "InfinitymNaNsm" string.
    const zeroCalendar: ProjectCalendar = { minutes_per_day: 0, minutes_per_week: 0, days_per_month: 0 };
    expect(formatCalendarDuration(10, zeroCalendar)).toBe("10");
  });

  it("preserves a fractional minute instead of flooring it away (Copilot review, #142/PR #189)", () => {
    // predecessorsLabel (planning-links.ts) calls this with link.lag_tenth_minute / 10, which can
    // legitimately be e.g. 0.5 -- Math.floor would silently turn that into "0min", losing a real lag.
    expect(formatCalendarDuration(0.5, DEFAULT_PROJECT_CALENDAR)).toBe("0.5min");
  });

  it("preserves a fractional minute in the secondary component alongside a non-zero primary component", () => {
    // 90.5 minutes = 1h + 30.5min: only the finest ("min") component may carry a decimal, the
    // primary "h" component stays a whole count.
    expect(formatCalendarDuration(90.5, DEFAULT_PROJECT_CALENDAR)).toBe("1h30.5min");
  });

  it("falls back to the primary component alone when the secondary unit's size is invalid (Copilot review round 2, #142/PR #189)", () => {
    // Nothing forbids a negative calendar field either (e.g. minutes_per_week stored as -100):
    // the primary "m" component (10000 min/month) is still valid and lands cleanly, but the
    // secondary "sm" component would divide by a negative size and produce a nonsensical count
    // (e.g. "-0.5sm") if not guarded the same way as the division-by-zero case above.
    const negativeWeekCalendar: ProjectCalendar = { minutes_per_day: 500, minutes_per_week: -100, days_per_month: 20 };
    expect(formatCalendarDuration(10050, negativeWeekCalendar)).toBe("1m");
  });

  it("falls back to the raw minute count when the primary unit's size is negative", () => {
    // Same reasoning applied to the primary component for consistency: a negative
    // minutes_per_day/days_per_month must not produce a nonsensical primary count either.
    const negativeCalendar: ProjectCalendar = { minutes_per_day: -480, minutes_per_week: -2400, days_per_month: 20 };
    expect(formatCalendarDuration(10, negativeCalendar)).toBe("10");
  });
});

describe("formatCalendarDurationForEditing", () => {
  it("uses the calendar-formatted value when it round-trips losslessly", () => {
    expect(formatCalendarDurationForEditing(480, DEFAULT_PROJECT_CALENDAR)).toBe("1j");
    expect(formatCalendarDurationForEditing(600, DEFAULT_PROJECT_CALENDAR)).toBe("1j2h");
    expect(formatCalendarDurationForEditing(0, DEFAULT_PROJECT_CALENDAR)).toBe("0");
  });

  it("falls back to the plain minute count when calendar formatting would be lossy", () => {
    // 500 = 1 day (480) + 20 minutes; the 20-minute remainder is finer than the secondary "h" unit
    // and would be silently dropped by formatCalendarDuration ("1j"), which does not round-trip.
    expect(formatCalendarDurationForEditing(500, DEFAULT_PROJECT_CALENDAR)).toBe("500");
  });
});

describe("parseCalendarDuration", () => {
  it("parses a bare number as raw minutes (backward compatible)", () => {
    expect(parseCalendarDuration("600", DEFAULT_PROJECT_CALENDAR)).toEqual({ minutes: 600 });
    expect(parseCalendarDuration("0", DEFAULT_PROJECT_CALENDAR)).toEqual({ minutes: 0 });
  });

  it("parses a single unit", () => {
    expect(parseCalendarDuration("3j", DEFAULT_PROJECT_CALENDAR)).toEqual({ minutes: 1440 });
    expect(parseCalendarDuration("1sm", DEFAULT_PROJECT_CALENDAR)).toEqual({ minutes: 2400 });
    expect(parseCalendarDuration("2h", DEFAULT_PROJECT_CALENDAR)).toEqual({ minutes: 120 });
    expect(parseCalendarDuration("45min", DEFAULT_PROJECT_CALENDAR)).toEqual({ minutes: 45 });
    expect(parseCalendarDuration("1m", DEFAULT_PROJECT_CALENDAR)).toEqual({ minutes: 9600 });
  });

  it("parses a combination of units regardless of order", () => {
    expect(parseCalendarDuration("1sm2j", DEFAULT_PROJECT_CALENDAR)).toEqual({ minutes: 3360 });
    expect(parseCalendarDuration("1j2h", DEFAULT_PROJECT_CALENDAR)).toEqual({ minutes: 600 });
  });

  it("uses the given calendar, not a fixed constant", () => {
    expect(parseCalendarDuration("1j", customCalendar)).toEqual({ minutes: 360 });
    expect(parseCalendarDuration("1sm", customCalendar)).toEqual({ minutes: 1440 });
  });

  it("rejects an unrecognized format with a clear French error message", () => {
    expect(parseCalendarDuration("abc", DEFAULT_PROJECT_CALENDAR)).toEqual({ error: DURATION_PARSE_ERROR_MESSAGE });
    expect(parseCalendarDuration("3x", DEFAULT_PROJECT_CALENDAR)).toEqual({ error: DURATION_PARSE_ERROR_MESSAGE });
    expect(parseCalendarDuration("3j abc", DEFAULT_PROJECT_CALENDAR)).toEqual({ error: DURATION_PARSE_ERROR_MESSAGE });
    expect(parseCalendarDuration("", DEFAULT_PROJECT_CALENDAR)).toEqual({ error: DURATION_PARSE_ERROR_MESSAGE });
    expect(parseCalendarDuration("3.5j", DEFAULT_PROJECT_CALENDAR)).toEqual({ error: DURATION_PARSE_ERROR_MESSAGE });
  });

  it("rejects a duplicated unit", () => {
    expect(parseCalendarDuration("1j2j", DEFAULT_PROJECT_CALENDAR)).toEqual({ error: DURATION_PARSE_ERROR_MESSAGE });
  });

  it("rejects a digit string long enough to overflow to Infinity instead of returning it as a success", () => {
    const hugeDigits = "9".repeat(320);
    expect(parseCalendarDuration(hugeDigits, DEFAULT_PROJECT_CALENDAR)).toEqual({
      error: DURATION_PARSE_ERROR_MESSAGE,
    });
    expect(parseCalendarDuration(`${hugeDigits}j`, DEFAULT_PROJECT_CALENDAR)).toEqual({
      error: DURATION_PARSE_ERROR_MESSAGE,
    });
  });

  it("round-trips format -> parse -> format for an exact value", () => {
    const minutes = 3360; // 1sm2j
    const formatted = formatCalendarDuration(minutes, DEFAULT_PROJECT_CALENDAR);
    const parsed = parseCalendarDuration(formatted, DEFAULT_PROJECT_CALENDAR);
    expect(parsed).toEqual({ minutes });
    expect(formatCalendarDuration((parsed as { minutes: number }).minutes, DEFAULT_PROJECT_CALENDAR)).toBe(formatted);
  });

  it("rejects a token whose unit is worthless under a misconfigured calendar instead of silently returning 0 (Copilot review, #142/PR #189)", () => {
    const zeroDayCalendar: ProjectCalendar = { ...DEFAULT_PROJECT_CALENDAR, minutes_per_day: 0 };
    expect(parseCalendarDuration("2j", zeroDayCalendar)).toEqual({ error: DURATION_PARSE_ERROR_MESSAGE });

    const zeroWeekCalendar: ProjectCalendar = { ...DEFAULT_PROJECT_CALENDAR, minutes_per_week: 0 };
    expect(parseCalendarDuration("1sm", zeroWeekCalendar)).toEqual({ error: DURATION_PARSE_ERROR_MESSAGE });

    const zeroMonthCalendar: ProjectCalendar = { ...DEFAULT_PROJECT_CALENDAR, days_per_month: 0 };
    expect(parseCalendarDuration("1m", zeroMonthCalendar)).toEqual({ error: DURATION_PARSE_ERROR_MESSAGE });
  });
});
