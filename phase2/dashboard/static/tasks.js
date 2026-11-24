'use strict';

const byId = id => document.getElementById(id);
const controls = ['task', 'instruction', 'workspace'].map(byId);
const domains = {finance: 'Small-business finance', schools: 'School administration',
  agriculture: 'Agriculture cooperatives', localization: 'Software localization',
  municipal: 'Municipal services', logistics: 'Transport and logistics',
  clinic: 'Clinic administration', archives: 'Libraries and archives'};
let request;

async function json(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error);
  return data;
}

function showError(error) {
  const message = byId('task-error');
  message.hidden = false;
  message.textContent = error.message;
}

async function showTask() {
  request?.abort();
  request = new AbortController();
  byId('task-error').hidden = true;
  const [id, instruction, workspace] = controls.map(control => control.value);
  const query = new URLSearchParams({id, instruction, workspace});
  try {
    const data = await json('/api/task?' + query, {signal: request.signal});
    byId('prompt').textContent = data.prompt;
    byId('files').replaceChildren(...Object.entries(data.files).map(([name, content]) => {
      const section = document.createElement('details');
      section.open = true;
      const title = document.createElement('summary');
      title.textContent = name;
      const text = document.createElement('pre');
      text.textContent = content;
      section.append(title, text);
      return section;
    }));
  } catch (error) {
    if (error.name !== 'AbortError') showError(error);
  }
}

async function initialize() {
  try {
    const tasks = await json('/api/tasks');
    const list = byId('task');
    const groups = new Map();
    for (const task of tasks) {
      if (!groups.has(task.domain)) {
        const group = document.createElement('optgroup');
        group.label = domains[task.domain];
        groups.set(task.domain, group);
        list.append(group);
      }
      groups.get(task.domain).append(new Option(task.title, task.id));
    }
    controls.forEach(control => control.addEventListener('change', showTask));
    await showTask();
  } catch (error) {
    showError(error);
  }
}

initialize();
