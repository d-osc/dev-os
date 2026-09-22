/* Dev OS extension written in JavaScript (runs on the Node.js runtime). */
function clock() {
  return new Date().toTimeString().slice(0, 5);
}

function widgetOps() {
  return [
    { op: 'rect', x: 0, y: 3, w: 72, h: 34, color: 'chrome', r: 4 },
    { op: 'text', value: clock(), x: 8, y: 25, color: 'accent', size: 13, bold: true },
  ];
}

module.exports.activate = function activate(api) {
  api.registerWidget('clock', 'left', 76, widgetOps());
  setInterval(() => api.updateWidget('clock', widgetOps()), 15000);

  api.registerTray('js', 'wifi', 'devos.hello-js.ping', 'blue');

  api.registerCommand('devos.hello-js.ping', 'Ping from JavaScript',
                      () => api.notify('Hello from JS', 'Node.js ' + process.version),
                      'Runs on the Node.js runtime');
};
