use std::collections::HashMap;
use std::fs::File;
use std::io::BufWriter;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use anyhow::Result;
use arrow::array::{
    Array, Float64Array, RecordBatch, RecordBatchReader, UInt16Array, UInt64Array, UInt8Array,
};
use arrow::compute::{cast, take};
use arrow::datatypes::{DataType, Field, Schema};
use arrow::ipc::writer::{IpcWriteOptions, StreamWriter};
use base64::prelude::BASE64_STANDARD;
use base64::Engine;
use parquet::arrow::ArrowWriter;
use parquet::basic::{Compression as ParquetCompression, ZstdLevel};
use parquet::file::properties::WriterProperties;
use pmtiles::{Compression, Compressor, PmTilesWriter, TileType, PYRAMID_SIZE_BY_ZOOM};
use pyo3::exceptions::{PyIOError, PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use rayon::prelude::*;
use serde_json::json;

const MAX_SPILL_ZOOM: u8 = 20;
const COARSE_MAX_Z: u8 = 6;
const COARSE_TILES: usize = 5_461; // (4^7 - 1) / 3
const MID_MAX_Z: u8 = 9;
const MID_TILES: usize = 349_525 - COARSE_TILES; // (4^10 - 1) / 3 - 5461

const RESERVED_OUTPUT_COLUMNS: &[&str] = &["x_u16", "y_u16", "z", "final_tile_id"];

const RESERVED_METADATA_KEYS: &[&str] = &[
    "format",
    "version",
    "arrow_schema",
    "bounds",
    "priority",
    "sampling",
    "grid_size",
    "nominal_max_zoom",
    "tile_capacity",
    "max_tile_rows",
    "total_rows",
    "dropped_rows",
    "dropped_columns",
    "stats",
    "tile_stats",
    "view",
    "layers",
    "edges",
];

fn take_ffi_stream(stream_ptr: usize) -> Result<arrow::ffi_stream::ArrowArrayStreamReader> {
    if stream_ptr == 0 {
        anyhow::bail!("Null FFI_ArrowArrayStream pointer passed across FFI boundary");
    }
    let ptr = stream_ptr as *mut arrow::ffi_stream::FFI_ArrowArrayStream;
    let stream =
        unsafe { std::ptr::replace(ptr, arrow::ffi_stream::FFI_ArrowArrayStream::empty()) };
    Ok(arrow::ffi_stream::ArrowArrayStreamReader::try_new(stream)?)
}

#[pyfunction]
fn init_threadpool(threads: usize) -> PyResult<()> {
    let _ = rayon::ThreadPoolBuilder::new()
        .num_threads(threads)
        .build_global();
    Ok(())
}

#[pyfunction]
#[pyo3(signature = (
    stream_ptr,
    output_dir,
    nominal_max_zoom,
    tile_capacity,
    max_tile_rows,
    grid_size,
    sampling_mode,
    allow_oversize_leaves,
    x_col_name,
    y_col_name,
    z_buffer_limit
))]
#[allow(clippy::too_many_arguments)]
fn run_bucketer(
    py: Python,
    stream_ptr: usize,
    output_dir: String,
    nominal_max_zoom: u8,
    tile_capacity: u32,
    max_tile_rows: u32,
    grid_size: usize,
    sampling_mode: String,
    allow_oversize_leaves: bool,
    x_col_name: String,
    y_col_name: String,
    z_buffer_limit: usize,
) -> PyResult<(u8, u32, u64)> {
    run_bucketer_impl(
        py,
        stream_ptr,
        output_dir,
        nominal_max_zoom,
        tile_capacity,
        max_tile_rows,
        grid_size,
        sampling_mode,
        allow_oversize_leaves,
        x_col_name,
        y_col_name,
        z_buffer_limit,
    )
    .map_err(|e| PyRuntimeError::new_err(e.to_string()))
}

