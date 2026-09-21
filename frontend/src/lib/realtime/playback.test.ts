import { expect, it, vi } from 'vitest';
import { RealtimePlayback } from './playback';

function setup() {
  const nodes: Array<{ start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn>; disconnect: ReturnType<typeof vi.fn>; onended: (() => void) | null; buffer?: AudioBuffer }> = [];
  const context = { state: 'running', currentTime: 0, destination: {},
    createBuffer: vi.fn((_channels, samples) => ({ getChannelData: () => new Float32Array(samples) })),
    createBufferSource: vi.fn(() => { const node = { connect: vi.fn(), disconnect: vi.fn(), start: vi.fn(), stop: vi.fn(), onended: null }; nodes.push(node); return node; }),
  };
  const report = vi.fn();
  return { player: new RealtimePlayback(context as unknown as AudioContext, report), context, nodes, report };
}
it('schedules PCM in order and reports only rendered samples', () => {
  const { player, context, nodes, report } = setup();
  player.begin({ audio_id: 'a', rate: 24000, samples: 24000 });
  const half = btoa('\0'.repeat(12000));
  for (let i = 0; i < 4; i++) player.append('a', i * 6000, half);
  player.end('a');
  expect(nodes[0].start).toHaveBeenCalledWith(.12);
  context.currentTime = .62; player.progress();
  expect(report).toHaveBeenLastCalledWith('a', 12000, false);
  context.state = 'suspended'; context.currentTime = 2; player.progress();
  expect(report).toHaveBeenCalledTimes(1);
  context.state = 'running'; player.progress();
  expect(report).toHaveBeenLastCalledWith('a', 24000, true);
});
it('rejects incomplete, oversized, overlapping and out-of-order audio', () => {
  const { player } = setup();
  expect(() => player.begin({ audio_id: 'a', rate: 24000, samples: 1440001 })).toThrow();
  player.begin({ audio_id: 'a', rate: 24000, samples: 2 });
  expect(() => player.begin({ audio_id: 'b', rate: 24000, samples: 2 })).toThrow();
  expect(() => player.append('a', 1, btoa('\0\0'))).toThrow();
  expect(() => player.append('a', 0, btoa('\0'.repeat(6)))).toThrow();
  expect(() => player.end('a')).toThrow();
});
it('interruption releases nodes and ignores only the interrupted audio identity', () => {
  const { player, nodes } = setup();
  player.begin({ audio_id: 'a', rate: 24000, samples: 10 });
  player.append('a', 0, btoa('\0'.repeat(10))); player.stop();
  expect(nodes[0].stop).toHaveBeenCalledOnce(); expect(nodes[0].disconnect).toHaveBeenCalledOnce();
  expect(() => player.append('a', 5, btoa('\0'.repeat(10)))).not.toThrow();
  player.begin({ audio_id: 'b', rate: 24000, samples: 10 });
  expect(() => player.append('a', 0, btoa('\0\0'))).toThrow();
});
