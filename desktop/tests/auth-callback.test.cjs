'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { CallbackGate, parseCallback, CALLBACKS, MAX_AGE_MS } = require('../auth-callback.cjs');
const state = '00000000-0000-4000-8000-000000000001';
const code = 'synthetic-code-not-a-real-authentication-secret';
test('exact native callbacks allow only a single authorization code and never token URLs', () => {
  assert.deepEqual(parseCallback(`${CALLBACKS.signup}?code=${code}#state=${state}`), { purpose: 'signup', state, code });
  for (const url of [`https://auth/confirm?code=${code}`, `interview-copilot://evil/confirm?code=${code}`, `interview-copilot://auth/confirm/extra?code=${code}`, `${CALLBACKS.signup}?code=${code}&code=duplicate`, `${CALLBACKS.signup}?access_token=x&refresh_token=y`, `${CALLBACKS.signup}?code=${code}#access_token=x`, `interview-copilot://user@auth/confirm?code=${code}`, `${CALLBACKS.signup}?code=${code}&next=https://evil.test`]) assert.equal(parseCallback(url), null, url);
});
test('cold-start state binds the pending purpose, is bounded and consumed once', () => {
  let state = null, now = 1000;
  const persistence = { read: () => state, write: value => { state = value; }, now: () => now };
  const first = new CallbackGate(persistence); const pending = first.begin('recovery');
  assert.equal(first.consume(`${CALLBACKS.signup}?code=${code}`), null);
  const restarted = new CallbackGate(persistence);
  assert.deepEqual(restarted.consume(`${CALLBACKS.recovery}?code=${code}#state=${pending.id}`), { id: pending.id, purpose: 'recovery', code });
  assert.equal(restarted.consume(`${CALLBACKS.recovery}?code=${code}#state=${pending.id}`), null);
  const expired = restarted.begin('signup'); now += MAX_AGE_MS + 1;
  assert.equal(restarted.consume(`${CALLBACKS.signup}?code=${code}#state=${expired.id}`), null);
});
test('superseded and cancelled intents cannot accept callbacks without a fresh pending flow', () => {
  let state; const gate = new CallbackGate({ read: () => state, write: value => { state = value; } });
  const a = gate.begin('signup'); const b = gate.begin('recovery'); gate.cancel(a.id);
  assert.equal(state.id, b.id); gate.cancel(b.id);
  assert.equal(gate.consume(`${CALLBACKS.recovery}?code=${code}`), null);
});

test('an older same-purpose callback cannot consume the replacement intent or its verifier', () => {
  let stored; const gate = new CallbackGate({ read: () => stored, write: value => { stored = value; } });
  const old = gate.begin('recovery'), current = gate.begin('recovery');
  assert.notEqual(old.redirectTo, current.redirectTo);
  assert.equal(gate.consume(`${CALLBACKS.recovery}?code=${code}#state=${old.id}`), null);
  assert.equal(stored.id, current.id);
  assert.equal(gate.consume(`${CALLBACKS.recovery}?code=${code}#state=${current.id}`).id, current.id);
  assert.equal(gate.consume(`${CALLBACKS.recovery}?code=${code}#state=${current.id}`), null);
});

test('only one fragment state is allowed; uncorrelated error returns never consume a flow', () => {
  let stored; const gate = new CallbackGate({ read: () => stored, write: value => { stored = value; } });
  const pending = gate.begin('recovery');
  for (const fragment of [`state=${pending.id}&state=${pending.id}`, `state=${pending.id}&access_token=forbidden`, 'access_token=forbidden', 'state=invalid']) assert.equal(parseCallback(`${CALLBACKS.recovery}?code=${code}#${fragment}`), null);
  const error = `${CALLBACKS.recovery}?error=access_denied#error=access_denied&error_code=otp_expired&sb=`;
  assert.equal(parseCallback(error).noticeOnly, true); assert.equal(gate.consume(error), null);
  assert.equal(stored.id, pending.id);
  assert.equal(gate.consume(`${CALLBACKS.recovery}?code=${code}#state=${pending.id}`).id, pending.id);
});
