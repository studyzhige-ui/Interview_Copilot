export function parseKeyValueLines(value: string): Record<string, string> {
  const result: Record<string, string> = {};
  for (const raw of value.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const separator = line.indexOf('=');
    if (separator <= 0) throw new Error(`格式错误：${line}`);
    result[line.slice(0, separator).trim()] = line.slice(separator + 1).trim();
  }
  return result;
}

export function parseArgs(value: string): string[] {
  return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}
