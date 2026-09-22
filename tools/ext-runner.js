#!/usr/bin/env node
'use strict';
/* Dev OS JavaScript extension runner.
 *
 * Loads extension.js next to the manifest and exposes the same API as the
 * Python host: registrations travel to the shell as line-delimited JSON on
 * stdout, clicks and panel events arrive on stdin. Drawing is declarative:
 * surfaces pass draw-op lists (see EXTENSIONS.md) that the shell replays
 * through its Painter; updateWidget/updatePanel replace the stored list.
 */
const path = require('path');

const directory = process.argv[2] || '.';
const context = JSON.parse(process.env.DEVOS_EXT_CONTEXT || '{}');
const commands = new Map();
const widgetClicks = new Map();
const panelEvents = new Map();

function send(message) {
  process.stdout.write(JSON.stringify(message) + '\n');
}

function ops(value) {
  return Array.isArray(value) ? value : [];
}

const api = {
  version: 2,
  settings: context.settings || {},
  theme: context.theme || {},
  screen: context.screen || [],

  registerCommand(id, title, handler, detail = '') {
    commands.set(String(id), handler);
    send({ type: 'command', id: String(id), title: String(title),
           detail: String(detail) });
  },

  registerTray(id, icon, commandId = null, color = 'accent') {
    send({ type: 'tray', id: String(id), icon, command_id: commandId, color });
  },

  registerWidget(id, zone, width, drawOps, onClick = null) {
    if (onClick) {
      widgetClicks.set(String(id), onClick);
    }
    send({ type: 'widget', id: String(id), zone, width,
           ops: ops(drawOps), click: Boolean(onClick) });
  },

  updateWidget(id, drawOps) {
    send({ type: 'update', target: 'widget', id: String(id), ops: ops(drawOps) });
  },

  createPanel(id, width, height, drawOps, onEvent = null, x = 8) {
    const panelId = String(id);
    if (onEvent) {
      panelEvents.set(panelId, onEvent);
    }
    send({ type: 'panel', id: panelId, width, height, x, ops: ops(drawOps) });
    return {
      show: () => send({ type: 'panel_cmd', id: panelId, cmd: 'show' }),
      hide: () => send({ type: 'panel_cmd', id: panelId, cmd: 'hide' }),
      toggle: () => send({ type: 'panel_cmd', id: panelId, cmd: 'toggle' }),
    };
  },

  updatePanel(id, drawOps) {
    send({ type: 'update', target: 'panel', id: String(id), ops: ops(drawOps) });
  },

  overrideClock(width, drawOps) {
    send({ type: 'clock_override', width, ops: ops(drawOps) });
  },

  restoreClock() {
    send({ type: 'clock_restore' });
  },

  hide(section) {
    send({ type: 'hide', section });
  },

  show(section) {
    send({ type: 'show', section });
  },

  notify(title, body = '') {
    send({ type: 'notify', title: String(title), body: String(body) });
  },

  setTheme(themePath) {
    send({ type: 'set_theme', path: String(themePath) });
  },
};

const entry = path.resolve(directory, 'extension.js');
const extension = require(entry);
if (extension && typeof extension.activate === 'function') {
  extension.activate(api);
}
send({ type: 'ready' });

let buffer = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => {
  buffer += chunk;
  let newline;
  while ((newline = buffer.indexOf('\n')) >= 0) {
    const line = buffer.slice(0, newline);
    buffer = buffer.slice(newline + 1);
    if (line.trim()) {
      dispatch(JSON.parse(line));
    }
  }
});
process.stdin.on('end', () => process.exit(0));

function dispatch(message) {
  if (message.type === 'invoke') {
    const handler = commands.get(message.command);
    if (handler) {
      handler();
    }
  } else if (message.type === 'widget_click') {
    const handler = widgetClicks.get(message.id);
    if (handler) {
      handler();
    }
  } else if (message.type === 'panel_event') {
    const handler = panelEvents.get(message.id);
    if (handler) {
      handler(message.action, message.x, message.y);
    }
  }
}
