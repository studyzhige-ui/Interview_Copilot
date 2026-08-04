import { describe, expect, it } from 'vitest';
import { apiUrl } from './apiUrl';

describe('apiUrl', () => {
  it('joins API paths without duplicate slashes', () => {
    expect(apiUrl('/auth/refresh')).toBe('/api/v1/auth/refresh');
    expect(apiUrl('interview-records/1/events')).toBe('/api/v1/interview-records/1/events');
  });
});
