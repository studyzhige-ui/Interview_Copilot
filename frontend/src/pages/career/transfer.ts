// Adapted from Reactive Resume, MIT, copyright (c) 2026 Amruth Pillai.
// Source: 19e0518eb5ea1b2c84d785bc5ea2b6d6c9d7b043; see third_party/reactive-resume.
export function parseCsv(input: string): string[][] {
  // Strip a UTF-8 BOM (Excel prepends one) — trim() doesn't remove \uFEFF, so the first header
  // would otherwise become "\uFEFFcompany" and never match an alias.
  const text = input.replace(/^\uFEFF/, "");
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let inQuotes = false;

  for (let i = 0; i < text.length; i++) {
    const char = text[i];

    if (inQuotes) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += char;
      }
      continue;
    }

    if (char === '"') inQuotes = true;
    else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n" || char === "\r") {
      if (char === "\r" && text[i + 1] === "\n") i++;
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += char;
    }
  }
  if (inQuotes) throw new Error("CSV 引号未闭合，请检查文件");
  // Flush the trailing field/row if the file didn't end in a newline.
  if (field !== "" || row.length > 0) {
    row.push(field);
    rows.push(row);
  }

  return rows.filter((r) => r.some((cell) => cell.trim() !== ""));
}

const escapeText = (text: string) =>
  text
    .replace(/\\/g, "\\\\")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,")
    .replace(/\r?\n/g, "\\n");
const stamp = (date: Date) =>
  date
    .toISOString()
    .replace(/[-:]/g, "")
    .replace(/\.\d{3}/, "");
function fold(line: string) {
  let output = "",
    count = 0;
  for (const char of line) {
    const bytes = new TextEncoder().encode(char).length;
    if (count + bytes > 75) {
      output += "\r\n ";
      count = 1;
    }
    output += char;
    count += bytes;
  }
  return output;
}
export function buildIcs(
  events: Array<{
    id: string;
    title: string;
    start: string;
    end?: string | null;
    location?: string | null;
  }>,
) {
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Interview Copilot//Career//ZH",
    "CALSCALE:GREGORIAN",
  ];
  for (const event of events) {
    const start = new Date(event.start),
      end = event.end ? new Date(event.end) : null;
    lines.push(
      "BEGIN:VEVENT",
      `UID:${event.id}@interview-copilot`,
      `DTSTAMP:${stamp(new Date())}`,
      `DTSTART:${stamp(start)}`,
      ...(end ? [`DTEND:${stamp(end)}`] : []),
      `SUMMARY:${escapeText(event.title)}`,
      ...(event.location ? [`LOCATION:${escapeText(event.location)}`] : []),
      "END:VEVENT",
    );
  }
  return [...lines, "END:VCALENDAR"].map(fold).join("\r\n") + "\r\n";
}
export function toCsv(rows: string[][]) {
  const cell = (s: string) =>
    `"${(/^[\s]*[=+@-]/.test(s) ? "'" + s : s).replaceAll('"', '""')}"`;
  return "\uFEFF" + rows.map((row) => row.map(cell).join(",")).join("\r\n");
}
