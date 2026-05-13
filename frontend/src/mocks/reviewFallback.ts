// MOCK: replace when interview-records list returns titles+qa_count consistently.
// Used only as fallback when the backend list is empty AND we want to show the
// UI structure to the user during early testing. Set USE_FALLBACK=false to hide.

import type { InterviewRecordListItem } from '@/types/api';

export const USE_FALLBACK = false;

export const FALLBACK_RECORDS: InterviewRecordListItem[] = [
  {
    id: 'mock-1',
    source: 'mock',
    title: '示例 · 字节后端二面',
    status: 'completed',
    created_at: new Date().toISOString(),
  },
];

export interface FallbackQA {
  q: string;
  a: string;
  s?: string;
}

export const FALLBACK_QA: FallbackQA[] = [
  {
    q: '这是 fallback 数据，仅当 /interview-records 为空时显示',
    a: '后端接通后即从真实记录读取',
  },
];
