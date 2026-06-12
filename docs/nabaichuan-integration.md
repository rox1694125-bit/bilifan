# Nabaichuan Integration

Bilifan integrates with Nabaichuan by generating JSONL files from
`content_bundle.json`. A successful Bilifan run automatically writes
`nabaichuan.jsonl` in the run directory. External systems should read or import
that JSONL file; they do not write back into Bilifan.

Stable fields:

- `schema_version`
- `bundle_id`
- `source.platform`
- `source.id`
- `source.part_id`
- `source.canonical_url`
- `source.title`
- `source.author`
- `summary.chapters`
- `summary.chapters[].timestamp_url`
- `transcript.segments`
- `provenance`

Generated Nabaichuan records use the same schema as
`bilifan.exports.build_nabaichuan_records`:

| Record type | Key fields |
| --- | --- |
| `video` | `record_id`, `content_hash`, `source`, `title`, `text` |
| `chapter` | `record_id`, `content_hash`, `source`, `chapter_id`, `parent_record_id`, `chapter_index`, `title`, `summary`, `key_points`, `start`, `end`, `timestamp_url`, `text` |
| `transcript_segment` | `record_id`, `content_hash`, `source`, `parent_record_id`, `chapter_id`, `start`, `end`, `timestamp_url`, `text` |

Manual conversion remains available when you already have a bundle file:

```bash
python examples/content_bundle_to_nabaichuan.py \
  outputs/BV1abcDEF12G_p1/runs/2026-06-09_120000/content_bundle.json \
  --out /tmp/nabaichuan.jsonl
```

Transcript segment records are included by default. `--include-transcript` is
kept for compatibility, and `--no-transcript` disables transcript segments:

```bash
python examples/content_bundle_to_nabaichuan.py \
  outputs/BV1abcDEF12G_p1/runs/2026-06-09_120000/content_bundle.json \
  --out /tmp/nabaichuan-without-transcript.jsonl \
  --no-transcript
```

The local Web UI can export one successful run to `nabaichuan.jsonl` and can
batch-export all successful history runs to a timestamped JSONL file. These
actions generate local files only; they do not call Nabaichuan APIs or mutate an
external system.

The converter does not import Nabaichuan code and does not depend on Bilifan run
directory internals. It reads only the bundle file passed on the command line
and writes JSONL to the requested output path.
