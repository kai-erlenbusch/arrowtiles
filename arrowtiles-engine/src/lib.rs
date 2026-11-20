use std::collections::HashMap;
use std::fs::File;
use std::io::BufWriter;
use std::sync::atomic::{AtomicU32, AtomicU64, Ordering};
use std::sync::Arc;
use arrow::array::{
    Array, Float64Array, RecordBatch, RecordBatchReader, UInt16Builder, UInt64Array, UInt64Builder, UInt8Builder,
};
use arrow::compute::{cast, take};
use arrow::datatypes::{DataType, Field, Schema};
use arrow::ipc::writer::{IpcWriteOptions, StreamWriter};
use base64::prelude::BASE64_STANDARD;
use base64::Engine;
use dashmap::DashMap;
use parquet::arrow::ArrowWriter;
use parquet::file::properties::WriterProperties;
use pmtiles::{Compression, Compressor, PmTilesWriter, TileType};
use rayon::prelude::*;
use serde_json::json;

use pyo3::prelude::*;
use pyo3::exceptions::PyRuntimeError;
use anyhow::Result;

fn take_ffi_stream(stream_ptr: usize) -> Result<arrow::ffi_stream::ArrowArrayStreamReader> {
    if stream_ptr == 0 {
        anyhow::bail!("Null FFI_ArrowArrayStream pointer passed across FFI boundary");
    }
    let ptr = stream_ptr as *mut arrow::ffi_stream::FFI_ArrowArrayStream;
    let stream = unsafe { std::ptr::replace(ptr, arrow::ffi_stream::FFI_ArrowArrayStream::empty()) };
    Ok(arrow::ffi_stream::ArrowArrayStreamReader::try_new(stream)?)
}

#[pyfunction]
fn init_threadpool(threads: usize) -> PyResult<()> {
    // Ignore error if global Rayon threadpool was already initialized in this process
    let _ = rayon::ThreadPoolBuilder::new().num_threads(threads).build_global();
    Ok(())
}

#[pyfunction]
fn run_bucketer(
    py: Python,
    stream_ptr: usize,
    output_dir: String,
    grid_size: f64,
    max_zoom: u8,
    x_col_name: String,
    y_col_name: String,
    z_buffer_limit: usize,
) -> PyResult<()> {
    match run_bucketer_impl(py, stream_ptr, output_dir, grid_size, max_zoom, x_col_name, y_col_name, z_buffer_limit) {
        Ok(_) => Ok(()),
        Err(e) => Err(PyRuntimeError::new_err(e.to_string())),
    }
}