#[allow(clippy::too_many_arguments)]
fn run_bucketer_impl(
    py: Python,
    stream_ptr: usize,
    output_dir: String,
    nominal_max_zoom: u8,
    tile_capacity: u32,
    max_tile_rows: u32,
    grid_size: usize,
    sampling_mode: String,
    allow_oversize_leaves: bool,
    x_col_name: String,
    y_col_name: String,
    z_buffer_limit: usize,
) -> Result<(u8, u32, u64)> {
    let mut reader = take_ffi_stream(stream_ptr)?;

    let is_even_coverage = match sampling_mode.as_str() {
        "even_coverage" => true,
        "proportional" => false,
        other => anyhow::bail!(
            "Unsupported sampling_mode '{}': expected 'even_coverage' or 'proportional'",
            other
        ),
    };

    let nom_z = nominal_max_zoom.min(MAX_SPILL_ZOOM);
    let eff_tile_cap = tile_capacity.max(1);
    let eff_leaf_cap = max_tile_rows.max(eff_tile_cap);
    let grid_int = grid_size.clamp(16, 512);

    let input_schema = reader.schema().clone();

    // Validate required row_id column and ensure no collisions with reserved output names
    let row_id_field = input_schema
        .field_with_name("row_id")
        .map_err(|_| anyhow::anyhow!("Required 'row_id' (UInt64) column missing from Pass 1 stream"))?;
    if row_id_field.data_type() != &DataType::UInt64 {
        anyhow::bail!(
            "Column 'row_id' must have Arrow DataType::UInt64, found {:?}",
            row_id_field.data_type()
        );
    }

    let mut out_fields = Vec::new();
    for f in input_schema.fields() {
        let name = f.name().as_str();
        if name == x_col_name || name == y_col_name {
            continue;
        }
        if RESERVED_OUTPUT_COLUMNS.contains(&name) {
            anyhow::bail!(
                "Input column '{}' collides with a reserved ArrowTiles column name",
                name
            );
        }
        if name.starts_with("__at_") && name != "__at_sort_key" {
            anyhow::bail!(
                "Input column '{}' uses reserved '__at_' prefix",
                name
            );
        }
        out_fields.push(f.clone());
    }
    out_fields.push(Arc::new(Field::new("x_u16", DataType::UInt16, false)));
    out_fields.push(Arc::new(Field::new("y_u16", DataType::UInt16, false)));
    out_fields.push(Arc::new(Field::new("z", DataType::UInt8, false)));
    out_fields.push(Arc::new(Field::new(
        "final_tile_id",
        DataType::UInt64,
        false,
    )));

    let output_schema = Arc::new(Schema::new(out_fields));

    let words_per_tile = (grid_int * grid_int + 63) / 64;
    let mut coarse_bitsets: Vec<u64> = if is_even_coverage {
        vec![0_u64; COARSE_TILES * words_per_tile]
    } else {
        Vec::new()
    };
    let mut coarse_counts: Vec<u32> = vec![0_u32; COARSE_TILES];
    let mut mid_counts: Vec<u32> = vec![0_u32; MID_TILES];
    let mut deep_counts: HashMap<u64, u32> = HashMap::new();

    let mut max_z20_rows: u32 = 0;

    let writer_props = WriterProperties::builder()
        .set_max_row_group_row_count(Some(100_000))
        .set_compression(ParquetCompression::ZSTD(ZstdLevel::try_new(1)?))
        .build();

    let mut actual_max_z: u8 = 0;
    let mut row_count: u64 = 0;

    let mut writers: HashMap<u8, ArrowWriter<File>> = HashMap::new();
    let mut z_buffers: HashMap<u8, Vec<RecordBatch>> = HashMap::new();
    let mut z_buffer_rows: HashMap<u8, usize> = HashMap::new();

    loop {
        let batch_res = reader.next();
        let batch = match batch_res {
            Some(Ok(b)) => b,
            Some(Err(e)) => return Err(e.into()),
            None => break,
        };

        let num_rows = batch.num_rows();
        if num_rows == 0 {
            continue;
        }

        let row_id_col = batch
            .column_by_name("row_id")
            .ok_or_else(|| anyhow::anyhow!("row_id column missing"))?;
        if row_id_col.null_count() > 0 {
            anyhow::bail!("Column 'row_id' contains NULL values");
        }

        let x_col = batch
            .column_by_name(&x_col_name)
            .ok_or_else(|| anyhow::anyhow!("x column '{}' missing", x_col_name))?;
        let y_col = batch
            .column_by_name(&y_col_name)
            .ok_or_else(|| anyhow::anyhow!("y column '{}' missing", y_col_name))?;

        if x_col.null_count() > 0 || y_col.null_count() > 0 {
            anyhow::bail!(
                "NULL coordinate encountered in run_bucketer; filter coordinates before Pass 1"
            );
        }

        let x_f64 = cast(x_col, &DataType::Float64)?;
        let y_f64 = cast(y_col, &DataType::Float64)?;

        let x_arr = x_f64
            .as_any()
            .downcast_ref::<Float64Array>()
            .ok_or_else(|| anyhow::anyhow!("Failed to downcast x to Float64Array"))?;
        let y_arr = y_f64
            .as_any()
            .downcast_ref::<Float64Array>()
            .ok_or_else(|| anyhow::anyhow!("Failed to downcast y to Float64Array"))?;

        let x_vals = x_arr.values();
        let y_vals = y_arr.values();
        let saw_non_finite = AtomicBool::new(false);

        // Stage A (Parallel, Stateless): compute (ix_20, iy_20, h_20) once per row
        // Stage B (Sequential, Deterministic): claim cells/counters in strict priority order
        let (z_vec, tid_vec, x_u16_vec, y_u16_vec, z_indices, batch_max_z) =
            py.allow_threads(|| -> Result<_> {
                let n20 = (1_u64 << MAX_SPILL_ZOOM) as f64;
                let max_idx_20 = (1_u32 << MAX_SPILL_ZOOM) - 1;

                let stage_a: Vec<(u32, u32, u64)> = (0..num_rows)
                    .into_par_iter()
                    .map(|i| {
                        let raw_x = x_vals[i];
                        let raw_y = y_vals[i];
                        if !raw_x.is_finite() || !raw_y.is_finite() {
                            saw_non_finite.store(true, Ordering::Relaxed);
                            return (0, 0, 0);
                        }
                        let x = raw_x.clamp(0.0, 1.0);
                        let y = raw_y.clamp(0.0, 1.0);
                        let ix_20 = (x * n20).min(max_idx_20 as f64) as u32;
                        let iy_20 = (y * n20).min(max_idx_20 as f64) as u32;
                        let h_20 = fast_hilbert::xy2h(ix_20, iy_20, MAX_SPILL_ZOOM);
                        (ix_20, iy_20, h_20)
                    })
                    .collect();

                if saw_non_finite.load(Ordering::Relaxed) {
                    anyhow::bail!(
                        "Non-finite or NULL coordinate encountered in run_bucketer; filter coordinates before Pass 1"
                    );
                }

                let mut z_vec = Vec::with_capacity(num_rows);
                let mut tid_vec = Vec::with_capacity(num_rows);
                let mut x_u16_vec = Vec::with_capacity(num_rows);
                let mut y_u16_vec = Vec::with_capacity(num_rows);
                let mut z_indices: [Vec<u32>; (MAX_SPILL_ZOOM as usize) + 1] =
                    std::array::from_fn(|_| Vec::new());
                let mut local_max_z: u8 = 0;
                let grid_f64 = grid_int as f64;

                for (i, &(ix_20, iy_20, h_20)) in stage_a.iter().enumerate() {
                    let x = x_vals[i].clamp(0.0, 1.0);
                    let y = y_vals[i].clamp(0.0, 1.0);

                    let mut assigned_z = nom_z;
                    let mut final_tid = 0_u64;
                    let mut final_x_u16 = 0_u16;
                    let mut final_y_u16 = 0_u16;

                    for z in 0..=MAX_SPILL_ZOOM {
                        let shift = MAX_SPILL_ZOOM - z;
                        let ix = ix_20 >> shift;
                        let iy = iy_20 >> shift;
                        let h_z = if z == 0 { 0 } else { h_20 >> (2 * shift) };
                        let tid = PYRAMID_SIZE_BY_ZOOM[z as usize] + h_z;

                        let cap_for_z = if z < nom_z {
                            eff_tile_cap
                        } else {
                            eff_leaf_cap
                        };

                        let claimed = if z == MAX_SPILL_ZOOM {
                            let count = deep_counts
                                .entry(tid)
                                .and_modify(|c| *c = c.saturating_add(1))
                                .or_insert(1);
                            if *count > max_z20_rows {
                                max_z20_rows = *count;
                            }
                            true
                        } else if z <= COARSE_MAX_Z && is_even_coverage && z < nom_z {
                            let n = (1_u64 << z) as f64;
                            let local_x = (x * n - (ix as f64)).clamp(0.0, 1.0);
                            let local_y = (y * n - (iy as f64)).clamp(0.0, 1.0);
                            let gx = ((local_x * grid_f64) as usize).min(grid_int - 1);
                            let gy = ((local_y * grid_f64) as usize).min(grid_int - 1);
                            let bit_idx = gy * grid_int + gx;
                            let word_idx = (tid as usize) * words_per_tile + (bit_idx >> 6);
                            let mask = 1_u64 << (bit_idx & 63);
                            let prev = coarse_bitsets[word_idx];
                            if (prev & mask) == 0 {
                                coarse_bitsets[word_idx] = prev | mask;
                                final_x_u16 = (local_x * 65535.0).round().clamp(0.0, 65535.0) as u16;
                                final_y_u16 = (local_y * 65535.0).round().clamp(0.0, 65535.0) as u16;
                                assigned_z = z;
                                final_tid = tid;
                                break;
                            }
                            false
                        } else if z <= COARSE_MAX_Z {
                            let cur = &mut coarse_counts[tid as usize];
                            if *cur < cap_for_z {
                                *cur += 1;
                                true
                            } else {
                                false
                            }
                        } else if z <= MID_MAX_Z {
                            let cur = &mut mid_counts[(tid as usize) - COARSE_TILES];
                            if *cur < cap_for_z {
                                *cur += 1;
                                true
                            } else {
                                false
                            }
                        } else {
                            let cur = deep_counts.entry(tid).or_insert(0);
                            if *cur < cap_for_z {
                                *cur += 1;
                                true
                            } else {
                                false
                            }
                        };

                        if claimed {
                            let n = (1_u64 << z) as f64;
                            let local_x = (x * n - (ix as f64)).clamp(0.0, 1.0);
                            let local_y = (y * n - (iy as f64)).clamp(0.0, 1.0);
                            assigned_z = z;
                            final_tid = tid;
                            final_x_u16 = (local_x * 65535.0).round().clamp(0.0, 65535.0) as u16;
                            final_y_u16 = (local_y * 65535.0).round().clamp(0.0, 65535.0) as u16;
                            break;
                        }
                    }

                    if assigned_z > local_max_z {
                        local_max_z = assigned_z;
                    }
                    z_vec.push(assigned_z);
                    tid_vec.push(final_tid);
                    x_u16_vec.push(final_x_u16);
                    y_u16_vec.push(final_y_u16);
                    z_indices[assigned_z as usize].push(i as u32);
                }

                Ok((z_vec, tid_vec, x_u16_vec, y_u16_vec, z_indices, local_max_z))
            })?;

        if batch_max_z > actual_max_z {
            actual_max_z = batch_max_z;
        }
        row_count += num_rows as u64;

        let z_arr: Arc<dyn Array> = Arc::new(UInt8Array::from(z_vec));
        let tid_arr: Arc<dyn Array> = Arc::new(UInt64Array::from(tid_vec));
        let x_u16_arr: Arc<dyn Array> = Arc::new(UInt16Array::from(x_u16_vec));
        let y_u16_arr: Arc<dyn Array> = Arc::new(UInt16Array::from(y_u16_vec));

        let mut out_columns: Vec<Arc<dyn Array>> = Vec::with_capacity(output_schema.fields().len());
        for f in output_schema.fields() {
            let name = f.name().as_str();
            if name == "z" {
                out_columns.push(z_arr.clone());
            } else if name == "final_tile_id" {
                out_columns.push(tid_arr.clone());
            } else if name == "x_u16" {
                out_columns.push(x_u16_arr.clone());
            } else if name == "y_u16" {
                out_columns.push(y_u16_arr.clone());
            } else {
                out_columns.push(
                    batch
                        .column_by_name(name)
                        .ok_or_else(|| anyhow::anyhow!("Column '{}' missing", name))?
                        .clone(),
                );
            }
        }

        let out_batch = RecordBatch::try_new(output_schema.clone(), out_columns)?;

        for (z_usize, indices) in z_indices.into_iter().enumerate() {
            if indices.is_empty() {
                continue;
            }
            let z = z_usize as u8;
            let index_array = arrow::array::UInt32Array::from(indices);

            let mut filtered_cols = Vec::with_capacity(out_batch.num_columns());
            for col in out_batch.columns() {
                filtered_cols.push(take(col, &index_array, None)?);
            }

            let filtered_batch = RecordBatch::try_new(output_schema.clone(), filtered_cols)?;

            let buffer = z_buffers.entry(z).or_default();
            let rows = z_buffer_rows.entry(z).or_insert(0);

            *rows += filtered_batch.num_rows();
            buffer.push(filtered_batch);

            if *rows >= z_buffer_limit {
                let single_batch =
                    arrow::compute::concat_batches(&output_schema, buffer.as_slice())?;
                if !writers.contains_key(&z) {
                    let path = format!("{}/z_{}.parquet", output_dir, z);
                    let file = File::create(path)?;
                    let new_writer = ArrowWriter::try_new(
                        file,
                        output_schema.clone(),
                        Some(writer_props.clone()),
                    )?;
                    writers.insert(z, new_writer);
                }
                let writer = writers
                    .get_mut(&z)
                    .ok_or_else(|| anyhow::anyhow!("Missing writer for z={}", z))?;
                writer.write(&single_batch)?;
                buffer.clear();
                *rows = 0;
            }
        }
    }

    let observed_z20 = max_z20_rows;
    if observed_z20 > eff_leaf_cap && !allow_oversize_leaves {
        anyhow::bail!(
            "Leaf tile at z=20 exceeded max_tile_rows ({}) with {} rows (exact-duplicate coordinates). Pass --allow-oversize-leaves to permit.",
            eff_leaf_cap,
            observed_z20
        );
    }

    for (z, buffer) in z_buffers {
        if !buffer.is_empty() {
            let single_batch = arrow::compute::concat_batches(&output_schema, &buffer)?;
            if !writers.contains_key(&z) {
                let path = format!("{}/z_{}.parquet", output_dir, z);
                let file = File::create(path)?;
                let new_writer = ArrowWriter::try_new(
                    file,
                    output_schema.clone(),
                    Some(writer_props.clone()),
                )?;
                writers.insert(z, new_writer);
            }
            let writer = writers
                .get_mut(&z)
                .ok_or_else(|| anyhow::anyhow!("Missing writer for z={}", z))?;
            writer.write(&single_batch)?;
        }
    }

    for (_, writer) in writers {
        writer.close()?;
    }

    log::info!(
        "Bucketed {} rows into partitions (actual_max_z={}).",
        row_count,
        actual_max_z
    );

    Ok((actual_max_z, observed_z20, row_count))
}

