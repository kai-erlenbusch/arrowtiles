# ArrowTiles Format Specification (`v0.1`)

**Status:** Draft `v0.1` (2026-11-19)  
**Media Type Profile:** PMTiles v3 (`TileType = Unknown`, `TileCompression = Zstd`) with schema-stripped Apache Arrow IPC `RecordBatch` payloads.

---

## 1. Identity & Container Profile

An `.arrowtiles` file **MUST** be a spec-valid **PMTiles v3** archive (`bytes 0..7 == "PMTiles"`, `SpecVersion == 3`) satisfying:

| PMTiles v3 Header Field | Required Value | Notes |
| :--- | :--- | :--- |
| `TileType` (`byte 99`) | `0x00` (`Unknown`) | Custom columnar Arrow IPC payload profile. |
| `TileCompression` (`byte 98`) | `0x04` (`Zstd`) | Every tile payload is a single Zstd frame. |
| `Clustered` (`byte 96`) | `0x01` (`true`) | Tiles written in strictly ascending PMTiles Hilbert `tile_id` order. |
| `MinZoom` (`byte 100`) | `0` | Root overview level is always `0`. |
| `MaxZoom` (`byte 101`) | `actual_max_z` ($0 \le z \le 20$) | Deepest non-empty zoom level actually written (including any leaf spill levels above `nominal_max_zoom`). |

The PMTiles JSON metadata object **MUST** include:
- `"format": "arrowtiles"`
- `"version": "0.1"` (`"<major>.<minor>"`)

**Version Handling:** Compliant readers **MUST** reject files whose `"format"` is not `"arrowtiles"` or whose major version is unknown (in `0.x`, major version `!= 0`). Legacy pre-spec archives lacking `"format"`/`"version"` **MAY** be opened in compatibility mode with a diagnostic warning.

---

## 2. Tile Payload & Arrow IPC Framing

1. **Shared Schema (`"arrow_schema"`):** Stored once in metadata as a Base64-encoded Apache Arrow IPC Stream **`Schema` message only** (`[0xFFFFFFFF][metadata_len_le32][Schema FlatBuffer + 8-byte padding]`), **without** an end-of-stream (`EOS`) marker, satisfying `decoded_len % 8 == 0`.
2. **Tile Payload:** Each tile's uncompressed payload **MUST** consist of a single Arrow IPC **`RecordBatch` message** (`BodyCompression = None`, little-endian, 8-byte aligned buffers) followed by the 8-byte `EOS` marker (`0xFFFFFFFF 0x00000000`), starting with continuation bytes `0xFFFFFFFF`. Empty (`0`-row) tiles **MUST NOT** be written.
3. **Stream Reconstruction:** Concatenating `base64_decode(arrow_schema) || zstd_decompress(tile_bytes)` yields a complete, valid Arrow IPC Stream containing one `RecordBatch`.
4. **No Dictionary Messages:** `DictionaryBatch` IPC messages and Arrow `DictionaryType` columns **MUST NOT** appear in `v0.1`. Categorical columns **MUST** be stored as unsigned integer codes (`UInt8` for $1 \dots 256$ categories; `UInt16` for $257 \dots 65,535$ categories) with missing values encoded exclusively in the Arrow validity bitmap (`nullBitmap`) and category labels stored once in `stats[col].categories`.
5. **Compressed Tile Size Limits:** Individual compressed tiles **SHOULD** remain below `16 MiB` (`16,777,216` bytes, validator warning) and **MUST NOT** exceed `64 MiB` (`67,108,864` bytes, validator error in `v0.1`; warning in `v0.0` compatibility mode). Validators **MUST** report `max_compressed_tile_bytes`.

---

## 3. Coordinate Model & Y-Axis Direction

1. **Source Bounds:** Metadata **MUST** declare `"bounds": {"min_x": <f64>, "max_x": <f64>, "min_y": <f64>, "max_y": <f64>}` in source data units (`span_x = max_x - min_x`, `span_y = max_y - min_y`, substituting `1.0` if `span == 0`).
2. **Normalization (`[0, 1]^2`) & Top-Down Y Convention:**
   - $x_{\text{norm}} = \text{clamp}\!\left(\frac{x - \text{min\_x}}{\text{span\_x}},\, 0.0,\, 1.0\right)$ (`0.0` = `min_x`/left, `1.0` = `max_x`/right).
   - $y_{\text{norm}} = \text{clamp}\!\left(\frac{\text{max\_y} - y}{\text{span\_y}},\, 0.0,\, 1.0\right)$ (**top-down**: `0.0` = `max_y`/top, `1.0` = `min_y`/bottom), matching PMTiles tile row `ty` (`0` at top, $2^z - 1$ at bottom).
