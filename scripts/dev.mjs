import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import net from 'node:net';

const root = fileURLToPath(new URL('../', import.meta.url));
const args = process.argv.slice(2);
if (args.length === 1 && args[0] === '--help') {
  console.log('Usage: npm run dev [-- --port 8124]\nDefault port: BRICK_PORT or 8123. Stop with Ctrl+C.');
  process.exit(0);
}
if (args.length !== 0 && !(args.length === 2 && args[0] === '--port')) {
  console.error('Usage: npm run dev [-- --port 8124]');
  process.exit(1);
}

const port = args[1] ?? process.env.BRICK_PORT ?? '8123';
if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535) {
  console.error('Port must be an integer from 1 to 65535.');
  process.exit(1);
}
const python = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
if (!existsSync(python)) {
  console.error('Project Python environment is missing: .venv. See QUICKSTART.md for setup.');
  process.exit(1);
}

// Check before Python loads the graph; an existing service must not be killed implicitly.
try {
  await new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.once('error', reject);
    probe.listen({ host: '127.0.0.1', port: Number(port), exclusive: true }, () => {
      probe.close(resolve);
    });
  });
} catch (error) {
  if (error.code === 'EADDRINUSE') {
    console.error(`Port ${Number(port)} is already in use. Open http://127.0.0.1:${Number(port)}/ if BrickQA is already running, or stop the old service with Ctrl+C.`);
    console.error('To use a different port: npm run dev -- --port 8124');
  } else {
    console.error(`Cannot listen on port ${Number(port)}: ${error.message}`);
  }
  process.exit(1);
}

console.log(`Starting BrickQA at http://127.0.0.1:${Number(port)}/ (Ctrl+C to stop)`);
const child = spawn(python, ['-u', 'app.py'], {
  cwd: root,
  env: { ...process.env, BRICK_PORT: String(Number(port)) },
  stdio: 'inherit',
  shell: false,
});
let stopping = false;
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    stopping = true;
    child.kill(signal);
  });
}
child.on('error', (error) => {
  console.error(`Could not start Python: ${error.message}`);
  process.exitCode = 1;
});
child.on('exit', (code, signal) => {
  if (code && !stopping) {
    console.error('BrickQA stopped with an error. If the port is in use, choose another with npm run dev -- --port 8124.');
  }
  process.exitCode = stopping ? 0 : (code ?? (signal ? 1 : 0));
});
