const fs = require('fs');
const path = require('path');

const outDir = path.join(__dirname, '../out');
const chunksDir = path.join(outDir, '_next/static/chunks');
const timestamp = Date.now();

const files = fs.readdirSync(chunksDir)
  .filter(f => f.endsWith('.js') && !f.includes('.v' + timestamp));

const renames = {};
for (const oldName of files) {
  const newName = oldName.replace('.js', `.v${timestamp}.js`);
  fs.renameSync(path.join(chunksDir, oldName), path.join(chunksDir, newName));
  renames[oldName] = newName;
}

function updateFiles(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) { updateFiles(fullPath); continue; }
    if (!entry.name.endsWith('.html') && !entry.name.endsWith('.js')) continue;
    let content = fs.readFileSync(fullPath, 'utf8');
    let changed = false;
    for (const [oldName, newName] of Object.entries(renames)) {
      if (content.includes(oldName)) {
        content = content.split(oldName).join(newName);
        changed = true;
      }
    }
    if (changed) {
      fs.writeFileSync(fullPath, content);
      console.log(`Updated: ${path.relative(outDir, fullPath)}`);
    }
  }
}
updateFiles(outDir);

console.log(`✅ Versioned ${Object.keys(renames).length} chunks with timestamp ${timestamp}`);
