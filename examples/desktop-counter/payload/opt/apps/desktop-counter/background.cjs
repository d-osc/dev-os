const fs = require('node:fs');
const path = require('node:path');
const data = process.env.DEVOS_DATA_DIR;
const filename = path.join(data, 'counter.json');
let ticks = 0;
try {
  ticks = Number(JSON.parse(fs.readFileSync(filename, 'utf8')).ticks) || 0;
} catch (error) {
  if (error.code !== 'ENOENT') throw error;
}
function update() {
  const temporary = path.join(data, 'counter.new');
  fs.writeFileSync(temporary, JSON.stringify({ ticks: ++ticks, updated: Date.now() / 1000 }));
  fs.renameSync(temporary, filename);
}
update();
setInterval(update, 1000);