fn run_bucketer_impl(
    py: Python,
    stream_ptr: usize,
    output_dir: String,
    grid_size: f64,
    max_zoom: u8,
    x_col_name: String,
    y_col_name: String,
    z_buffer_limit: usize,
) -> Result<()> {
    let mut reader = take_ffi_stream(stream_ptr)?;
    let effective_max_zoom = max_zoom.min(20);

    let input_schema = reader.schema().clone();

    // Output schema: input schema (minus internal coords) + x_u16, y_u16, z, final_tile_id
    let mut out_fields = Vec::new();
    for f in input_schema.fields() {
        let name = f.name().as_str();
        if name != x_col_name && name != y_col_name {
            out_fields.push(f.clone());
        }
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

    // Configure hybrid spatial quadtree capacity structures:
    // - Z = 0..=6 (5,461 tiles): lock-free sub-tile grid bitset (AtomicU64) so dense clusters
    //   never starve sparse regions in coarse overview tiles.
    // - Z = 7..=9 (344,064 tiles): lock-free flat AtomicU32 tile capacity counters (~1.37 MB).
    // - Z >= 10: sparse DashMap<u64, AtomicU32> tile capacity counters.
    let grid_int = if grid_size <= 1024.0 {
        (grid_size.round() as usize).clamp(16, 512)
    } else {
        ((grid_size.sqrt()).round() as usize).clamp(16, 512)
    };
    let tile_capacity = if grid_size <= 1024.0 {
        ((grid_int * grid_int) as u32).clamp(256, 262_144)
    } else {
        (grid_size.round() as u32).clamp(256, 262_144)
    };
    let words_per_tile = (grid_int * grid_int + 63) / 64;
    const COARSE_MAX_Z: u8 = 6;
    const COARSE_TILES: usize = 5_461; // (4^7 - 1) / 3
    const MID_MAX_Z: u8 = 9;
    const MID_TILES: usize = 349_525 - COARSE_TILES; // (4^10 - 1) / 3 - 5461

    let coarse_bitsets: Vec<AtomicU64> = (0..(COARSE_TILES * words_per_tile))
        .map(|_| AtomicU64::new(0))
        .collect();
    let mid_counts: Vec<AtomicU32> = (0..MID_TILES)
        .map(|_| AtomicU32::new(0))
        .collect();
    let deep_counts: DashMap<u64, AtomicU32> = DashMap::new();

    py.allow_threads(|| -> Result<()> {
        let mut writers: HashMap<u8, ArrowWriter<File>> = HashMap::new();
        let mut z_buffers: HashMap<u8, Vec<RecordBatch>> = HashMap::new();
        let mut z_buffer_rows: HashMap<u8, usize> = HashMap::new();
        let mut row_count: usize = 0;

        loop {
            let batch_res = Python::with_gil(|_py| reader.next());

            let batch = match batch_res {
                Some(Ok(b)) => b,
                Some(Err(e)) => return Err(e.into()),
                None => break,
            };
            
            let num_rows = batch.num_rows();
            if num_rows == 0 {
                continue;
            }
            row_count += num_rows;

            let x_col = batch.column_by_name(&x_col_name).ok_or_else(|| anyhow::anyhow!("x column missing"))?;
            let y_col = batch.column_by_name(&y_col_name).ok_or_else(|| anyhow::anyhow!("y column missing"))?;

            let x_f64 = cast(x_col, &DataType::Float64)?;
            let y_f64 = cast(y_col, &DataType::Float64)?;

            let x_arr = x_f64.as_any().downcast_ref::<Float64Array>().ok_or_else(|| anyhow::anyhow!("Failed to downcast x to Float64Array"))?;
            let y_arr = y_f64.as_any().downcast_ref::<Float64Array>().ok_or_else(|| anyhow::anyhow!("Failed to downcast y to Float64Array"))?;

            // Spatial Quadtree Downsampler: assign each row to the highest level Z where its spatial cell/tile has capacity
            let results: Vec<(u8, u64, u16, u16)> = (0..num_rows).into_par_iter().map(|i| {
                let raw_x = if x_arr.is_null(i) { 0.5 } else { x_arr.value(i) };
                let raw_y = if y_arr.is_null(i) { 0.5 } else { y_arr.value(i) };
                let x = if raw_x.is_finite() { raw_x.clamp(0.0, 1.0) } else { 0.5 };
                let y = if raw_y.is_finite() { raw_y.clamp(0.0, 1.0) } else { 0.5 };

                let mut assigned_z = effective_max_zoom;
                let mut final_tid = 0_u64;
                let mut final_x_u16 = 0_u16;
                let mut final_y_u16 = 0_u16;

                for z in 0..=effective_max_zoom {
                    let n = (1_u64 << z) as f64;
                    let max_index = (1_u32 << z).saturating_sub(1);

                    let scaled_x = x * n;
                    let scaled_y = y * n;

                    let ix = (scaled_x as u32).min(max_index);
                    let iy = (scaled_y as u32).min(max_index);

                    let local_x = scaled_x - (ix as f64);
                    let local_y = scaled_y - (iy as f64);

                    let h = fast_hilbert::xy2h(ix, iy, z);
                    let offset = ((1_u64 << (z as u32 * 2)) - 1) / 3;
                    let tid = h + offset;

                    let claimed = if z == effective_max_zoom {
                        true
                    } else if z <= COARSE_MAX_Z {
                        let gx = ((local_x * (grid_int as f64)) as usize).min(grid_int - 1);
                        let gy = ((local_y * (grid_int as f64)) as usize).min(grid_int - 1);
                        let bit_idx = gy * grid_int + gx;
                        let word_idx = (tid as usize) * words_per_tile + (bit_idx >> 6);
                        let mask = 1_u64 << (bit_idx & 63);
                        let prev = coarse_bitsets[word_idx].fetch_or(mask, Ordering::Relaxed);
                        (prev & mask) == 0
                    } else if z <= MID_MAX_Z {
                        let mid_idx = (tid as usize) - COARSE_TILES;
                        let prev = mid_counts[mid_idx].fetch_add(1, Ordering::Relaxed);
                        prev < tile_capacity
                    } else {
                        let entry = deep_counts.entry(tid).or_insert_with(|| AtomicU32::new(0));
                        let prev = entry.fetch_add(1, Ordering::Relaxed);
                        prev < tile_capacity
                    };

                    if claimed {
                        assigned_z = z;
                        final_tid = tid;
                        final_x_u16 = (local_x * 65535.0).round().clamp(0.0, 65535.0) as u16;
                        final_y_u16 = (local_y * 65535.0).round().clamp(0.0, 65535.0) as u16;
                        break;
                    }
                }

                (assigned_z, final_tid, final_x_u16, final_y_u16)
            }).collect();

            let mut z_builder = UInt8Builder::with_capacity(num_rows);
            let mut tid_builder = UInt64Builder::with_capacity(num_rows);
            let mut x_u16_builder = UInt16Builder::with_capacity(num_rows);
            let mut y_u16_builder = UInt16Builder::with_capacity(num_rows);

            for (assigned_z, tid, x_u16, y_u16) in results {
                z_builder.append_value(assigned_z);
                tid_builder.append_value(tid);
                x_u16_builder.append_value(x_u16);
                y_u16_builder.append_value(y_u16);
            }

            let z_arr = Arc::new(z_builder.finish());
            
            let mut out_columns: Vec<Arc<dyn Array>> = Vec::new();
            for f in output_schema.fields() {
                let name = f.name().as_str();
                if name == "z" {
                    out_columns.push(z_arr.clone());
                } else if name == "final_tile_id" {
                    out_columns.push(Arc::new(tid_builder.finish()));
                } else if name == "x_u16" {
                    out_columns.push(Arc::new(x_u16_builder.finish()));
                } else if name == "y_u16" {
                    out_columns.push(Arc::new(y_u16_builder.finish()));
                } else {
                    out_columns.push(batch.column_by_name(name).ok_or_else(|| anyhow::anyhow!("Column missing"))?.clone());
                }
            }

            let out_batch = RecordBatch::try_new(output_schema.clone(), out_columns)?;
            
            // O(N) single-pass grouping by Z-level to drastically optimize the previous O(N * Z) evaluation
            let mut z_indices: HashMap<u8, Vec<u32>> = HashMap::new();
            let z_arr_typed = z_arr.as_any().downcast_ref::<arrow::array::UInt8Array>().ok_or_else(|| anyhow::anyhow!("Failed to downcast z_arr"))?;
            
            for i in 0..num_rows {
                let z = z_arr_typed.value(i);
                z_indices.entry(z).or_default().push(i as u32);
            }
            
            for (z, indices) in z_indices {
                let index_array = arrow::array::UInt32Array::from(indices);
                
                let mut filtered_cols = Vec::new();
                for col in out_batch.columns() {
                    // take kernel is exponentially faster than boolean mask filtering here
                    filtered_cols.push(take(col, &index_array, None)?);
                }
                
                let filtered_batch = RecordBatch::try_new(output_schema.clone(), filtered_cols)?;
                
                let buffer = z_buffers.entry(z).or_insert_with(Vec::new);
                let rows = z_buffer_rows.entry(z).or_insert(0);
                
                *rows += filtered_batch.num_rows();
                buffer.push(filtered_batch);
                
                if *rows >= z_buffer_limit {
                    let single_batch = arrow::compute::concat_batches(&output_schema, buffer.as_slice())?;
                    if !writers.contains_key(&z) {
                        let path = format!("{}/z_{}.parquet", output_dir, z);
                        let file = File::create(path)?;
                        let props = WriterProperties::builder()
                            .set_compression(parquet::basic::Compression::UNCOMPRESSED)
                            .build();
                        let new_writer = ArrowWriter::try_new(file, output_schema.clone(), Some(props))?;
                        writers.insert(z, new_writer);
                    }
                    let writer = writers.get_mut(&z).unwrap();
                    writer.write(&single_batch)?;
                    buffer.clear();
                    *rows = 0;
                }
            }
        }

        for (z, buffer) in z_buffers.into_iter() {
            if !buffer.is_empty() {
                let single_batch = arrow::compute::concat_batches(&output_schema, &buffer)?;
                if !writers.contains_key(&z) {
                    let path = format!("{}/z_{}.parquet", output_dir, z);
                    let file = File::create(path)?;
                    let props = WriterProperties::builder()
                        .set_compression(parquet::basic::Compression::UNCOMPRESSED)
                        .build();
                    let new_writer = ArrowWriter::try_new(file, output_schema.clone(), Some(props))?;
                    writers.insert(z, new_writer);
                }
                let writer = writers.get_mut(&z).unwrap();
                writer.write(&single_batch)?;
            }
        }

        log::info!("Bucketed {} rows into partitions.", row_count);
        for (_, writer) in writers {
            writer.close()?;
        }
        Ok(())
    })?;

    Ok(())
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

fn flush_chunk_buffer(
    py: Python,
    buffer: &mut Vec<(u64, Vec<RecordBatch>)>,
    rows: &mut usize,
    writer: &mut pmtiles::PmTilesStreamWriter<BufWriter<File>>,
    export_schema: &Arc<Schema>,
    global_schema_size: usize,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    if buffer.is_empty() {
        return Ok(());
    }

    let to_process = std::mem::take(buffer);
    *rows = 0;
    let schema = export_schema.clone();

    let processed_tiles = py.allow_threads(|| -> Result<Vec<(u64, Vec<u8>)>, pyo3::PyErr> {
        let processed_tiles_res: Result<Vec<(u64, Vec<u8>)>, Box<dyn std::error::Error + Send + Sync>> = to_process
            .into_par_iter()
            .map(|(tid, batches)| -> Result<(u64, Vec<u8>), Box<dyn std::error::Error + Send + Sync>> {
                let mut export_batches = Vec::with_capacity(batches.len());
                for b in batches.iter() {
                    let mut cols = Vec::with_capacity(schema.fields().len());
                    for f in schema.fields() {
                        cols.push(b.column_by_name(f.name()).ok_or("Missing column")?.clone());
                    }
                    export_batches.push(RecordBatch::try_new(schema.clone(), cols)?);
                }

                let single_batch = if export_batches.len() == 1 {
                    export_batches.into_iter().next().unwrap()
                } else {
                    arrow::compute::concat_batches(&schema, &export_batches)?
                };
                let mut sink = Vec::new();
                let mut stream_writer = StreamWriter::try_new_with_options(
                    &mut sink,
                    &schema,
                    IpcWriteOptions::default(),
                )?;
                stream_writer.write(&single_batch)?;
                stream_writer.finish()?;
                
                if sink.len() > global_schema_size {
                    // Safely check framing, if it fails, abort because tile is corrupt
                    if sink.len() >= global_schema_size + 4 {
                        let next_bytes = &sink[global_schema_size..global_schema_size + 4];
                        if next_bytes != [0xFF, 0xFF, 0xFF, 0xFF] {
                            return Err(anyhow::anyhow!("Schema size mismatch! IPC framing shifted.").into());
                        }
                    }
                }
                let compressed_bytes = zstd::bulk::compress(&sink[global_schema_size..], 3)
                    .map_err(|e| anyhow::anyhow!("Zstd compression failed: {}", e))?;
                
                Ok((tid, compressed_bytes))
            })
            .collect();
            
        processed_tiles_res.map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))
    })?;

    for (tid, compressed_bytes) in processed_tiles {
        let tile_id = pmtiles::TileId::new(tid)?;
        let coord: pmtiles::TileCoord = tile_id.into();
        writer.add_tile(coord, &compressed_bytes)?;
    }

    Ok(())
}

