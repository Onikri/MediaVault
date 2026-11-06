// MediaVault HanimeTV relay (Cloudflare Worker).
//
// HanimeTV answers datacenter addresses (the Oracle VM) with a Cloudflare 403
// before it processes signed API requests. Following anime-src/hanime-stremio,
// the MediaVault server sends the two small requests it needs through this
// Worker; video segments and keys are still fetched by the server directly.
// The Worker solves nothing and forwards no cookies or accounts: two fixed
// upstreams, a shared secret, size limits.
const HANDSHAKE = 'https://auth.hanime.tv/api/v11/handshake';
const PLAYLIST = /^\/hls\/\d{1,10}\/[A-Za-z0-9]{16,600}$/;
const BROWSER = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36';
const SIGNED = ['x-signature', 'x-signature-version', 'x-time', 'x-csrf-token'];
const MAX_BODY = 16 * 1024;
const MAX_PLAYLIST = 1024 * 1024;

async function digest(value) {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)));
}

async function authorized(request, env) {
  const secret = (env.RELAY_SECRET || '').trim();
  if (secret.length < 32) return false;
  const given = await digest(request.headers.get('authorization') || '');
  const expected = await digest('Bearer ' + secret);
  let difference = 0;
  for (let i = 0; i < expected.length; i++) difference |= given[i] ^ expected[i];
  return difference === 0;
}

function reply(status, body, headers = {}) {
  return new Response(body, { status, headers: { 'cache-control': 'no-store', ...headers } });
}

const site = { 'user-agent': BROWSER, origin: 'https://hanime.tv', referer: 'https://hanime.tv/' };

async function handshake(request) {
  if (!(request.headers.get('content-type') || '').startsWith('application/json')) return reply(415, 'JSON required');
  const body = await request.arrayBuffer();
  if (body.byteLength === 0 || body.byteLength > MAX_BODY) return reply(413, 'Body size');
  const headers = { ...site, accept: 'application/json', 'content-type': 'application/json' };
  for (const name of SIGNED) {
    const value = request.headers.get(name);
    if (value && value.length <= 256) headers[name] = value;
  }
  const upstream = await fetch(HANDSHAKE, { method: 'POST', headers, body, redirect: 'manual' });
  const out = { 'content-type': upstream.headers.get('content-type') || 'application/json' };
  const token = upstream.headers.get('x-token');
  if (token) out['x-token'] = token;
  if (upstream.headers.get('cf-mitigated')) out['x-upstream-challenge'] = '1';
  return reply(upstream.status, await upstream.text(), out);
}

async function playlist(path) {
  const upstream = await fetch('https://hanime.tv' + path, {
    headers: { ...site, accept: 'application/vnd.apple.mpegurl,application/x-mpegURL,*/*' }, redirect: 'manual',
  });
  const text = await upstream.text();
  if (text.length > MAX_PLAYLIST) return reply(502, 'Playlist too large');
  const out = { 'content-type': upstream.headers.get('content-type') || 'application/vnd.apple.mpegurl' };
  if (upstream.headers.get('cf-mitigated')) out['x-upstream-challenge'] = '1';
  return reply(upstream.status, text, out);
}

export default {
  async fetch(request, env) {
    if (!(await authorized(request, env))) return reply(401, 'Unauthorized');
    const url = new URL(request.url);
    if (url.search) return reply(404, 'Not found');
    if (request.method === 'POST' && url.pathname === '/handshake') return handshake(request);
    if (request.method === 'GET' && PLAYLIST.test(url.pathname)) return playlist(url.pathname);
    return reply(404, 'Not found');
  },
};