struct PrecompressedZstd;

impl Compressor for PrecompressedZstd {
    fn compression(&self) -> Compression {
        Compression::Zstd
    }

    fn compress(
        &self,
        f: &mut dyn FnMut(&mut dyn std::io::Write) -> std::io::Result<()>,
        writer: &mut dyn std::io::Write,
    ) -> pmtiles::PmtResult<()> {
        f(writer)?;
        Ok(())
    }
}

#[allow(clippy::too_many_arguments)]
fn flush_chunk_buffer(
    py: Python,
    buffer: &mut Vec<(u64, Vec<RecordBatch>)>,
    rows: &mut usize,
    writer: &mut pmtiles::PmTilesStreamWriter<BufWriter<File>>,
    export_schema: &Arc<Schema>,
    global_schema_size: usize,
    declared_max_tile_rows: u32,
    observed_max_tile_rows: &mut u32,
    max_compressed_tile_bytes: &mut usize,
) -> Result<()> {
    if buffer.is_empty() {
        return Ok(());
    }

    let to_process = std::mem::take(buffer);
    *rows = 0;
    let schema = export_schema.clone();

    let processed_tiles: Vec<(u64, u32, Vec<u8>)> = py.allow_threads(|| -> Result<Vec<(u64, u32, Vec<u8>)>> {
        to_process
            .into_par_iter()
            .map(|(tid, batches)| -> Result<(u64, u32, Vec<u8>)> {
                let mut export_batches = Vec::with_capacity(batches.len());
                for b in &batches {
                    let mut cols = Vec::with_capacity(schema.fields().len());
                    for f in schema.fields() {
                        let col = b
                            .column_by_name(f.name())
                            .ok_or_else(|| anyhow::anyhow!("Missing column '{}'", f.name()))?;
                        if !f.is_nullable() && col.null_count() > 0 {
                            anyhow::bail!(
                                "Non-nullable column '{}' contains {} NULL value(s)",
                                f.name(),
                                col.null_count()
                            );
                        }
                        cols.push(col.clone());
                    }
                    export_batches.push(RecordBatch::try_new(schema.clone(), cols)?);
                }

                let single_batch = if export_batches.len() == 1 {
                    export_batches
                        .into_iter()
                        .next()
                        .ok_or_else(|| anyhow::anyhow!("Empty export_batches"))?
                } else {
                    arrow::compute::concat_batches(&schema, &export_batches)?
                };

                let tile_rows = u32::try_from(single_batch.num_rows())
                    .map_err(|_| anyhow::anyhow!("Tile {} row count overflows u32", tid))?;
                if tile_rows == 0 {
                    anyhow::bail!("Refusing to write empty tile {}", tid);
                }
                if tile_rows > declared_max_tile_rows {
                    anyhow::bail!(
                        "Tile {} has {} rows, exceeding declared max_tile_rows ({})",
                        tid,
                        tile_rows,
                        declared_max_tile_rows
                    );
                }

                let mut sink = Vec::new();
                let mut stream_writer = StreamWriter::try_new_with_options(
                    &mut sink,
                    &schema,
                    IpcWriteOptions::default(),
                )?;
                stream_writer.write(&single_batch)?;
                stream_writer.finish()?;

                if sink.len() < global_schema_size + 8 {
                    anyhow::bail!(
                        "IPC buffer too short ({} bytes < schema {} + 8) on tile {}",
                        sink.len(),
                        global_schema_size,
                        tid
                    );
                }
                let next_bytes = &sink[global_schema_size..global_schema_size + 4];
                if next_bytes != [0xFF, 0xFF, 0xFF, 0xFF] {
                    anyhow::bail!(
                        "Schema size mismatch on tile {}! Expected 0xFFFFFFFF continuation marker.",
                        tid
                    );
                }

                let compressed_bytes = zstd::bulk::compress(&sink[global_schema_size..], 3)
                    .map_err(|e| anyhow::anyhow!("Zstd compression failed: {}", e))?;

                Ok((tid, tile_rows, compressed_bytes))
            })
            .collect()
    })?;

    for (tid, tile_rows, compressed_bytes) in processed_tiles {
        if tile_rows > *observed_max_tile_rows {
            *observed_max_tile_rows = tile_rows;
        }
        if compressed_bytes.len() > *max_compressed_tile_bytes {
            *max_compressed_tile_bytes = compressed_bytes.len();
        }
        let tile_id = pmtiles::TileId::new(tid)?;
        let coord: pmtiles::TileCoord = tile_id.into();
        writer.add_tile(coord, &compressed_bytes)?;
    }

    Ok(())
}