#[pyclass(unsendable)]
struct ArrowTilesPacker {
    writer: Option<pmtiles::PmTilesStreamWriter<BufWriter<File>>>,
    export_schema: Arc<Schema>,
    global_schema_size: usize,
    current_tile_id: Option<u64>,
    current_batches: Vec<RecordBatch>,
    chunk_buffer: Vec<(u64, Vec<RecordBatch>)>,
    chunk_buffer_rows: usize,
    row_count: usize,
    chunk_buffer_limit: usize,
}

#[pymethods]
impl ArrowTilesPacker {
    #[new]
    #[pyo3(signature = (output_path, schema_stream_ptr, chunk_buffer_limit, custom_metadata=None))]
    fn new(output_path: String, schema_stream_ptr: usize, chunk_buffer_limit: usize, custom_metadata: Option<String>) -> PyResult<Self> {
        let reader = take_ffi_stream(schema_stream_ptr)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        let input_schema = reader.schema().clone();

        let mut out_fields = Vec::new();
        for f in input_schema.fields() {
            if f.name() != "final_tile_id" {
                out_fields.push(f.clone());
            }
        }
        let export_schema = Arc::new(Schema::new(out_fields));

        let mut dummy_sink = Vec::new();
        let options = IpcWriteOptions::default();
        let _stream_writer =
            StreamWriter::try_new_with_options(&mut dummy_sink, &export_schema, options)
                .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        let global_schema_size = dummy_sink.len();

        let b64_schema = BASE64_STANDARD.encode(&dummy_sink[0..global_schema_size]);
        
        let mut metadata_obj = serde_json::Map::new();
        metadata_obj.insert("arrow_schema".to_string(), json!(b64_schema));
        
        if let Some(meta_str) = custom_metadata {
            if let Ok(json_val) = serde_json::from_str::<serde_json::Value>(&meta_str) {
                if let Some(obj) = json_val.as_object() {
                    for (k, v) in obj {
                        metadata_obj.insert(k.clone(), v.clone());
                    }
                }
            } else {
                log::warn!("Provided custom metadata could not be parsed as JSON. Ignoring.");
            }
        }
        
        let metadata_json = serde_json::Value::Object(metadata_obj).to_string();

        let out_file = File::create(&output_path)
            .map_err(|e| pyo3::exceptions::PyIOError::new_err(e.to_string()))?;
        let buf_writer = BufWriter::new(out_file);
        let writer = PmTilesWriter::new(TileType::Unknown)
            .tile_codec(PrecompressedZstd)
            .metadata(&metadata_json)
            .create(buf_writer)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        Ok(ArrowTilesPacker {
            writer: Some(writer),
            export_schema,
            global_schema_size,
            current_tile_id: None,
            current_batches: Vec::new(),
            chunk_buffer: Vec::with_capacity(1000),
            chunk_buffer_rows: 0,
            row_count: 0,
            chunk_buffer_limit,
        })
    }

