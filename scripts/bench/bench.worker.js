import { tableFromIPC, Type } from 'apache-arrow';
import { init as initZstd, decompress as zstdDecompress } from '@bokuweb/zstd-wasm';
import { parquetRead } from 'hyparquet';

let zstdReady = null;
function ensureZstd() {
  if (!zstdReady) zstdReady = initZstd();
  return zstdReady;
}

let arrowSchemaBytes = null;
let parquetState = null; // { url, byteLength, metadata }

function makeNoCacheAsyncBuffer(url, byteLength) {
  return {
    byteLength,
    async slice(start, end) {
      const targetEnd = end !== undefined ? end - 1 : byteLength - 1;
      const resp = await fetch(url, {
        headers: { Range: `bytes=${start}-${targetEnd}` },
        cache: 'no-store',
      });
      if (!resp.ok && resp.status !== 206) {
        throw new Error(`HTTP ${resp.status} fetching ${url} bytes=${start}-${targetEnd}`);
      }
      return await resp.arrayBuffer();
    },
  };
}

function extractArrowColumns(table, cols) {
  const xChild = table.getChild('x_u16');
  const yChild = table.getChild('y_u16');
  const numRows = table.numRows;
  const xArr = xChild.data.length === 1 ? xChild.data[0].values : xChild.toArray();
  const yArr = yChild.data.length === 1 ? yChild.data[0].values : yChild.toArray();

  const xyBuf = new ArrayBuffer(numRows * 4);
  const xyU32 = new Uint32Array(xyBuf);
  for (let i = 0; i < numRows; i++) {
    xyU32[i] = xArr[i] | (yArr[i] << 16);
  }
  const out = { xy_u16: xyBuf };
  const transfers = [xyBuf];

  for (const col of cols) {
    if (col === 'x_u16' || col === 'y_u16') continue;
    const child = table.getChild(col);
    const fBuf = new ArrayBuffer(numRows * 4);
    const f32 = new Float32Array(fBuf);
    if (!child) {
      f32.fill(NaN);
    } else {
      const isBool = child.type?.typeId === Type.Bool;
      let dst = 0;
      for (const chunk of child.data) {
        const vals = chunk.values;
        const cOff = chunk.offset || 0;
        const cLen = chunk.length;
        const hasNulls = chunk.nullCount > 0 && chunk.nullBitmap && chunk.nullBitmap.length > 0;
        const nb = chunk.nullBitmap;
        for (let i = 0; i < cLen; i++) {
          const bitIdx = cOff + i;
          if (hasNulls && (nb[bitIdx >> 3] & (1 << (bitIdx & 7))) === 0) {
            f32[dst++] = NaN;
          } else if (isBool) {
            f32[dst++] = (vals[bitIdx >> 3] & (1 << (bitIdx & 7))) !== 0 ? 1.0 : 0.0;
          } else {
            const v = vals[i];
            f32[dst++] = typeof v === 'bigint' ? Number(v) : v;
          }
        }
      }
    }
    out[col] = fBuf;
    transfers.push(fBuf);
  }
  return { numRows, out, transfers };
}