#[pyclass(unsendable)]
struct ArrowTilesPacker {
    writer: Option<pmtiles::PmTilesStreamWriter<BufWriter<File>>>,
    output_path: String,
    tmp_path: String,
    export_schema: Arc<Schema>,
    global_schema_size: usize,
    declared_max_tile_rows: u32,
    observed_max_tile_rows: u32,
    max_compressed_tile_bytes: usize,
    last_pushed_tid: Option<u64>,
    current_tile_id: Option<u64>,
    current_batches: Vec<RecordBatch>,
    chunk_buffer: Vec<(u64, Vec<RecordBatch>)>,
    chunk_buffer_rows: usize,
    row_count: u64,
    chunk_buffer_limit: usize,
}

impl ArrowTilesPacker {
    fn push_completed_tile(&mut self, tid: u64, batches: Vec<RecordBatch>) -> PyResult<usize> {
        if let Some(prev) = self.last_pushed_tid {
            if tid <= prev {
                return Err(PyValueError::new_err(format!(
                    "Tile IDs must strictly increase in Pass 2: got {} after {}",
                    tid, prev
                )));
            }
        }
        self.last_pushed_tid = Some(tid);
        let rows: usize = batches.iter().map(|b| b.num_rows()).sum();
        self.chunk_buffer.push((tid, batches));
        self.chunk_buffer_rows += rows;
        Ok(rows)
    }
}

