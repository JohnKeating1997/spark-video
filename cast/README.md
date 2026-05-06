# cast — character pool

Characters are discovered from **two tiers**, project tier overriding global:

```
projects/<id>/cast/   ← project-specific (this folder; per-project)
./cast/               ← global pool (this README; recurring OCs, defaults)
```

If both tiers contain the same stem (e.g. `钱夫人`), the project file wins.
Use the global tier for characters you reuse across many projects.

## Filename convention

Match by **stem before the first dot**:

```
cast/
├── 佟掌柜.jpg            ← portrait, default          (REQUIRED for the character)
├── 佟掌柜.侧面.png       ← portrait, tagged view      (optional, multiple OK)
├── 佟掌柜.大笑.webp      ← portrait, tagged view
├── 佟掌柜.mp3            ← voice sample, default      (optional)
├── 佟掌柜.愤怒.mp3       ← voice sample, alt          (optional)
└── 佟掌柜.md             ← soul card                  (optional, see below)
```

- **Multiple portraits** → CLI auto-composes a grid image and feeds it to
  Wan as `reference_image`. Wan supports multi-pane references natively.
- **Multiple voice clips** → CLI concatenates them with ffmpeg and trims to
  10s (the r2v `reference_voice` upper limit).
- **Multiple `.md` files** are NOT supported — only `<name>.md` (without a tag)
  is treated as the soul card. Tagged `.md` files are ignored.

Composites live in `projects/<id>/cast_built/`. Your input files in `cast/`
and `projects/<id>/cast/` are never modified.

## Soul cards (人设档案)

Without a soul, the LLM only knows how a character *looks* and *sounds*.
With a soul, the same catchphrases, mannerisms, and relationships show up
every time the character appears — that's what makes a 5-minute video feel
like a coherent show.

Scaffold one:

```bash
# Global character (./cast/钱夫人.md)
./bin/videogen cast soul template --name 钱夫人

# Project-specific (projects/<id>/cast/钱夫人.md)
./bin/videogen cast soul template --project <id> --name 钱夫人
```

Then fill in the YAML front-matter (archetype, voice_style, catchphrases,
mannerisms, relationships, do/dont) and free-form bio. The CLI parses the
YAML; the body is fed verbatim to the director Skill.

Soul cards are **never uploaded** to OSS, and `.gitignore` keeps them out of
git by default. Use `git add -f cast/<name>.md` if you want to commit one.

## Workflow

```bash
# 1. Drop files (in either tier).
# 2. Register cast for a project (uploads + composes + parses souls):
./bin/videogen cast init --project my-video

# 3. Inspect parsed souls (this is what the director Skill consumes):
./bin/videogen cast soul show --project my-video
```

The cast table will show `Source: project|global` so you can verify which
tier each character is coming from.