    fn process_batch(&mut self, py: Python, stream_ptr: usize) -> PyResult<()> {
        let mut reader = take_ffi_stream(stream_ptr)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        loop {
            let batch_res = reader.next();

            let batch = match batch_res {
                Some(Ok(b)) => b,
                Some(Err(e)) => return Err(pyo3::exceptions::PyRuntimeError::new_err(e.to_string())),
                None => break,
            };
            
            if batch.num_rows() == 0 {
                continue;
            }

            self.row_count += batch.num_rows();

            let tile_ids_col = batch
                .column_by_name("final_tile_id")
                .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("final_tile_id missing"))?;
            let tile_ids = tile_ids_col
                .as_any()
                .downcast_ref::<UInt64Array>()
                .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("final_tile_id must be UInt64"))?;

            let mut start_idx = 0;
            let mut last_tid = if tile_ids.is_null(0) {
                0
            } else {
                tile_ids.value(0)
            };

            if let Some(ctid) = self.current_tile_id {
                if ctid != last_tid {
                    let batches = std::mem::take(&mut self.current_batches);
                    let rows: usize = batches.iter().map(|b| b.num_rows()).sum();
                    self.chunk_buffer.push((ctid, batches));
                    self.chunk_buffer_rows += rows;

                    if self.chunk_buffer_rows >= self.chunk_buffer_limit || self.chunk_buffer.len() >= 5000 {
                        flush_chunk_buffer(
                            py,
                            &mut self.chunk_buffer,
                            &mut self.chunk_buffer_rows,
                            self.writer.as_mut().unwrap(),
                            &self.export_schema,
                            self.global_schema_size
                        ).map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
                    }
                    self.current_tile_id = Some(last_tid);
                }
            } else {
                self.current_tile_id = Some(last_tid);
            }

