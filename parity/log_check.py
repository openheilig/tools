#!/usr/bin/env python3
"""Gate on the findings log's shape: research/log/autoresearch-results.tsv.

CLAUDE.md states the row contract -- exactly four tab-separated fields, `id`,
`YYYY-MM-DD`, `kebab-case-slug`, one paragraph with no tabs and no newlines --
and says it is "checked rather than trusted". It was not checked. Nothing in
`checks/` or `tools/` had ever read this file, and 539 of its 853 rows do not
have four fields: an older six-field schema (`iteration/binary/metric/runs/
status/description`) accounts for 450 of them, and rows with 1, 3, 5, 7, 9 and
10 fields account for the rest.

Rewriting 539 rows of research history to satisfy a contract written after them
would destroy the record to make a gate green, so this is a RATCHET instead.
The count of non-conforming rows is pinned below. The gate fails if that count
GROWS, if a conforming row stops conforming, or if an id is duplicated or goes
backwards. Legacy rows are grandfathered and named; nothing new may join them.

Lower the pin when you genuinely fix a legacy row. Never raise it.

Usage:  log_check.py [path]        exit 0 pass, 1 fail
"""
import re
import sys

# Rows before MODERN_FROM predate the contract and are checked only for field
# count, against a pinned total. Ratchet: both numbers may fall, never rise.
# Row 661 is where the four-field schema becomes continuous; 827 is the one
# later row that never adopted it.
MODERN_FROM = 661
LEGACY_BAD_MAX = 539
GRANDFATHERED = {827}

SLUG = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def check(path):
    rows = open(path, encoding='utf-8').read().split('\n')
    if rows and rows[-1] == '':
        rows.pop()

    bad, conforming, ids, fail = [], 0, [], []
    for i, line in enumerate(rows, 1):
        f = line.split('\t')
        if len(f) != 4:
            bad.append((i, len(f)))
            continue
        conforming += 1
        rid, date, slug, para = f
        if i < MODERN_FROM or i in GRANDFATHERED:
            continue
        if not rid.isdigit():
            fail.append(f'row {i}: id {rid!r} is not a number')
            continue
        ids.append((int(rid), i))
        if not DATE.match(date):
            fail.append(f'row {i}: date {date!r} is not YYYY-MM-DD')
        if not SLUG.match(slug):
            fail.append(f'row {i}: slug {slug!r} is not kebab-case')
        if not para.strip():
            fail.append(f'row {i}: empty paragraph')

    if len(bad) > LEGACY_BAD_MAX:
        fail.append(f'{len(bad)} rows are not four fields, pin is '
                    f'{LEGACY_BAD_MAX} -- a malformed row was added: '
                    f'{bad[-3:]}')

    seen = {}
    for rid, line in ids:
        if rid in seen:
            fail.append(f'row {line}: id {rid} duplicates row {seen[rid]}')
        seen[rid] = line

    ordered = [r for r, _ in ids]
    for a, b in zip(ordered, ordered[1:]):
        if b <= a:
            fail.append(f'id {b} does not follow {a}')
            break

    print(f'{path}: {len(rows)} rows, {conforming} four-field, '
          f'{len(bad)} not (pin {LEGACY_BAD_MAX}); '
          f'contract enforced from row {MODERN_FROM}')
    for m in fail:
        print('  FAIL ' + m)
    return not fail


if __name__ == '__main__':
    p = sys.argv[1] if len(sys.argv) > 1 else 'analysis/autoresearch-results.tsv'
    sys.exit(0 if check(p) else 1)
