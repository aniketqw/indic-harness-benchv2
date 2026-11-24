
'use strict';

const $ = id => document.getElementById(id);
const languages = {en: 'English', hi: 'Hindi', hinglish: 'Hinglish'};
const models = {glm: 'GLM-5.3-Flash', oss: 'GPT-OSS-120B', nemotron: 'Nemotron 3 Super'};
const domains = {finance: 'Small-business finance', schools: 'School administration',
  agriculture: 'Agriculture cooperatives', localization: 'Software localization',
  municipal: 'Municipal services', logistics: 'Transport and logistics',
  clinic: 'Clinic administration', archives: 'Libraries and archives'};
const buttons = Object.fromEntries(Array.from(document.querySelectorAll('button[data-action]'),
  button => [button.dataset.action, button]));
let token = '';
let busy = false;
let refreshing = false;

function table(id, rows, columns, empty) {
  const body = $(id);
  body.replaceChildren();
  for (const values of rows) {
    const row = body.insertRow();
    for (const value of values) row.insertCell().textContent = value;
  }
  if (!rows.length) {
    const cell = body.insertRow().insertCell();
    cell.colSpan = columns;
    cell.className = 'empty';
    cell.textContent = empty;
  }
}

function message(text, kind = '') {
  const node = $('message');
  node.textContent = text;
  node.toggleAttribute('data-error', kind === 'error');
  node.toggleAttribute('data-safe', kind === 'safe');
}

function render(data) {
  token = data.token;
  $('scope').options[0].textContent = 'Full suite · ' + data.sizes.full + ' conditions';
  $('scope').options[1].textContent = 'Pilot · ' + data.sizes.pilot + ' conditions';
  if (data.scope) $('scope').value = data.scope;
  $('limit').max = data.sizes.full;
  if (Number($('limit').value) > data.sizes.full) $('limit').value = data.sizes.full;
  const total = data.total || data.sizes[$('scope').value];
  const count = key => data.counts[key] || 0;
  const selected = data.exists;
  const scored = Object.values(data.models).reduce((n, model) => n + model.n, 0);
  const attention = count('infrastructure_failed') + count('quota_paused') + count('interrupted') + count('integrity_failed');
  const finished = data.total > 0 && data.finished === data.total;
  const launchable = data.key_file_exists && data.validation_file_exists;
  const pausing = data.running && data.pause_requested;
  let status = 'Ready';
  let kind = 'idle';
  if (data.recoverable) [status, kind] = ['Recovery needed', 'recover'];
  else if (pausing) [status, kind] = ['Pausing', 'pausing'];
  else if (data.running) [status, kind] = ['Running', 'running'];
  else if (finished) status = 'Finished';
  else if (data.pause_requested) status = 'Paused';
  else if (selected) status = 'Stopped';
  else if (!launchable) status = 'Setup required';
  const pill = $('state');
  pill.dataset.kind = kind;
  pill.lastChild.textContent = status;
  $('scope').disabled = selected || busy;
  $('limit').disabled = busy || data.running;
  buttons.start.disabled = busy || data.running || selected || !launchable;
  buttons.pause.disabled = busy || !data.running || !selected || data.pause_requested;
  buttons.resume.disabled = busy || data.running || !selected || finished || !launchable || data.outdated;
  buttons.restart.disabled = busy || data.running || !selected || data.recoverable || !launchable;
  buttons.clear.disabled = busy || data.running || !selected || data.recoverable;
  if (data.notice) message(data.notice, !data.running && !data.recoverable ? 'safe' : '');
  else if (data.outdated) message('This run used an earlier suite. Restart to use the current tasks, or clear it from the dashboard.');
  else if (!data.key_file_exists) message('Set the Ollama key with the hidden local PowerShell prompt.');
  else if (!data.validation_file_exists) message('Run the offline benchmark validation first.');
  else message(data.running ? 'The runner saves each condition as it finishes.' :
    attention ? 'Some conditions need attention. Review the status and runner log.' :
    finished ? 'All conditions reached a terminal state.' : 'Choose a batch size and start or resume the campaign.');

  $('count').textContent = data.finished + ' / ' + total;
  $('progress').max = total;
  $('progress').value = data.finished;
  $('scored').textContent = scored;
  $('pending').textContent = data.total ? count('planned') : total;
  $('attention').textContent = attention;
  $('credits').textContent = '$' + data.estimated_credits.toFixed(3);
  $('active').textContent = data.active ?
    [data.active.task, models[data.active.model], languages[data.active.prompt] + ' prompt',
     languages[data.active.files] + ' files'].join(' · ') : 'No active condition';

  function entries(labels, groups) {
    return Object.entries(labels).map(([key, label]) => [label, groups[key]?.n ?? 0,
      groups[key]?.mean?.toFixed(2) ?? '—']);
  }
  table('models', entries(models, data.models), 3, '');
  table('domains', entries(domains, data.domains), 3, '');
  table('recent', data.recent.map(item => [item.task, languages[item.prompt], languages[item.files],
    models[item.model], item.status.replaceAll('_', ' '), item.score === null ? '—' : item.score.toFixed(2)]),
    6, 'Results will appear after the first condition.');
  $('logs').hidden = !data.runner_message;
  $('runner-log').textContent = data.runner_message || '';
}

async function refresh() {
  if (refreshing || busy || !$('campaign').checkValidity()) return;
  refreshing = true;
  const name = $('campaign').value;
  try {
    const response = await fetch('/api/status?campaign=' + encodeURIComponent(name));
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    if (name === $('campaign').value) render(data);
  } catch (error) {
    message(error.message || 'Could not reach the local dashboard.', 'error');
  } finally {
    refreshing = false;
  }
}

$('controls').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy || !event.submitter) return;
  const action = event.submitter.dataset.action;
  const payload = {action, campaign: $('campaign').value, scope: $('scope').value, limit: Number($('limit').value)};
  if (action === 'clear' || action === 'restart') {
    const followUp = action === 'restart' ? 'A fresh run will start and can use Ollama credits.' : 'The dashboard will show an empty campaign.';
    if (!window.confirm('Archive the saved results for “' + payload.campaign + '”? ' + followUp)) return;
    payload.confirmed = true;
  }
  const feedback = $('action-feedback');
  feedback.hidden = true;
  busy = true;
  Object.values(buttons).forEach(button => { button.disabled = true; });
  let failure = '';
  try {
    const response = await fetch('/api/action', {method: 'POST', headers: {
      'Content-Type': 'application/json', 'X-Dashboard-Token': token}, body: JSON.stringify(payload)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    if (data.archive) {
      feedback.textContent = 'Previous results archived in ' + data.archive;
      feedback.hidden = false;
    }
  } catch (error) {
    failure = error.message;
  } finally {
    busy = false;
    await refresh();
    if (failure) message(failure, 'error');
  }
});
$('campaign').addEventListener('input', () => {
  $('action-feedback').hidden = true;
  Object.values(buttons).forEach(button => { button.disabled = true; });
  refresh();
});
$('scope').addEventListener('change', refresh);
refresh();
setInterval(refresh, 2000);
