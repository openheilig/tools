# vk — mining the Russian Sacred communities

**Status:** Working
**Purpose:** Pull twenty years of public VK community discussion into one local,
searchable corpus, because the Russian-language Sacred scene is where the
modding knowledge went and none of it is on the open web.

The English-language record is empty on the things this project still needs. A
targeted sweep of DarkMatters (the primary English forum, ~20 years indexed)
returns **zero** rows for `sectors.wldx`, `triggers.pak`, `questcode` and
`GUI_SPELL`, and exactly one for `floor.pak` — a user asking for a tool, with no
reply. The reason is documented rather than guessed: Ascaron forbade publishing
format descriptions and sent cease-and-desist letters, so the one competent
English RE crew never reached the world data.

The Russian scene did not stop. Two of the five groups below are the **developer
groups of mods that alter the layer this project is stuck on**.

| Group | id | What it is |
|---|---|---|
| `overlookers` | 76291554 | *Sacred ReBorn HD* mod + OverLookers clan. The team an English forum post credits with **altering spawn triggers**, method never published. |
| `sacred.srrp` | 21089257 | Official **developer** group of the Raven Rock global mod-patch. |
| `sacred_nl` | 191594029 | Sacred NL, a rework built on **the mmG extension**. |
| `sacredwiki` | 8640958 | Encyclopedia / club-museum. The bulk of the corpus. |
| `sacredtribute` | 209940413 | *"Collecting and preserving EVERYTHING related to the Sacred series."* |

Measured 2026-08-24: **10,472 wall posts and 52,623 topic comments** across the
five.

```sh
python3 tools/vk/mine.py --all               # everything, resumable
python3 tools/vk/mine.py overlookers         # one group
python3 tools/vk/mine.py --search "floor.pak"
python3 tools/vk/mine.py --selftest          # no token, no network
```

## The token

**A service access key is enough** — verified 2026-08-24 against `wall.get`,
`board.getTopics` and `board.getComments` on these open communities. This was
worth verifying rather than assuming: VK's own docs now describe service keys as
being for *"методы, предназначенные для работы с играми и мини-приложениями"*,
and the `wall.get` method page was in maintenance when it was checked, so the
docs could not settle it. They still read public community content.

The key is read from `$VK_TOKEN`, or the file at `$VK_TOKEN_FILE`, or
`../donotpublish/.vk-token`. **That last path is deliberate: it is inside the
unpublished workspace.** This repository is published — never add a default that
resolves inside it, and never commit a key. Nothing here writes to VK.

## What it stores, and why in SQLite

`donotpublish/analysis/vk/vk.sqlite` — outside this repo, because it is other
people's content and not ours to redistribute.

| Table | Holds |
|---|---|
| `item` | posts, comments, topics, topic comments, each with the raw JSON kept |
| `attach` | every attachment and off-site link — `type`, `ext`, `size`, `url` |
| `ft` | FTS5 index over the text, so Russian queries work |
| `state` | one row per finished page |

`attach` is a separate table on purpose. **Files are the point** and they do not
live in a files section: `docs.get` and `photos.getAll` both return 0 for all
five groups, while a 100-post sample of `sacred.srrp` alone carries 26 links, 5
docs (`.rar`, `.torrent`) and 129 photos as post attachments. A miner that only
saved post text would have reported the groups as having no files at all.

`state` makes the run resumable at page granularity, which matters at ~700 API
calls; `SLEEP` is 0.34 s because service keys are capped at 3 requests/second.

## Reading what comes back

⚠️ **The API returns UTF-8 and is fine. The Wayback fallback is not.** Archived
`vk.com` pages serve **cp1251 bytes under a utf-8 meta tag** — decoding by the
declared charset turns every Cyrillic string into `���`. If you ever fall back to
scraping snapshots, decode `cp1251` explicitly.

⚠️ **The live site is useless without auth.** All five URLs return an SPA shell
reading `Загружается...`; `m.vk.ru` returns empty. The API is the only route, and
Wayback holds front pages only.

⚠️ This is a **research corpus, not a source of truth.** Forum claims are
documentation of behaviour, like `community/unpack-tools/` — the clean-room rule
in `AGENTS.md` applies to anything found here. A post saying how a format works
is a lead to verify against the binary, never a citation.

---
Verified by: `--selftest`, and the survey numbers above re-derived from the API.