3. **Tile & Sub-Tile Encoding:** At zoom $z \in [0, 20]$ ($N_z = 2^z$), tile coordinates are $t_x = \min(\lfloor x_{\text{norm}} N_z \rfloor, N_z - 1)$ and $t_y = \min(\lfloor y_{\text{norm}} N_z \rfloor, N_z - 1)$, addressed by PMTiles v3 Hilbert `tile_id` ($\text{tid}_z = \frac{4^z - 1}{3} + h_z$, where $h_z = h_{20} \gg (2(20 - z))$ and $\text{tid}_{z-1} = (\text{tid}_z - 1) \gg 2$ for $z \ge 1$). Every tile **MUST** include non-nullable columns:
   - `x_u16: UInt16` = $\text{round}((x_{\text{norm}} N_z - t_x) \cdot 65535)$
   - `y_u16: UInt16` = $\text{round}((y_{\text{norm}} N_z - t_y) \cdot 65535)$
   - `z: UInt8` = $z$
4. **Coordinate Decoding:**
   $$\hat{x}_{\text{norm}} = \frac{t_x + x_{\text{u16}} / 65535.0}{2^z}, \qquad \hat{y}_{\text{norm}} = \frac{t_y + y_{\text{u16}} / 65535.0}{2^z}$$
   $$\hat{x} = \text{min\_x} + \hat{x}_{\text{norm}} \cdot \text{span\_x}, \qquad \hat{y} = \text{max\_y} - \hat{y}_{\text{norm}} \cdot \text{span\_y}$$
   Maximum quantization error per axis at zoom $z$ is $\frac{\text{span}}{2 \cdot 65535 \cdot 2^z}$.

---

## 4. Row Identity (`row_id`) & Completeness

1. **Required Column:** Every tile **MUST** contain non-nullable `row_id: UInt64`, globally unique across the archive.
   - If a source identifier column is specified (`--id-col`), it **MUST** be unique and non-null `UInt64` (or lossless non-negative integer cast to `UInt64`).
   - For Parquet file/glob inputs without `--id-col`, the writer sorts resolved file paths lexicographically, computes contiguous per-file row offsets `file_base_offset` from Parquet metadata, and assigns `row_id = file_base_offset + file_row_number` (`0 .. input_rows - 1`).
   - Custom SQL query callers (`build(input_query=...)`) **MUST** supply an explicit deterministic `id_col`.
2. **Completeness, Non-Finite Coordinates & Dropped Columns:** Rows where source `x` or `y` is `NULL`, `NaN`, or `±Infinity` **MUST** be excluded and counted in metadata `"dropped_rows"` ($\ge 0$). Every remaining valid row (`"total_rows"`, $\ge 0$) **MUST** appear in **exactly one** tile:
   $$\sum_{t \in \text{tiles}} \text{num\_rows}(t) = \text{total\_rows}, \qquad \text{total\_rows} + \text{dropped\_rows} = \text{input\_rows}.$$
   Writers that automatically omit unrequested high-cardinality string columns (`distinct > max_categories`) **MUST** record their names in metadata `"dropped_columns": ["...", ...]` (`[]` when none were dropped).

---

## 5. Capacity, Leaf Spillover & Sampling Contract

Metadata **MUST** record `"nominal_max_zoom"` (`u8`), `"tile_capacity"` (`u32`, applied at $z < \text{nominal\_max\_zoom}$), `"max_tile_rows"` (`u32` $\ge \text{tile\_capacity}$, hard leaf cap applied at $z \ge \text{nominal\_max\_zoom}$), and `"sampling"` (`"proportional"` or `"even_coverage"`):

