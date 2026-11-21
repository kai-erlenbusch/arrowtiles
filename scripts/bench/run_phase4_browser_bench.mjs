import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, '../..');
const workspaceParent = path.resolve(repoRoot, '..');
const viewerRoot = process.env.DEEPGRAPH_VIEWER_ROOT || path.join(workspaceParent, 'deepgraph-arrowtiles-sandbox');
const benchDir = __dirname;
const samplesDir = path.join(repoRoot, 'samples');
const dataDir = path.join(samplesDir, '_tmp_phase4_parquet_bench');

const argv = process.argv.slice(2);
let onlyDatasets = null;
let numRuns = 5;
let throttle50Mbps = false;
let outPath = null;

for (let i = 0; i < argv.length; i++) {
  if (argv[i] === '--only' && argv[i + 1]) {
    onlyDatasets = new Set(argv[++i].split(',').map((s) => s.trim()).filter(Boolean));
  } else if (argv[i] === '--runs' && argv[i + 1]) {
    numRuns = Math.max(1, Number(argv[++i]));
  } else if (argv[i] === '--throttle-50mbps') {
    throttle50Mbps = true;
  } else if (argv[i] === '--out' && argv[i + 1]) {
    outPath = path.resolve(argv[++i]);
  }
}
if (!outPath) {
  outPath = path.join(benchDir, throttle50Mbps ? 'phase4_results_throttled.json' : 'phase4_results.json');
}

const viteMod = await import(pathToFileURL(path.join(viewerRoot, 'node_modules/vite/dist/node/index.js')).href);
const pwMod = await import(pathToFileURL(path.join(viewerRoot, 'node_modules/@playwright/test/index.mjs')).href);

const manifest = JSON.parse(fs.readFileSync(path.join(dataDir, 'phase4_manifest.json'), 'utf8'));

// Persistent FD cache + wire telemetry plugin
function benchRangePlugin(fileRegistry) {
  const fdCache = new Map();
  let telReqs = 0;
  let telBytes = 0;

  const getEntry = (absPath) => {
    let entry = fdCache.get(absPath);
    if (!entry) {
      const st = fs.statSync(absPath);
      const fd = fs.openSync(absPath, 'r');
      entry = { fd, size: st.size };
      fdCache.set(absPath, entry);
    }
    return entry;
  };

  return {
    name: 'bench-range-server',
    configureServer(server) {
      server.httpServer?.on('close', () => {
        for (const e of fdCache.values()) {
          try { fs.closeSync(e.fd); } catch {}
        }
        fdCache.clear();
      });

      server.middlewares.use((req, res, next) => {
        if (!req.url) return next();
        const u = req.url.split('?')[0];

        if (u === '/__tel/reset') {
          telReqs = 0;
          telBytes = 0;
          res.setHeader('Content-Type', 'application/json');
          res.end('{"ok":true}');
          return;
        }
        if (u === '/__tel/get') {
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify({ reqs: telReqs, bytes: telBytes }));
          return;
        }
        if (!u.startsWith('/__bench_data/')) return next();

        const key = decodeURIComponent(u.slice('/__bench_data/'.length));
        const absPath = fileRegistry.get(key);
        if (!absPath) {
          res.statusCode = 404;
          res.end('Not found');
          return;
        }

        const entry = getEntry(absPath);
        telReqs++;
        res.setHeader('Accept-Ranges', 'bytes');
        res.setHeader('Cache-Control', 'no-store');
        res.setHeader('Content-Type', absPath.endsWith('.json') ? 'application/json' : 'application/octet-stream');

        if (req.method === 'HEAD') {
          res.statusCode = 200;
          res.setHeader('Content-Length', entry.size);
          res.end();
          return;
        }

        const range = req.headers.range;
        if (!range || !range.startsWith('bytes=')) {
          res.statusCode = 200;
          res.setHeader('Content-Length', entry.size);
          telBytes += entry.size;
          const buf = Buffer.allocUnsafe(entry.size);
          fs.readSync(entry.fd, buf, 0, entry.size, 0);
          res.end(buf);
          return;
        }

        const m = /^bytes=(\d+)-(\d*)$/.exec(range);
        if (!m) {
          res.statusCode = 416;
          res.end();
          return;
        }
        const start = Number(m[1]);
        const end = m[2] !== '' ? Math.min(Number(m[2]), entry.size - 1) : Math.min(start + 16 * 1024 * 1024 - 1, entry.size - 1);
        if (start > end || start >= entry.size) {
          res.statusCode = 416;
          res.setHeader('Content-Range', `bytes */${entry.size}`);
          res.end();
          return;
        }
        const len = end - start + 1;
        telBytes += len;
        res.statusCode = 206;
        res.setHeader('Content-Range', `bytes ${start}-${end}/${entry.size}`);
        res.setHeader('Content-Length', len);
        const buf = Buffer.allocUnsafe(len);
        fs.read(entry.fd, buf, 0, len, start, (err, n) => {
          if (err) {
            if (!res.headersSent) res.statusCode = 500;
            res.end();
            return;
          }
          res.end(n === len ? buf : buf.subarray(0, n));
        });
      });
    },
  };
}

