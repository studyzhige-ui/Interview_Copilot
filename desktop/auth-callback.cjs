'use strict';
const crypto = require('node:crypto');
const CALLBACKS = Object.freeze({
  signup: 'interview-copilot://auth/confirm',
  recovery: 'interview-copilot://auth/recovery',
});
const STATE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const MAX_AGE_MS = 10 * 60 * 1000;
function parseCallback(value) {
  if (typeof value !== 'string' || value.length > 4096) return null;
  let url; try { url = new URL(value); } catch { return null; }
  if (url.protocol !== 'interview-copilot:' || url.hostname !== 'auth' || url.port || url.username || url.password) return null;
  const purpose = Object.keys(CALLBACKS).find(key => new URL(CALLBACKS[key]).pathname === url.pathname);
  if (!purpose) return null;
  const allowed = new Set(['code', 'error', 'error_code', 'error_description']);
  for (const key of url.searchParams.keys()) if (!allowed.has(key) || url.searchParams.getAll(key).length !== 1) return null;
  const fragment = new URLSearchParams(url.hash.slice(1));
  const code = url.searchParams.get('code');
  if (!code && (url.searchParams.has('error') || fragment.has('error'))) {
    // Supabase error redirects replace Fragment, so they cannot prove a flow.
    // Surface only a fixed notice; never consume the current pending verifier.
    if ([...fragment.keys()].some(key => !['error', 'error_code', 'error_description', 'sb'].includes(key) || fragment.getAll(key).length !== 1)) return null;
    return { purpose, noticeOnly: true, error: '邮箱链接无效或已过期，请重新发送' };
  }
  const state = fragment.get('state');
  if (!state || !STATE.test(state) || [...fragment.keys()].length !== 1) return null;
  if (code && /^[A-Za-z0-9_-]{16,256}$/.test(code) && !url.searchParams.has('error')) return { purpose, state, code };
  return null;
}
/** Pending intent is not authentication. Only the originating SDK's PKCE exchange grants a session. */
class CallbackGate {
  constructor({ read = () => null, write = () => {}, now = Date.now } = {}) {
    this.read = read; this.write = write; this.now = now;
  }
  begin(purpose) {
    if (!Object.hasOwn(CALLBACKS, purpose)) throw new Error('不支持的账号操作');
    const pending = { id: crypto.randomUUID(), purpose, expiresAt: this.now() + MAX_AGE_MS };
    this.write(pending); return { ...pending, redirectTo: `${CALLBACKS[purpose]}#state=${pending.id}` };
  }
  cancel(id) { const pending = this.read(); if (pending?.id === id) this.write(null); }
  consume(value) {
    const callback = parseCallback(value), pending = this.read();
    if (!callback || !pending || !STATE.test(pending.id || '') || callback.state !== pending.id || pending.expiresAt <= this.now() || pending.expiresAt > this.now() + MAX_AGE_MS || callback.purpose !== pending.purpose) return null;
    this.write(null);
    return { id: pending.id, purpose: pending.purpose, ...(callback.code ? { code: callback.code } : { error: callback.error }) };
  }
}
module.exports = { CALLBACKS, MAX_AGE_MS, parseCallback, CallbackGate };
