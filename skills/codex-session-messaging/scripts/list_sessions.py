#!/usr/bin/env python3
"""List bounded recipient candidates from a local Codex index, without reading turns."""
import argparse
import json
from pathlib import Path
import sqlite3


def candidates(home: Path, query: str, limit: int) -> list[dict]:
    databases = list(home.glob('state_*.sqlite'))
    if len(databases) != 1:
        raise ValueError('Expected one state_*.sqlite index; use a session listing or ask for the thread ID')
    with sqlite3.connect(databases[0].as_uri() + '?mode=ro', uri=True, timeout=2) as db:
        db.execute('PRAGMA query_only = ON')
        db.row_factory = sqlite3.Row
        columns = {row['name'] for row in db.execute('PRAGMA table_info(threads)')}
        required = {'id', 'title', 'cwd', 'model_provider', 'updated_at', 'archived'}
        if not required <= columns:
            raise ValueError('Unsupported session index schema; use a session listing or ask for the thread ID')
        optional = [field for field in ('name', 'model') if field in columns]
        fields = ['id', 'substr(title, 1, 240) AS title', 'cwd', 'model_provider', 'updated_at', *optional]
        searchable = ['id', 'title', 'cwd', *optional]
        where = ' OR '.join(f'instr(lower(coalesce({field}, \'\')), lower(?)) > 0' for field in searchable)
        sql = f'SELECT {", ".join(fields)} FROM threads WHERE archived = 0 AND ({where}) ORDER BY updated_at DESC, id LIMIT ?'
        rows = db.execute(sql, [query] * len(searchable) + [limit]).fetchall()
        return [dict(row) for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', required=True, type=Path, help='Destination CODEX_HOME')
    parser.add_argument('--query', default='', help='Literal substring in ID, title, cwd, name or model')
    parser.add_argument('--limit', type=int, default=10, choices=range(1, 21), metavar='1..20')
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    try:
        rows = candidates(home, args.query, args.limit)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.exit(1, f'{exc}\n')
    print(json.dumps({'home': str(home), 'live_status': 'unknown', 'candidates': rows}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
