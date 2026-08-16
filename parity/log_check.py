#!/usr/bin/env python3
"""Gate on the findings log's shape: research/log/autoresearch-results.tsv.

CLAUDE.md states the row contract -- exactly four tab-separated fields, `id`,
`YYYY-MM-DD`, `kebab-case-slug`, one paragraph with no tabs and no newlines --
and says it is "checked rather than trusted".

THE RATCHET IS CLOSED. This gate was written as one, pinned at 539 legacy rows
in five older schemas that it declined to rewrite. Those rows have since been
normalised into the contract without losing a character: their extra columns
are folded into the paragraph in order, joined with ' | ', and the status tag
leads the paragraph where it is not the slug. The pin is 0 and the contract is
enforced from the first row, so there is no longer a legacy class to grow.

What that normalisation could NOT recover is the dates: 492 rows never carried
one, and the repo's first commit imported the whole log at once, so git blame
dates every legacy line to the import. Those dates are inferred from the
nearest dated row and are NOT evidence -- the file's header comment says so,
and nothing here can check it.

The gate fails if any row breaks the contract, or if an id is duplicated or goes
backwards. Legacy rows are grandfathered and named; nothing new may join them.

Usage:  log_check.py [path]        exit 0 pass, 1 fail
"""
import re
import sys

SLUG = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
# The four oldest rows are 0, 0b, 0c, 0d -- one run and three re-runs of it,
# numbered as retail's own patch letters are. Their suffix is history, not a
# typo, so ids sort as (number, suffix) rather than as integers.
ID = re.compile(r'^(\d+)([a-z]?)$')


def check(path):
    rows = open(path, encoding='utf-8').read().split('\n')
    if rows and rows[-1] == '':
        rows.pop()

    bad, conforming, ids, fail = [], 0, [], []
    for i, line in enumerate(rows, 1):
        if line.startswith('#'):
            continue
        f = line.split('\t')
        if len(f) != 4:
            bad.append((i, len(f)))
            continue
        conforming += 1
        rid, date, slug, para = f
        m = ID.match(rid)
        if not m:
            fail.append(f'row {i}: id {rid!r} is not a number')
            continue
        ids.append(((int(m.group(1)), m.group(2)), rid, i))
        if not DATE.match(date):
            fail.append(f'row {i}: date {date!r} is not YYYY-MM-DD')
        if not SLUG.match(slug):
            fail.append(f'row {i}: slug {slug!r} is not kebab-case')
        if not para.strip():
            fail.append(f'row {i}: empty paragraph')

    if bad:
        fail.append(f'{len(bad)} rows are not four fields: {bad[:3]}')

    seen = {}
    for key, rid, line in ids:
        if key in seen:
            fail.append(f'row {line}: id {rid} duplicates row {seen[key]}')
        seen[key] = line

    for (a, ra, _), (b, rb, lb) in zip(ids, ids[1:]):
        if b <= a:
            fail.append(f'row {lb}: id {rb} does not follow {ra}')
            break

    print(f'{path}: {len(rows)} rows, {conforming} conforming, {len(bad)} not')
    for m in fail:
        print('  FAIL ' + m)
    return not fail


if __name__ == '__main__':
    p = sys.argv[1] if len(sys.argv) > 1 else 'analysis/autoresearch-results.tsv'
    sys.exit(0 if check(p) else 1)