            for i in 1..batch.num_rows() {
                let tid = if tile_ids.is_null(i) {
                    0
                } else {
                    tile_ids.value(i)
                };
                if tid != last_tid {
                    self.current_batches.push(batch.slice(start_idx, i - start_idx));

                    let batches = std::mem::take(&mut self.current_batches);
                    let rows: usize = batches.iter().map(|b| b.num_rows()).sum();
                    self.chunk_buffer.push((self.current_tile_id.unwrap(), batches));
                    self.chunk_buffer_rows += rows;

                    if self.chunk_buffer_rows >= self.chunk_buffer_limit || self.chunk_buffer.len() >= 5000 {
                        flush_chunk_buffer(
                            py,
                            &mut self.chunk_buffer,
                            &mut self.chunk_buffer_rows,
                            self.writer.as_mut().unwrap(),
                            &self.export_schema,
                            self.global_schema_size
                        ).map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
                    }

                    self.current_tile_id = Some(tid);
                    start_idx = i;
                    last_tid = tid;
                }
            }

            if start_idx < batch.num_rows() {
                self.current_batches.push(batch.slice(start_idx, batch.num_rows() - start_idx));
            }
        }
        Ok(())
    }

    fn finalize(&mut self, py: Python) -> PyResult<()> {
        if let Some(tid) = self.current_tile_id {
            self.chunk_buffer.push((tid, std::mem::take(&mut self.current_batches)));
        }

        flush_chunk_buffer(
            py,
            &mut self.chunk_buffer,
            &mut self.chunk_buffer_rows,
            self.writer.as_mut().unwrap(),
            &self.export_schema,
            self.global_schema_size
        ).map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;

        log::info!("Packed {} rows", self.row_count);
        
        let writer = self.writer.take().ok_or_else(|| {
            pyo3::exceptions::PyRuntimeError::new_err("writer already finalized")
        })?;
        writer.finalize().map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        Ok(())
    }
}

#[pymodule]
fn arrowtiles_core(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    pyo3_log::init();
    m.add_function(wrap_pyfunction!(init_threadpool, m)?)?;
    m.add_function(wrap_pyfunction!(run_bucketer, m)?)?;
    m.add_class::<ArrowTilesPacker>()?;
    Ok(())
}