impl Drop for ArrowTilesPacker {
    fn drop(&mut self) {
        // If aborted before finalize(), drop the open file handle first, then remove the .tmp file
        if self.writer.take().is_some() {
            let _ = std::fs::remove_file(&self.tmp_path);
        }
    }
}

#[pymethods]
impl ArrowTilesPacker {
    #[new]
    #[pyo3(signature = (
        output_path,
        schema_stream_ptr,
        chunk_buffer_limit,
        actual_max_zoom,
        declared_max_tile_rows,
        spec_metadata_json,
        custom_metadata=None
    ))]
    fn new(
        output_path: String,
        schema_stream_ptr: usize,
        chunk_buffer_limit: usize,
        actual_max_zoom: u8,
        declared_max_tile_rows: u32,
        spec_metadata_json: String,
        custom_metadata: Option<String>,
    ) -> PyResult<Self> {
        let reader = take_ffi_stream(schema_stream_ptr)
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        let input_schema = reader.schema().clone();

        let mut out_fields = Vec::new();
        for f in input_schema.fields() {
            let name = f.name().as_str();
            if name == "final_tile_id" || name.starts_with("__at_") {
                continue;
            }
            if matches!(f.data_type(), DataType::Dictionary(_, _)) {
                return Err(PyValueError::new_err(format!(
                    "Column '{}' uses Arrow DictionaryType, which is forbidden in ArrowTiles v0.1 (use UInt8/UInt16 category codes)",
                    name
                )));
            }
            if matches!(name, "row_id" | "x_u16" | "y_u16" | "z") {
                out_fields.push(Arc::new(Field::new(name, f.data_type().clone(), false)));
            } else {
                out_fields.push(f.clone());
            }
        }
        let export_schema = Arc::new(Schema::new(out_fields));

        let mut dummy_sink = Vec::new();
        let options = IpcWriteOptions::default();
        let _stream_writer =
            StreamWriter::try_new_with_options(&mut dummy_sink, &export_schema, options)
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
        let global_schema_size = dummy_sink.len();
        if global_schema_size == 0 || global_schema_size % 8 != 0 {
            return Err(PyRuntimeError::new_err(format!(
                "Serialized Arrow IPC Schema length ({}) is not 8-byte aligned",
                global_schema_size
            )));
        }

        let b64_schema = BASE64_STANDARD.encode(&dummy_sink[0..global_schema_size]);

        let spec_val: serde_json::Value = serde_json::from_str(&spec_metadata_json)
            .map_err(|e| PyValueError::new_err(format!("Invalid spec_metadata_json: {}", e)))?;
        let mut metadata_obj = spec_val
            .as_object()
            .ok_or_else(|| PyValueError::new_err("spec_metadata_json must be a JSON object"))?
            .clone();

        if let Some(meta_str) = custom_metadata {
            if !meta_str.trim().is_empty() {
                let custom_val: serde_json::Value = serde_json::from_str(&meta_str)
                    .map_err(|e| PyValueError::new_err(format!("Invalid custom_metadata JSON: {}", e)))?;
                let custom_obj = custom_val.as_object().ok_or_else(|| {
                    PyValueError::new_err("custom_metadata must be a JSON object")
                })?;
                for (k, v) in custom_obj {
                    if RESERVED_METADATA_KEYS.contains(&k.as_str()) {
                        return Err(PyValueError::new_err(format!(
                            "Custom metadata key '{}' is reserved by the ArrowTiles specification",
                            k
                        )));
                    }
                    metadata_obj.insert(k.clone(), v.clone());
                }
            }
        }

        metadata_obj.insert("arrow_schema".to_string(), json!(b64_schema));
        let metadata_json = serde_json::Value::Object(metadata_obj).to_string();

        let tmp_path = format!("{}.tmp", output_path);
        let out_file = File::create(&tmp_path)
            .map_err(|e| PyIOError::new_err(format!("Failed to create '{}': {}", tmp_path, e)))?;
        let buf_writer = BufWriter::new(out_file);
        let writer = PmTilesWriter::new(TileType::Unknown)
            .tile_codec(PrecompressedZstd)
            .min_zoom(0)
            .max_zoom(actual_max_zoom.min(MAX_SPILL_ZOOM))
            .metadata(&metadata_json)
            .create(buf_writer)
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        Ok(ArrowTilesPacker {
            writer: Some(writer),
            output_path,
            tmp_path,
            export_schema,
            global_schema_size,
            declared_max_tile_rows: declared_max_tile_rows.max(1),
            observed_max_tile_rows: 0,
            max_compressed_tile_bytes: 0,
            last_pushed_tid: None,
            current_tile_id: None,
            current_batches: Vec::new(),
            chunk_buffer: Vec::with_capacity(1000),
            chunk_buffer_rows: 0,
            row_count: 0,
            chunk_buffer_limit,
        })
    }

    fn process_batch(&mut self, py: Python, stream_ptr: usize) -> PyResult<()> {
        if self.writer.is_none() {
            return Err(PyRuntimeError::new_err("writer already finalized"));
        }

        let mut reader = take_ffi_stream(stream_ptr)
            .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;

        loop {
            let batch_res = reader.next();
            let batch = match batch_res {
                Some(Ok(b)) => b,
                Some(Err(e)) => return Err(PyRuntimeError::new_err(e.to_string())),
                None => break,
            };

            if batch.num_rows() == 0 {
                continue;
            }

            self.row_count += batch.num_rows() as u64;

            let tile_ids_col = batch
                .column_by_name("final_tile_id")
                .ok_or_else(|| PyValueError::new_err("final_tile_id missing"))?;
            if tile_ids_col.null_count() > 0 {
                return Err(PyValueError::new_err("final_tile_id contains NULL values"));
            }
            let tile_ids = tile_ids_col
                .as_any()
                .downcast_ref::<UInt64Array>()
                .ok_or_else(|| PyValueError::new_err("final_tile_id must be UInt64"))?;

            let mut start_idx = 0;
            let mut last_tid = tile_ids.value(0);

            if let Some(ctid) = self.current_tile_id {
                if ctid != last_tid {
                    let batches = std::mem::take(&mut self.current_batches);
                    self.push_completed_tile(ctid, batches)?;

                    if self.chunk_buffer_rows >= self.chunk_buffer_limit
                        || self.chunk_buffer.len() >= 5000
                    {
                        let writer_ref = self
                            .writer
                            .as_mut()
                            .ok_or_else(|| PyRuntimeError::new_err("writer already finalized"))?;
                        flush_chunk_buffer(
                            py,
                            &mut self.chunk_buffer,
                            &mut self.chunk_buffer_rows,
                            writer_ref,
                            &self.export_schema,
                            self.global_schema_size,
                            self.declared_max_tile_rows,
                            &mut self.observed_max_tile_rows,
                            &mut self.max_compressed_tile_bytes,
                        )
                        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
                    }
                    self.current_tile_id = Some(last_tid);
                }
            } else {
                self.current_tile_id = Some(last_tid);
            }

            for i in 1..batch.num_rows() {
                let tid = tile_ids.value(i);
                if tid != last_tid {
                    self.current_batches
                        .push(batch.slice(start_idx, i - start_idx));

                    let completed_tid = self
                        .current_tile_id
                        .ok_or_else(|| PyRuntimeError::new_err("missing current_tile_id"))?;
                    let batches = std::mem::take(&mut self.current_batches);
                    self.push_completed_tile(completed_tid, batches)?;

                    if self.chunk_buffer_rows >= self.chunk_buffer_limit
                        || self.chunk_buffer.len() >= 5000
                    {
                        let writer_ref = self
                            .writer
                            .as_mut()
                            .ok_or_else(|| PyRuntimeError::new_err("writer already finalized"))?;
                        flush_chunk_buffer(
                            py,
                            &mut self.chunk_buffer,
                            &mut self.chunk_buffer_rows,
                            writer_ref,
                            &self.export_schema,
                            self.global_schema_size,
                            self.declared_max_tile_rows,
                            &mut self.observed_max_tile_rows,
                            &mut self.max_compressed_tile_bytes,
                        )
                        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
                    }

                    self.current_tile_id = Some(tid);
                    start_idx = i;
                    last_tid = tid;
                }
            }

            if start_idx < batch.num_rows() {
                self.current_batches
                    .push(batch.slice(start_idx, batch.num_rows() - start_idx));
            }
        }
        Ok(())
    }

    fn finalize(&mut self, py: Python) -> PyResult<(u64, u32, usize)> {
        let mut writer = self
            .writer
            .take()
            .ok_or_else(|| PyRuntimeError::new_err("writer already finalized"))?;

        if let Some(tid) = self.current_tile_id.take() {
            let batches = std::mem::take(&mut self.current_batches);
            if !batches.is_empty() {
                self.push_completed_tile(tid, batches)?;
            }
        }

        if let Err(e) = flush_chunk_buffer(
            py,
            &mut self.chunk_buffer,
            &mut self.chunk_buffer_rows,
            &mut writer,
            &self.export_schema,
            self.global_schema_size,
            self.declared_max_tile_rows,
            &mut self.observed_max_tile_rows,
            &mut self.max_compressed_tile_bytes,
        ) {
            drop(writer);
            let _ = std::fs::remove_file(&self.tmp_path);
            return Err(PyRuntimeError::new_err(e.to_string()));
        }

        if let Err(e) = writer.finalize() {
            let _ = std::fs::remove_file(&self.tmp_path);
            return Err(PyRuntimeError::new_err(e.to_string()));
        }

        let out_path = Path::new(&self.output_path);
        if out_path.exists() {
            std::fs::remove_file(out_path).map_err(|e| {
                PyIOError::new_err(format!(
                    "Failed to replace existing '{}': {}",
                    self.output_path, e
                ))
            })?;
        }
        std::fs::rename(&self.tmp_path, &self.output_path).map_err(|e| {
            PyIOError::new_err(format!(
                "Failed to rename '{}' -> '{}': {}",
                self.tmp_path, self.output_path, e
            ))
        })?;

        log::info!(
            "Packed {} rows (max_tile_rows={}, max_compressed_tile_bytes={})",
            self.row_count,
            self.observed_max_tile_rows,
            self.max_compressed_tile_bytes
        );

        Ok((
            self.row_count,
            self.observed_max_tile_rows,
            self.max_compressed_tile_bytes,
        ))
    }
}

