import { expect, it } from 'vitest';
import { buildIcs, parseCsv, toCsv } from '@/pages/career/transfer';

it('keeps multiline Chinese CSV cells and rejects an incomplete quoted field', () => {
  const rows = [['公司', '岗位'], ['星河,科技', '工程师\nPython']];
  expect(parseCsv(toCsv(rows))).toEqual(rows);
  expect(() => parseCsv('公司,岗位\n"未闭合,工程师')).toThrow();
  expect(toCsv([['=HYPERLINK("bad")']])).toContain("'=HYPERLINK");
});

it('folds iCalendar at UTF-8 octet boundaries and preserves UTC and escaping', () => {
  const ics = buildIcs([{ id: 'iv1', title: '中文面试安排'.repeat(20) + ',团队;一\n下一行', start: '2026-10-15T10:00:00+08:00' }]);
  for (const line of ics.split('\r\n')) expect(new TextEncoder().encode(line).length).toBeLessThanOrEqual(75);
  const unfolded = ics.replaceAll('\r\n ', '');
  expect(unfolded).toContain('DTSTART:20261015T020000Z');
  expect(unfolded).not.toContain('DTEND:');
  expect(unfolded).toContain('\\,团队\\;一\\n下一行');
});