1. **Leaf Spillover ($z \ge \text{nominal\_max\_zoom}$):** Tiles at `nominal_max_zoom` accept up to `max_tile_rows` points; overflow rows spill into finer child tiles up to $z = 20$. If a $z = 20$ tile still exceeds the configured `max_tile_rows` (exact-duplicate coordinates), the writer **MUST** fail with the overflow count unless `--allow-oversize-leaves` is enabled, in which case metadata `"max_tile_rows"` records the actual maximum row count across all written tiles.
2. **Sampling Modes & Priority Invariant:** Let valid rows be strictly ordered by `(priority_key, row_id ASC)` from highest to lowest priority; rows within every tile **MUST** preserve this order:
   - **`"proportional"`:** Every zoom $z < \text{nominal\_max\_zoom}$ admits up to `tile_capacity` rows per tile ($z \ge \text{nominal\_max\_zoom}$ admits up to `max_tile_rows`). *Contract:* For every full tile $T$ at zoom $z$, every row in $T$ has higher priority than every row in any descendant tile $T' \subset T$ ($z' > z$).
   - **`"even_coverage"`:** Zoom levels $z \le 6$ with $z < \text{nominal\_max\_zoom}$ partition each tile into a $G \times G$ sub-grid (`"grid_size": G` in metadata, $16 \le G \le 512$) admitting **at most 1 row per `(z, tile, gx, gy)` cell**; levels $7 \le z < \text{nominal\_max\_zoom}$ use `tile_capacity`, and $z \ge \text{nominal\_max\_zoom}$ use `max_tile_rows`. *Contract:* At $z \le 6$ with $z < \text{nominal\_max\_zoom}$, the row in cell $(z, T, g_x, g_y)$ has higher priority than every row in any descendant tile $T'$ ($z' > z$) falling within that cell; otherwise, the per-tile contract holds.

---

## 6. Priority, Statistics, View Hints & Reserved Names

1. **Priority (`"priority"`):** Required metadata object:
   - Seeded random (default when unspecified): `{"kind": "random", "seed": <int>}` ranked by portable `splitmix64(row_id, seed) ASC, row_id ASC` in unsigned 64-bit wrapping arithmetic (`seed_u64 = seed & 0xFFFFFFFFFFFFFFFF`; `z0 = row_id + seed_u64 + 0x9E3779B97F4A7C15`; `z1 = (z0 ^ (z0 >> 30)) * 0xBF58476D1CE4E5B9`; `z2 = (z1 ^ (z1 >> 27)) * 0x94D049BB133111EB`; `out = z2 ^ (z2 >> 31)`).
   - Column order: `{"kind": "column", "column": "<name>", "order": "asc" | "desc"}` (`NULL`/`NaN` sorted last, ties broken by `row_id ASC`).
2. **Statistics (`"stats"`, `"tile_stats"`):**
   - `"stats"`: per-column map computed over **finite non-null** values only (RFC 8259 JSON; `NaN`/`Infinity` forbidden):
     - Numeric: `{"type": "numeric", "min": <f64>, "max": <f64>, "null_count": <u64>}`
     - Categorical: `{"type": "categorical", "categories": ["...", ...], "null_count": <u64>}` (every non-null integer code $k$ **MUST** satisfy $0 \le k < \text{len}(\text{categories})$, mapping $k \mapsto \text{categories}[k]$).
   - `"tile_stats"`: reserved optional key in metadata JSON (`null` or omitted in `v0.1`; reserved for a compact tile-indexed min/max summary directory so tile payloads stay pure Arrow IPC).
3. **Optional View Hints (`"view"`):** Optional metadata object (`colorField`, `colorMin`, `colorMax`, `sizeField`, `sizeMin`, `sizeMax`, `colorScale`, `preserveAspect`, `mode`). Readers **MUST NOT** require `"view"`. Viewers rendering categorical columns **MUST** treat `NULL`/`NaN` values as missing (never category `0`) and **SHOULD** provide at least a 64-color palette with deterministic wrap/hue-hashing above 64 categories.
4. **Reserved Identifiers & Future Extensions:**
   - **Reserved Columns:** `row_id`, `x_u16`, `y_u16`, `z`, `final_tile_id`, and prefix `__at_*` (writers **MUST** reject colliding user columns unless `row_id` is passed via `--id-col`).
   - **Reserved Metadata Keys:** `format`, `version`, `arrow_schema`, `bounds`, `priority`, `sampling`, `grid_size`, `nominal_max_zoom`, `tile_capacity`, `max_tile_rows`, `total_rows`, `dropped_rows`, `dropped_columns`, `stats`, `tile_stats`, `view`, `layers`, `edges` (writers **MUST** error on unparseable custom metadata JSON or reserved-key collisions).
   - **Reserved Future Concepts (Named Only):** `"layers"` (multi-archive auxiliary column layers) and `"edges"` (graph links).
