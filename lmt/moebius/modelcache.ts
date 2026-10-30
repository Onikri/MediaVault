// Adapted from simonw/moebius-web 080be6e737ec976130e260d34707d7d9b7f63d5b (Apache-2.0).
// Persistent model caching via the Cache Storage API — the same approach Transformers.js
// uses. We key by the STABLE Hugging Face URL (…/resolve/main/<file>), not the signed CDN
// URL it redirects to. HF's redirect target carries rotating Expires/Signature query params,
// so the browser HTTP cache never hits across loads; and a redirected fetch Response can't be
// cache.put() directly. So we download the bytes once, build a fresh Response, and store it
// under the stable URL. Subsequent loads (and future sessions) read straight from the cache.

import {readModelFile,writeModelFile,removeModelFile} from "../../src/model-folder.js";
const CACHE_NAME = "moebius-onnx-v1";
const HASHES: Record<string,string> = {
 "unet.onnx":"e3f90f52f72378339b990459fadb29a68d3c7b5c6851545ba42774f489160b08",
 "vae_decoder.onnx":"d90ef0b7f6c8c8b7234459c8b449d70be0033bf1576c842e8b9991baf3934280",
 "vae_encoder.onnx":"b8b81d41e757222a0707665ba9d826703987855e5bed056036b90b988968042f",
};
async function verify(url:string,bytes:Uint8Array){
 const expected=HASHES[url.split('/').at(-1)!];
 if(!expected)throw Error('Unknown Moebius artifact');
 const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes as BufferSource))).map(n=>n.toString(16).padStart(2,'0')).join('');
 if(hash!==expected)throw Error('Moebius model checksum mismatch');
}

export interface DownloadProgress {
  (loaded: number, total: number, fromCache: boolean): void;
}

// Ask the browser to keep our storage (reduces eviction risk for ~1.2 GB of weights).
export async function requestPersistentStorage(): Promise<boolean> {
  try {
    if (navigator.storage?.persist) {
      if (await navigator.storage.persisted()) return true;
      return await navigator.storage.persist();
    }
  } catch {
    /* not supported */
  }
  return false;
}

async function openCache(): Promise<Cache | null> {
  try {
    return await caches.open(CACHE_NAME);
  } catch {
    return null; // e.g. private mode / cache disabled
  }
}

// Return the model bytes, from cache if present, else download (with progress) and cache.
export async function loadModelBytes(
  url: string,
  onProgress?: DownloadProgress,
): Promise<Uint8Array> {
  const disk = await readModelFile(url);
  if(disk){
    const bytes=new Uint8Array(await disk.arrayBuffer());
    try{await verify(url,bytes);}catch(error){await removeModelFile(url);throw error;}
    onProgress?.(bytes.length,bytes.length,true);return bytes;
  }
  const cache = await openCache();

  if (cache) {
    const hit = await cache.match(url);
    if (hit) {
      const buf = await hit.arrayBuffer();
      try{await verify(url,new Uint8Array(buf));}catch(error){await cache.delete(url);throw error;}
      await writeModelFile(url,buf).catch(()=>false);
      onProgress?.(buf.byteLength, buf.byteLength, true);
      return new Uint8Array(buf);
    }
  }

  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`fetch ${url} → HTTP ${resp.status}`);
  const total = Number(resp.headers.get("content-length")) || 0;

  let bytes: Uint8Array;
  const reader = resp.body?.getReader();
  if (reader && total > 0) {
    // preallocate one buffer (memory-efficient for ~900 MB) and fill as chunks arrive
    bytes = new Uint8Array(total);
    let loaded = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      bytes.set(value, loaded);
      loaded += value.length;
      onProgress?.(loaded, total, false);
    }
  } else {
    const buf = await resp.arrayBuffer();
    bytes = new Uint8Array(buf);
    onProgress?.(bytes.length, bytes.length, false);
  }

  await verify(url,bytes);
  await writeModelFile(url,bytes).catch(()=>false);
  if (cache) {
    try {
      // build a fresh (non-redirected) Response so it can be stored under the stable URL
      await cache.put(
        url,
        new Response(bytes.buffer as ArrayBuffer, {
          headers: {
            "Content-Type": "application/octet-stream",
            "Content-Length": String(bytes.length),
          },
        }),
      );
    } catch (e) {
      console.warn("[modelcache] cache.put failed (continuing uncached):", e);
    }
  }
  return bytes;
}

// For a "clear cache" affordance.
export async function clearModelCache(): Promise<void> {
  try {
    await caches.delete(CACHE_NAME);
  } catch {
    /* ignore */
  }
}

export async function cachedBytes(): Promise<number> {
  const cache = await openCache();
  if (!cache) return 0;
  let total = 0;
  for (const req of await cache.keys()) {
    const r = await cache.match(req);
    const len = Number(r?.headers.get("content-length")) || 0;
    total += len;
  }
  return total;
}

