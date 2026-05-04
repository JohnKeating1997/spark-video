# ./cast — character pool

Drop **paired files** here, one set per character:

```
cast/
├── 佟掌柜.jpg     ← portrait (jpg/png/webp, 240–8000px each side)
├── 佟掌柜.mp3     ← voice sample (wav/mp3, 1–10s, ≤15MB)
├── 钱夫人.jpg
├── 钱夫人.mp3
├── 莫小贝.png
└── 莫小贝.wav
```

Stem (the part before the dot) is the **character name**. Use it verbatim in
your script and storyboard.

After populating this folder, run:

```bash
videogen cast init --project my-video
```

The CLI uploads everything to DashScope's instant OSS bucket and writes
`projects/my-video/cast.json` with the resulting `oss://` URLs.