#[pyfunction]
fn verify_hilbert_shift_invariants() -> PyResult<()> {
    // 1. Exhaustive verification for z = 1..=5 embedded at z = 20
    for z in 1_u8..=5_u8 {
        let shift = MAX_SPILL_ZOOM - z;
        let dim = 1_u32 << z;
        for ix in 0..dim {
            for iy in 0..dim {
                for (sub_x, sub_y) in [(0_u32, 0_u32), ((1_u32 << shift) - 1, (1_u32 << shift) - 1)] {
                    let ix_20 = (ix << shift) | sub_x;
                    let iy_20 = (iy << shift) | sub_y;
                    let h_20 = fast_hilbert::xy2h(ix_20, iy_20, MAX_SPILL_ZOOM);
                    let derived_tid = PYRAMID_SIZE_BY_ZOOM[z as usize] + (h_20 >> (2 * shift));
                    let coord = pmtiles::TileCoord::new(z, ix, iy)
                        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
                    let expected_tid: u64 = pmtiles::TileId::from(coord).into();
                    if derived_tid != expected_tid {
                        return Err(PyRuntimeError::new_err(format!(
                            "Hilbert shift mismatch at z={}, ix={}, iy={}: derived {} != expected {}",
                            z, ix, iy, derived_tid, expected_tid
                        )));
                    }
                    let parent_tid = (derived_tid - 1) >> 2;
                    let parent_coord = pmtiles::TileCoord::new(z - 1, ix >> 1, iy >> 1)
                        .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
                    let expected_parent_tid: u64 = pmtiles::TileId::from(parent_coord).into();
                    if parent_tid != expected_parent_tid {
                        return Err(PyRuntimeError::new_err(format!(
                            "Parent TileId recurrence mismatch at z={}: (tid-1)>>2 = {} != {}",
                            z, parent_tid, expected_parent_tid
                        )));
                    }
                }
            }
        }
    }

    // 2. 20,000 deterministic SplitMix64 samples across all z = 0..=20
    let mask_20 = (1_u64 << MAX_SPILL_ZOOM) - 1;
    let mut state = 0x9E37_79B9_7F4A_7C15_u64;
    for sample_idx in 0..20_000_usize {
        state = state.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z1 = (state ^ (state >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z1 = (z1 ^ (z1 >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        let r = z1 ^ (z1 >> 31);

        let ix_20 = (r & mask_20) as u32;
        let iy_20 = ((r >> 20) & mask_20) as u32;
        let h_20 = fast_hilbert::xy2h(ix_20, iy_20, MAX_SPILL_ZOOM);

        for z in 0..=MAX_SPILL_ZOOM {
            let shift = MAX_SPILL_ZOOM - z;
            let ix = ix_20 >> shift;
            let iy = iy_20 >> shift;
            let h_z = if z == 0 { 0 } else { h_20 >> (2 * shift) };
            let derived_tid = PYRAMID_SIZE_BY_ZOOM[z as usize] + h_z;
            let coord = pmtiles::TileCoord::new(z, ix, iy)
                .map_err(|e| PyRuntimeError::new_err(e.to_string()))?;
            let expected_tid: u64 = pmtiles::TileId::from(coord).into();
            if derived_tid != expected_tid {
                return Err(PyRuntimeError::new_err(format!(
                    "Hilbert shift mismatch at sample {}, z={}, ix={}, iy={}: derived {} != expected {}",
                    sample_idx, z, ix, iy, derived_tid, expected_tid
                )));
            }
        }
    }
    Ok(())
}

#[inline]
pub fn splitmix64_mix(row_id: u64, seed_u64: u64) -> u64 {
    let z0 = row_id
        .wrapping_add(seed_u64)
        .wrapping_add(0x9E37_79B9_7F4A_7C15_u64);
    let z1 = (z0 ^ (z0 >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9_u64);
    let z2 = (z1 ^ (z1 >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB_u64);
    z2 ^ (z2 >> 31)
}

#[pyfunction]
fn splitmix64_hash(row_id: u64, seed: i128) -> u64 {
    splitmix64_mix(row_id, seed as u64)
}

#[pymodule]
#[pyo3(name = "_core")]
fn arrowtiles_core(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    let _ = pyo3_log::try_init();
    m.add_function(wrap_pyfunction!(init_threadpool, m)?)?;
    m.add_function(wrap_pyfunction!(run_bucketer, m)?)?;
    m.add_function(wrap_pyfunction!(verify_hilbert_shift_invariants, m)?)?;
    m.add_function(wrap_pyfunction!(splitmix64_hash, m)?)?;
    m.add_class::<ArrowTilesPacker>()?;
    Ok(())
}
