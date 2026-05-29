# Use Web Minutes List as Canonical Meeting Universe

The public OpenAPI meeting endpoints and the `record.assembly.go.kr/assembly/mnts/total/22.do` web listing do not expose the same 22대 minutes universe, while utterances are parsed only from HTML viewer pages. We will treat the web listing as the canonical meeting universe, use OpenAPI meeting endpoints only to enrich metadata and law-bill links by matching `mnts_id`, and keep PDF/HWP out of utterance extraction.
