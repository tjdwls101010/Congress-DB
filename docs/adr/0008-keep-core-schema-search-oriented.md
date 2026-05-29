# Keep Core Schema Search-Oriented

Congress-DB is the foundation for future search APIs/SDKs, not a full archive of every upstream field. We will remove source links, source-tracking fields, and the `agenda_items` core table before Supabase migration; official meeting agenda text may be used transiently to derive `meeting_bills`, while policy topics and positions will be modeled later as a separate evidence-backed semantic layer.
