import { mkdir, readFile, writeFile, rm, copyFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = path.resolve(here, '../static');
const output = path.resolve(here, '.vercel/output');
const rawOrigin = process.env.SLIDECOACH_BACKEND_ORIGIN;
if (!rawOrigin) throw new Error('Set SLIDECOACH_BACKEND_ORIGIN to the public HTTPS backend origin.');
const backend = new URL(rawOrigin);
if (backend.protocol !== 'https:' || backend.username || backend.password || backend.pathname !== '/' || backend.search || backend.hash) {
  throw new Error('SLIDECOACH_BACKEND_ORIGIN must be an HTTPS origin without a path or credentials.');
}

await rm(output, { recursive: true, force: true });
await mkdir(path.join(output, 'static/static'), { recursive: true });
const files = ['style.css', 'app.js', 'voice.js'];
for (const name of files) await copyFile(path.join(source, name), path.join(output, 'static/static', name));
await copyFile(path.join(source, 'index.html'), path.join(output, 'static/index.html'));

const csp = "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'";
const config = {
  version: 3,
  routes: [
    { src: '/api/(.*)', dest: `${backend.origin}/api/$1`, headers: {
      'Cache-Control': 'no-store',
      'CDN-Cache-Control': 'no-store',
      'Vercel-CDN-Cache-Control': 'no-store',
      'x-vercel-enable-rewrite-caching': '0'
    } },
    { src: '/(.*)', headers: {
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'same-origin',
      'Content-Security-Policy': csp,
      'Permissions-Policy': 'microphone=(self)'
    }, continue: true },
    { src: '/', headers: { 'Cache-Control': 'no-cache' }, continue: true },
    { handle: 'filesystem' },
    { src: '/.*', status: 404 }
  ]
};
await writeFile(path.join(output, 'config.json'), JSON.stringify(config, null, 2) + '\n');
const html = await readFile(path.join(output, 'static/index.html'), 'utf8');
for (const name of files) {
  if (!html.includes(`/static/${name}`)) throw new Error(`Missing asset reference: ${name}`);
}
console.log(`Built static frontend and /api proxy to ${backend.origin}. No model key or database is included.`);