self.onmessage = async (e) => {
  const msg = e.data;
  try {
    await ensureZstd();

    if (msg.action === 'warmup') {
      self.postMessage({ id: msg.id, ok: true });
      return;
    }

    if (msg.action === 'decompress_zstd') {
      const dec = zstdDecompress(new Uint8Array(msg.buffer), { defaultHeapSize: 16 * 1024 * 1024 });
      const buf = dec.buffer.slice(dec.byteOffset, dec.byteOffset + dec.byteLength);
      self.postMessage({ id: msg.id, buffer: buf }, [buf]);
      return;
    }

    if (msg.action === 'init_arrowtiles') {
      arrowSchemaBytes = new Uint8Array(msg.schemaBytes);
      self.postMessage({ id: msg.id, ok: true });
      return;
    }

    if (msg.action === 'decode_arrowtile') {
      const t0 = performance.now();
      let raw = new Uint8Array(msg.buffer);
      if (raw.length >= 4 && raw[0] === 0x28 && raw[1] === 0xb5 && raw[2] === 0x2f && raw[3] === 0xfd) {
        raw = zstdDecompress(raw, { defaultHeapSize: 64 * 1024 * 1024 });
      }
      const table = tableFromIPC([arrowSchemaBytes, raw]);
      const { numRows, out, transfers } = extractArrowColumns(table, msg.columns);
      const decodeMs = performance.now() - t0;
      self.postMessage({ id: msg.id, numRows, columns: out, decodeMs }, transfers);
      return;
    }

    if (msg.action === 'init_parquet') {
      parquetState = {
        url: msg.url,
        byteLength: msg.byteLength,
        metadata: msg.metadata,
      };
      self.postMessage({ id: msg.id, ok: true });
      return;
    }

    if (msg.action === 'read_parquet_tile') {
      const { rowStart, rowEnd, columns, useOffsetIndex } = msg;
      const expectedRows = rowEnd - rowStart;
      const asyncFile = makeNoCacheAsyncBuffer(parquetState.url, parquetState.byteLength);

      let syncCpuDecodeMs = 0;
      const localCompressors = {
        ZSTD: (input, outputLength) => {
          const tc0 = performance.now();
          const out = zstdDecompress(input, {
            defaultHeapSize: Math.max((outputLength || 0) + 65536, 4 * 1024 * 1024),
          });
          syncCpuDecodeMs += performance.now() - tc0;
          return out;
        },
      };

      const colMap = new Map();
      await parquetRead({
        file: asyncFile,
        metadata: parquetState.metadata,
        rowStart,
        rowEnd,
        columns,
        useOffsetIndex: Boolean(useOffsetIndex),
        utf8: false,
        compressors: localCompressors,
        onChunk(chunk) {
          const tc1 = performance.now();
          // Slice chunk to exact [rowStart, rowEnd) window (critical for Page Index / large RG!)
          const overlapStart = Math.max(rowStart, chunk.rowStart);
          const overlapEnd = Math.min(rowEnd, chunk.rowEnd);
          if (overlapEnd <= overlapStart) return;
          let target = colMap.get(chunk.columnName);
          if (!target) {
            if (chunk.columnName === 'x_u16' || chunk.columnName === 'y_u16') {
              target = new Uint16Array(expectedRows);
            } else {
              target = new Float32Array(expectedRows);
            }
            colMap.set(chunk.columnName, target);
          }
          const srcOffset = overlapStart - chunk.rowStart;
          const dstOffset = overlapStart - rowStart;
          const count = overlapEnd - overlapStart;
          const srcData = chunk.columnData;
          if (ArrayBuffer.isView(srcData) && !(srcData instanceof BigInt64Array) && !(srcData instanceof BigUint64Array)) {
            target.set(srcData.subarray(srcOffset, srcOffset + count), dstOffset);
          } else {
            for (let i = 0; i < count; i++) {
              const v = srcData[srcOffset + i];
              target[dstOffset + i] = v === null || v === undefined ? NaN : typeof v === 'bigint' ? Number(v) : Number(v);
            }
          }
          syncCpuDecodeMs += performance.now() - tc1;
        },
      });

      const tc2 = performance.now();
      const xArr = colMap.get('x_u16') || new Uint16Array(expectedRows);
      const yArr = colMap.get('y_u16') || new Uint16Array(expectedRows);
      const xyBuf = new ArrayBuffer(expectedRows * 4);
      const xyU32 = new Uint32Array(xyBuf);
      for (let i = 0; i < expectedRows; i++) {
        xyU32[i] = xArr[i] | (yArr[i] << 16);
      }
      const out = { xy_u16: xyBuf };
      const transfers = [xyBuf];
      for (const col of columns) {
        if (col === 'x_u16' || col === 'y_u16') continue;
        const arr = colMap.get(col) || new Float32Array(expectedRows).fill(NaN);
        out[col] = arr.buffer;
        transfers.push(arr.buffer);
      }
      syncCpuDecodeMs += performance.now() - tc2;
      const decodeMs = syncCpuDecodeMs;
      self.postMessage({ id: msg.id, numRows: expectedRows, columns: out, decodeMs }, transfers);
      return;
    }
  } catch (err) {
    self.postMessage({ id: msg.id, error: err?.stack || err?.message || String(err) });
  }
};
