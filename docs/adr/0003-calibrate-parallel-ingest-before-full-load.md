# Calibrate parallel ingest before full load

The initial 10% load is a calibration phase, not the product goal: it measures worker counts for unknown National Assembly OpenAPI and meeting HTML limits before attempting 100% collection. For meeting metadata the calibration target is about 500 meetings across all five source APIs, and per-bill enrichment (`VCONFBILLCONFLIST`) uses the measured worker policy so the later full load can be fast without blindly increasing concurrency.
