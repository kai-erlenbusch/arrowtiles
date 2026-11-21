import { PMTiles, Compression, SharedPromiseCache } from 'pmtiles';
import { decompressSync } from 'fflate';
import { parquetMetadataAsync } from 'hyparquet';
import BenchWorker from './bench.worker.js?worker';

class NoCacheFetchSource {
  constructor(url) {
    this.url = url;
  }
  getKey() {
    return this.url;
  }
  async getBytes(offset, length, signal) {
    const resp = await fetch(this.url, {
      headers: { Range: `bytes=${offset}-${offset + length - 1}` },
      cache: 'no-store',
      signal,
    });
    if (!resp.ok && resp.status !== 206) {
      throw new Error(`HTTP ${resp.status} fetching ${this.url}`);
    }
    return { data: await resp.arrayBuffer() };
  }
}

class WorkerPool {
  constructor(size = 6) {
    this.workers = [];
    this.idle = [];
    this.queue = [];
    this.resolvers = new Map();
    this.nextId = 1;
    for (let i = 0; i < size; i++) {
      const w = new BenchWorker();
      w.onerror = (err) => {
        console.error('Worker onerror:', err?.message || err);
        for (const [, res] of this.resolvers) {
          res.reject(new Error(`Worker crashed: ${err?.message || 'unknown'}`));
        }
        this.resolvers.clear();
      };
      w.onmessage = (e) => {
        const { id, error, ...rest } = e.data;
        const res = this.resolvers.get(id);
        if (res) {
          this.resolvers.delete(id);
          if (error) res.reject(new Error(error));
          else res.resolve(rest);
        }
        if (this.queue.length > 0) {
          const next = this.queue.shift();
          w.postMessage(next.msg, next.transfer);
        } else {
          this.idle.push(w);
        }
      };
      this.workers.push(w);
      this.idle.push(w);
    }
  }

  call(msg, transfer = []) {
    return new Promise((resolve, reject) => {
      const id = this.nextId++;
      const fullMsg = { ...msg, id };
      this.resolvers.set(id, { resolve, reject });
      const w = this.idle.shift();
      if (w) {
        w.postMessage(fullMsg, transfer);
      } else {
        this.queue.push({ msg: fullMsg, transfer });
      }
    });
  }

  async broadcast(msgFactory) {
    await Promise.all(
      this.workers.map((w) => {
        return new Promise((resolve, reject) => {
          const id = this.nextId++;
          const { msg, transfer } = msgFactory();
          this.resolvers.set(id, { resolve, reject });
          const idx = this.idle.indexOf(w);
          if (idx >= 0) this.idle.splice(idx, 1);
          w.postMessage({ ...msg, id }, transfer || []);
        });
      })
    );
  }

  destroy() {
    for (const w of this.workers) w.terminate();
    this.workers = [];
    this.idle = [];
  }
}

async function runWithConcurrency(items, concurrency, fn) {
  let cursor = 0;
  const results = new Array(items.length);
  const runners = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (cursor < items.length) {
      const i = cursor++;
      results[i] = await fn(items[i], i);
    }
  });
  await Promise.all(runners);
  return results;
}

let prewarmedPool = null;

window.__prepareBenchPool = async function () {
  if (prewarmedPool) prewarmedPool.destroy();
  prewarmedPool = new WorkerPool(6);
  await prewarmedPool.broadcast(() => ({ msg: { action: 'warmup' } }));
};