// Register requested benchmark files
const fileRegistry = new Map();
for (const [dsName, ds] of Object.entries(manifest)) {
  if (onlyDatasets && !onlyDatasets.has(dsName)) continue;
  fileRegistry.set(`${dsName}.arrowtiles`, ds.arrowtiles.path);
  fileRegistry.set(`${dsName}_tile_rg.parquet`, ds.parquet_tile_rg.path);
  fileRegistry.set(`${dsName}_tile_rg.index.json`, ds.parquet_tile_rg.index_path);
  fileRegistry.set(`${dsName}_page_idx.parquet`, ds.parquet_page_idx.path);
  fileRegistry.set(`${dsName}_page_idx.index.json`, ds.parquet_page_idx.index_path);
}

const server = await viteMod.createServer({
  root: benchDir,
  configFile: false,
  plugins: [benchRangePlugin(fileRegistry)],
  server: {
    host: '127.0.0.1',
    port: 0,
    fs: { allow: [benchDir, viewerRoot, samplesDir, dataDir] },
  },
  optimizeDeps: {
    exclude: ['apache-arrow', 'pmtiles', 'hyparquet'],
  },
  logLevel: 'error',
});
await server.listen();
if (server.httpServer) {
  server.httpServer.keepAliveTimeout = 120_000;
  server.httpServer.headersTimeout = 125_000;
  server.httpServer.requestTimeout = 0;
}
const baseUrl = `http://127.0.0.1:${server.httpServer.address().port}`;

function median(arr) {
  const s = [...arr].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 === 1 ? s[m] : 0.5 * (s[m - 1] + s[m]);
}
function p95(arr) {
  const s = [...arr].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(s.length * 0.95))];
}
function summarizeMetric(runs, key, digits = 2) {
  const vals = runs.map((r) => r[key]);
  return {
    median: Number(median(vals).toFixed(digits)),
    p95: Number(p95(vals).toFixed(digits)),
  };
}

const THROTTLE_CONDITIONS = {
  offline: false,
  latency: 50, // 50 ms RTT
  downloadThroughput: (50 * 1000 * 1000) / 8, // 50 Mbps = 6,250,000 B/s
  uploadThroughput: (50 * 1000 * 1000) / 8,
};

