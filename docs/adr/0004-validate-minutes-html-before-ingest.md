# Validate minutes HTML before ingest

The meeting-minutes HTML endpoint can transiently return a different meeting's DOM under parallel scraping, so utterance ingest validates the parsed meeting date against `meetings.conf_date` before accepting a response. Scraping remains parallel, but the default worker count is capped at 5 until a later full-load run proves higher concurrency preserves metadata correctness, not just HTTP success.
