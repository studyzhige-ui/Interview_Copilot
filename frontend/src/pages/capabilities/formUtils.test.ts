import { describe, expect, it } from 'vitest';
import { parseArgs, parseKeyValueLines } from './formUtils';

describe('capability form parsers', () => {
  it('parses secrets without splitting values on later equals signs', () => {
    expect(parseKeyValueLines('Authorization=Bearer abc==\nX-Tenant=demo')).toEqual({
      Authorization: 'Bearer abc==',
      'X-Tenant': 'demo',
    });
  });

  it('rejects malformed secret lines', () => {
    expect(() => parseKeyValueLines('missing-separator')).toThrow('格式错误');
  });

  it('parses one stdio argument per line', () => {
    expect(parseArgs('--yes\nserver.py\n\n')).toEqual(['--yes', 'server.py']);
  });
});
