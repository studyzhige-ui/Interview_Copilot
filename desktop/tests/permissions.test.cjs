'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { installAudioPermissions } = require('../permissions.cjs');
const origin = 'http://127.0.0.1:21781';
function setup(ask = async () => true) {
  let url = origin + '/mock', destroyed = false;
  const contents = Object.assign(new EventEmitter(), { getURL: () => url, isDestroyed: () => destroyed });
  const handlers = {}, target = { setPermissionCheckHandler: value => { handlers.check = value; }, setPermissionRequestHandler: value => { handlers.request = value; } };
  installAudioPermissions(target, { current: () => contents, origin: () => origin, ask });
  const details = { isMainFrame: true, securityOrigin: origin, requestingUrl: url, mediaType: 'audio', mediaTypes: ['audio'] };
  return { contents, handlers, details, navigate: value => { contents.emit('did-start-navigation', {}, value, false, true); url = value; }, destroy: () => { destroyed = true; } };
}
test('audio consent never grants video, foreign origins, subframes or unknown media', async () => {
  const { handlers, contents, details } = setup();
  assert.equal(handlers.check(contents, 'media', origin, details), false);
  let allowed; await handlers.request(contents, 'media', value => { allowed = value; }, details);
  assert.equal(allowed, true); assert.equal(handlers.check(contents, 'media', origin, details), true);
  for (const patch of [{ mediaType: 'video' }, { mediaType: 'unknown' }, { isMainFrame: false }, { securityOrigin: 'https://foreign.test' }, { requestingUrl: 'https://foreign.test/page' }]) assert.equal(handlers.check(contents, 'media', origin, { ...details, ...patch }), false);
  assert.equal(handlers.check(contents, 'media', 'https://foreign.test', details), false);
  for (const patch of [{ mediaTypes: ['audio', 'video'] }, { mediaTypes: ['video'] }, { isMainFrame: false }, { securityOrigin: 'https://foreign.test' }]) {
    await handlers.request(contents, 'media', value => { allowed = value; }, { ...details, ...patch }); assert.equal(allowed, false);
  }
});
test('a navigation or destroyed frame while the dialog is open cancels consent', async () => {
  for (const change of ['navigate', 'reload', 'destroy']) {
    let decide; const state = setup(() => new Promise(resolve => { decide = resolve; }));
    let allowed; const pending = state.handlers.request(state.contents, 'media', value => { allowed = value; }, state.details);
    if (change === 'navigate') state.navigate(origin + '/other'); else if (change === 'reload') state.navigate(origin + '/mock'); else state.destroy();
    decide(true); await pending; assert.equal(allowed, false);
  }
});
