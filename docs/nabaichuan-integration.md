# Nabaichuan Integration

Bilifan integrates with Nabaichuan through `content_bundle.json`.

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

Recommended mapping:

| Bilifan bundle field | Nabaichuan record |
| --- | --- |
| `bundle_id` | video `source_id` |
| `source.title` | video title |
| `source.platform` | video platform |
| `source.author` | author/channel |
| `summary.chapters[]` | chapter notes/cards |
| `timestamp_url` | source backlink |
| `transcript.segments[]` | optional searchable transcript |

Use:

```bash
python examples/content_bundle_to_nabaichuan.py \
  outputs/BV1abcDEF12G_p1/runs/2026-06-09_120000/content_bundle.json \
  --out /tmp/nabaichuan.jsonl
```

Include transcript segments when you want search granularity:

```bash
python examples/content_bundle_to_nabaichuan.py \
  outputs/BV1abcDEF12G_p1/runs/2026-06-09_120000/content_bundle.json \
  --out /tmp/nabaichuan.jsonl \
  --include-transcript
```

The converter does not import Nabaichuan code and does not depend on Bilifan run
directory internals. It reads only the bundle file passed on the command line.