let browser = null;
try {
  browser = await pwMod.chromium.launch({
    channel: 'chrome',
    headless: true,
    args: ['--js-flags=--expose-gc'],
  });
  const context = await browser.newContext();

  const finalResults = {
    generated_at: new Date().toISOString(),
    network_profile: throttle50Mbps
      ? { mode: 'cdp_throttled', latency_ms: 50, mbps: 50, bytes_per_sec: THROTTLE_CONDITIONS.downloadThroughput }
      : { mode: 'loopback_unthrottled' },
    runs_per_case: numRuns,
    datasets: {},
  };

  for (const [dsName, ds] of Object.entries(manifest)) {
    if (onlyDatasets && !onlyDatasets.has(dsName)) continue;
    console.log(
      `\n=== Benchmarking dataset: ${dsName} (${ds.total_rows.toLocaleString()} rows, ${ds.total_tiles} tiles | profile=${finalResults.network_profile.mode}) ===`
    );
    finalResults.datasets[dsName] = {
      static_info: {
        total_rows: ds.total_rows,
        total_tiles: ds.total_tiles,
        overview_tiles: ds.overview_keys.length,
        overview_rows: ds.overview_rows,
        deep_tiles: ds.deep_keys.length,
        deep_rows: ds.deep_rows,
        arrowtiles: ds.arrowtiles,
        parquet_tile_rg: ds.parquet_tile_rg,
        parquet_page_idx: ds.parquet_page_idx,
      },
      workloads: {},
    };

    for (const [wlName, cols] of Object.entries(ds.workloads)) {
      console.log(`  Workload: ${wlName} (${cols.length} cols)`);
      finalResults.datasets[dsName].workloads[wlName] = { columns: cols, formats: {} };

      for (const fmt of ['arrowtiles', 'parquet_tile_rg', 'parquet_page_idx']) {
        const fileUrl =
          fmt === 'arrowtiles'
            ? `/__bench_data/${dsName}.arrowtiles`
            : `/__bench_data/${dsName}_${fmt === 'parquet_tile_rg' ? 'tile_rg' : 'page_idx'}.parquet`;
        const indexUrl =
          fmt === 'arrowtiles'
            ? null
            : `/__bench_data/${dsName}_${fmt === 'parquet_tile_rg' ? 'tile_rg' : 'page_idx'}.index.json`;

        const runs = [];
        for (let r = 0; r < numRuns; r++) {
          const page = await context.newPage();
          page.on('pageerror', (err) => console.error('[pageerror]', err));
          page.on('console', (m) => { if (m.type() === 'error') console.error('[console.error]', m.text()); });
          const cdp = await context.newCDPSession(page);
          await cdp.send('Performance.enable');

          // Load page & warm WASM workers unthrottled first so bundle load isn't timed
          await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
          await page.waitForFunction(() => window.__benchReady === true, null, { timeout: 15000 });

          // Pre-spawn & warm worker pool BEFORE enabling network throttling so worker JS/WASM boot is untimed
          await page.evaluate(async () => await window.__prepareBenchPool());

          if (throttle50Mbps) {
            await cdp.send('Network.enable');
            await cdp.send('Network.emulateNetworkConditions', THROTTLE_CONDITIONS);
          }

          const beforeMetrics = await cdp.send('Performance.getMetrics');
          const heapBefore = beforeMetrics.metrics.find((m) => m.name === 'JSHeapUsedSize')?.value || 0;

          const runOut = await page.evaluate(
            async (args) => await window.__runBenchCase(args),
            {
              format: fmt,
              fileUrl,
              indexUrl,
              columns: cols,
              overviewKeys: ds.overview_keys,
              deepKeys: ds.deep_keys,
            }
          );

          const afterMetrics = await cdp.send('Performance.getMetrics');
          const heapAfter = afterMetrics.metrics.find((m) => m.name === 'JSHeapUsedSize')?.value || 0;
          const jsHeapDeltaMB = Math.max(0, (heapAfter - heapBefore) / (1024 * 1024));
          runOut.peakMemMB = jsHeapDeltaMB + runOut.retainedBuffersMB;

          if (runOut.overviewRows !== ds.overview_rows) {
            throw new Error(
              `Row count mismatch on ${dsName}/${wlName}/${fmt} overview: got ${runOut.overviewRows}, expected ${ds.overview_rows}`
            );
          }
          if (runOut.deepRows !== ds.deep_rows) {
            throw new Error(
              `Row count mismatch on ${dsName}/${wlName}/${fmt} deep: got ${runOut.deepRows}, expected ${ds.deep_rows}`
            );
          }

          runs.push(runOut);
          await page.close();
        }

        const summary = {
          handshake_ms: summarizeMetric(runs, 'handshakeMs', 1),
          handshake_bytes: runs[0].handshakeBytes,
          handshake_reqs: runs[0].handshakeReqs,
          overview_ttff_ms: summarizeMetric(runs, 'overviewTtffMs', 1),
          overview_bytes: runs[0].overviewBytes,
          overview_reqs: runs[0].overviewReqs,
          overview_decode_ms_sum: summarizeMetric(runs, 'overviewDecodeMsSum', 1),
          deep_zoom_ms: summarizeMetric(runs, 'deepMs', 1),
          deep_zoom_bytes: runs[0].deepBytes,
          deep_zoom_reqs: runs[0].deepReqs,
          deep_decode_ms_sum: summarizeMetric(runs, 'deepDecodeMsSum', 1),
          peak_mem_mb: summarizeMetric(runs, 'peakMemMB', 1),
        };
        finalResults.datasets[dsName].workloads[wlName].formats[fmt] = summary;
        console.log(
          `    [${fmt}] HS=${summary.handshake_ms.median}ms (${(summary.handshake_bytes / 1024).toFixed(1)} KB) | ` +
          `TTFF=${summary.overview_ttff_ms.median}ms (${(summary.overview_bytes / (1024 * 1024)).toFixed(2)} MiB, ${summary.overview_reqs} reqs) | ` +
          `Deep=${summary.deep_zoom_ms.median}ms (${(summary.deep_zoom_bytes / (1024 * 1024)).toFixed(2)} MiB, ${summary.deep_zoom_reqs} reqs)`
        );
      }
    }
  }

  fs.writeFileSync(outPath, JSON.stringify(finalResults, null, 2));
  console.log('\nSaved Phase 4 results to:', outPath);
} finally {
  if (browser) await browser.close();
  await server.close();
}