window.__runBenchCase = async function ({
  format, // 'arrowtiles' | 'parquet_tile_rg' | 'parquet_page_idx'
  fileUrl,
  indexUrl,
  columns,
  overviewKeys,
  deepKeys,
}) {
  const pool = prewarmedPool || new WorkerPool(6);
  if (!prewarmedPool) {
    await pool.broadcast(() => ({ msg: { action: 'warmup' } }));
  }
  prewarmedPool = null;

  let retainedBuffersBytes = 0;
  try {
    await fetch('/__tel/reset', { cache: 'no-store' });

    if (format === 'arrowtiles') {
      const dirDecompress = async (buf, compression) => {
        const code = Number(compression);
        if (compression === Compression.None || code === 1) return buf;
        if (compression === Compression.Gzip || code === 2) {
          const out = decompressSync(new Uint8Array(buf));
          return out.buffer.slice(out.byteOffset, out.byteOffset + out.byteLength);
        }
        if (code === 4) {
          const copy = buf.slice(0);
          const r = await pool.call({ action: 'decompress_zstd', buffer: copy }, [copy]);
          return r.buffer;
        }
        throw new Error(`Unsupported dir compression ${compression}`);
      };
      const tileDecompress = async (buf, compression) => {
        const code = Number(compression);
        if (compression === Compression.None || code === 1 || code === 4) return buf;
        return dirDecompress(buf, compression);
      };

      const cache = new SharedPromiseCache(2000, true, dirDecompress);
      const source = new NoCacheFetchSource(fileUrl);
      const pm = new PMTiles(source, cache, tileDecompress);

      // 1. Handshake: Header + Metadata + Schema init
      const tHs0 = performance.now();
      const header = await pm.getHeader();
      const metadata = await pm.getMetadata();
      const bin = atob(metadata.arrow_schema);
      const schemaBytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) schemaBytes[i] = bin.charCodeAt(i);
      await pool.broadcast(() => {
        const c = schemaBytes.slice();
        return { msg: { action: 'init_arrowtiles', schemaBytes: c.buffer }, transfer: [c.buffer] };
      });
      const handshakeMs = performance.now() - tHs0;
      const hsTel = await (await fetch('/__tel/get', { cache: 'no-store' })).json();

      // 2. Overview Z=0..2 (includes handshake in TTFF!)
      const tOv0 = performance.now();
      const ovResults = await runWithConcurrency(overviewKeys, 6, async (key) => {
        const [z, x, y] = key.split('/').map(Number);
        const tile = await pm.getZxy(z, x, y);
        if (!tile || !tile.data) return { numRows: 0, decodeMs: 0 };
        const buf = tile.data;
        const r = await pool.call({ action: 'decode_arrowtile', buffer: buf, columns }, [buf]);
        for (const b of Object.values(r.columns)) retainedBuffersBytes += b.byteLength;
        return r;
      });
      const overviewAfterHsMs = performance.now() - tOv0;
      const ovTel = await (await fetch('/__tel/get', { cache: 'no-store' })).json();

      // 3. Deep-zoom viewport burst
      await fetch('/__tel/reset', { cache: 'no-store' });
      const tDp0 = performance.now();
      const dpResults = await runWithConcurrency(deepKeys, 6, async (key) => {
        const [z, x, y] = key.split('/').map(Number);
        const tile = await pm.getZxy(z, x, y);
        if (!tile || !tile.data) return { numRows: 0, decodeMs: 0 };
        const buf = tile.data;
        const r = await pool.call({ action: 'decode_arrowtile', buffer: buf, columns }, [buf]);
        for (const b of Object.values(r.columns)) retainedBuffersBytes += b.byteLength;
        return r;
      });
      const deepMs = performance.now() - tDp0;
      const dpTel = await (await fetch('/__tel/get', { cache: 'no-store' })).json();

      return {
        handshakeMs,
        handshakeBytes: hsTel.bytes,
        handshakeReqs: hsTel.reqs,
        overviewTtffMs: handshakeMs + overviewAfterHsMs,
        overviewBytes: ovTel.bytes,
        overviewReqs: ovTel.reqs,
        overviewRows: ovResults.reduce((s, r) => s + r.numRows, 0),
        overviewDecodeMsSum: ovResults.reduce((s, r) => s + r.decodeMs, 0),
        deepMs,
        deepBytes: dpTel.bytes,
        deepReqs: dpTel.reqs,
        deepRows: dpResults.reduce((s, r) => s + r.numRows, 0),
        deepDecodeMsSum: dpResults.reduce((s, r) => s + r.decodeMs, 0),
        retainedBuffersMB: retainedBuffersBytes / (1024 * 1024),
        headerLeafBytes: header.leafDirectoryLength || 0,
      };
    } else {
      // Parquet Layout 1 (parquet_tile_rg) or Layout 2 (parquet_page_idx)
      const useOffsetIndex = format === 'parquet_page_idx';

      const tHs0 = performance.now();
      const [idxResp, headResp] = await Promise.all([
        fetch(indexUrl, { cache: 'no-store' }),
        fetch(fileUrl, { method: 'HEAD', cache: 'no-store' }),
      ]);
      const idxJson = await idxResp.json();
      const byteLength = Number(headResp.headers.get('content-length'));
      const mainAsyncBuf = {
        byteLength,
        async slice(start, end) {
          const targetEnd = end !== undefined ? end - 1 : byteLength - 1;
          const r = await fetch(fileUrl, {
            headers: { Range: `bytes=${start}-${targetEnd}` },
            cache: 'no-store',
          });
          return await r.arrayBuffer();
        },
      };
      const metadata = await parquetMetadataAsync(mainAsyncBuf);
      await pool.broadcast(() => ({
        msg: { action: 'init_parquet', url: fileUrl, byteLength, metadata },
      }));
      const handshakeMs = performance.now() - tHs0;
      const hsTel = await (await fetch('/__tel/get', { cache: 'no-store' })).json();

      // 2. Overview Z=0..2
      const tOv0 = performance.now();
      const ovResults = await runWithConcurrency(overviewKeys, 6, async (key) => {
        const [rowStart, rowEnd] = idxJson.tiles[key];
        const r = await pool.call({
          action: 'read_parquet_tile',
          rowStart,
          rowEnd,
          columns,
          useOffsetIndex,
        });
        for (const b of Object.values(r.columns)) retainedBuffersBytes += b.byteLength;
        return r;
      });
      const overviewAfterHsMs = performance.now() - tOv0;
      const ovTel = await (await fetch('/__tel/get', { cache: 'no-store' })).json();

      // 3. Deep-zoom viewport burst
      await fetch('/__tel/reset', { cache: 'no-store' });
      const tDp0 = performance.now();
      const dpResults = await runWithConcurrency(deepKeys, 6, async (key) => {
        const [rowStart, rowEnd] = idxJson.tiles[key];
        const r = await pool.call({
          action: 'read_parquet_tile',
          rowStart,
          rowEnd,
          columns,
          useOffsetIndex,
        });
        for (const b of Object.values(r.columns)) retainedBuffersBytes += b.byteLength;
        return r;
      });
      const deepMs = performance.now() - tDp0;
      const dpTel = await (await fetch('/__tel/get', { cache: 'no-store' })).json();

      return {
        handshakeMs,
        handshakeBytes: hsTel.bytes,
        handshakeReqs: hsTel.reqs,
        overviewTtffMs: handshakeMs + overviewAfterHsMs,
        overviewBytes: ovTel.bytes,
        overviewReqs: ovTel.reqs,
        overviewRows: ovResults.reduce((s, r) => s + r.numRows, 0),
        overviewDecodeMsSum: ovResults.reduce((s, r) => s + r.decodeMs, 0),
        deepMs,
        deepBytes: dpTel.bytes,
        deepReqs: dpTel.reqs,
        deepRows: dpResults.reduce((s, r) => s + r.numRows, 0),
        deepDecodeMsSum: dpResults.reduce((s, r) => s + r.decodeMs, 0),
        retainedBuffersMB: retainedBuffersBytes / (1024 * 1024),
      };
    }
  } finally {
    pool.destroy();
  }
};

window.__benchReady = true;
