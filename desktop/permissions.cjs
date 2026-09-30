'use strict';
function sameOrigin(value, origin) { try { return new URL(value).origin === origin; } catch { return false; } }
function trustedMediaFrame(contents, current, origin, details) {
  return !!contents && contents === current && !contents.isDestroyed() && details?.isMainFrame === true && sameOrigin(contents.getURL(), origin) && sameOrigin(details.requestingUrl, origin) && sameOrigin(details.securityOrigin, origin);
}
function installAudioPermissions(target, { current, origin, ask }) {
  const documents = new WeakMap();
  function documentState(contents) {
    let state = documents.get(contents);
    if (!state) {
      state = { generation: 0, approvedGeneration: null };
      documents.set(contents, state);
      contents.on('did-start-navigation', (_event, _url, inPlace, mainFrame) => {
        if (mainFrame && !inPlace) { state.generation += 1; state.approvedGeneration = null; }
      });
      contents.on('render-process-gone', () => { state.generation += 1; state.approvedGeneration = null; });
    }
    return state;
  }
  target.setPermissionCheckHandler((contents, permission, requestingOrigin, details) => permission === 'media' && details?.mediaType === 'audio' && trustedMediaFrame(contents, current(), origin(), details) && sameOrigin(requestingOrigin, origin()) && documentState(contents).approvedGeneration === documentState(contents).generation);
  target.setPermissionRequestHandler(async (contents, permission, done, details) => {
    if (permission !== 'media' || !trustedMediaFrame(contents, current(), origin(), details) || details.mediaTypes?.length !== 1 || details.mediaTypes[0] !== 'audio') return done(false);
    const requestingDocument = contents.getURL();
    const state = documentState(contents), generation = state.generation;
    try {
      const approved = await ask();
      const stillTrusted = approved && trustedMediaFrame(contents, current(), origin(), details) && requestingDocument === contents.getURL() && generation === state.generation;
      if (stillTrusted) state.approvedGeneration = generation;
      done(!!stillTrusted);
    } catch { done(false); }
  });
}
module.exports = { installAudioPermissions, trustedMediaFrame };
