'use strict';
const api = window.copilotRuntime;
const status = document.querySelector('#status');
function paint(state) {
  status.textContent = state.message; status.dataset.error = String(state.phase === 'error');
  const busy = ['starting', 'stopping'].includes(state.phase);
  for (const id of ['check', 'start', 'open']) document.getElementById(id).disabled = busy;
  document.querySelector('#open').hidden = !state.ready;
  document.querySelector('#stop').disabled = busy || !state.canStop;
}
async function run(action) { try { paint(await api.command(action)); } catch (error) { status.textContent = error.message.replace(/^Error invoking remote method[^:]*: /, ''); status.dataset.error = 'true'; } }
for (const action of ['check', 'start', 'open', 'stop']) document.getElementById(action).addEventListener('click', () => run(action));
document.querySelector('#guide').addEventListener('click', () => run('docker-guide'));
api.onState(paint); void run('state');
