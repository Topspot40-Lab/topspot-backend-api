"""Patch the failed 2020s Pop apply tool after audio recovery.

Removes the unneeded track_genre write (table absent in the live database) and
rehearses the entire database transaction with a rollback before any upload.
Refuses to patch an unfamiliar file or while an upload journal remains.
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"Expected exactly one original code block: {old[:90]!r}")
    return source.replace(old,new,1)


def patch_source(source: str) -> str:
    source = replace_once(source,
        '    pop_genre_id = connection.execute(text("SELECT id FROM genre WHERE slug=\'pop\'")).scalar_one()\n',
        '')
    source = replace_once(source,
        '            connection.execute(text("INSERT INTO track_genre (track_id,genre_id) VALUES (:tid,:gid)"),\n'
        '                               {"tid":tid,"gid":pop_genre_id})\n',
        '')
    source = replace_once(source,
        '    artwork = artist_artwork(plan)\n'
        '    print("DB snapshot and 90 remote/local MP3s verified; 10 rankings, 6 tracks, 4 artists will be added")\n',
        '    artwork = artist_artwork(plan)\n'
        '    # Run all intended inserts in a disposable transaction before uploading.\n'
        '    # The database rolls back all rows after this check (sequences may advance).\n'
        '    with engine.connect() as rehearsal:\n'
        '        transaction = rehearsal.begin()\n'
        '        try:\n'
        '            write_database(rehearsal, plan, artwork)\n'
        '        finally:\n'
        '            transaction.rollback()\n'
        '    print("DB transaction rehearsal passed and rolled back")\n'
        '    print("DB snapshot and 90 remote/local MP3s verified; 10 rankings, 6 tracks, 4 artists will be added")\n')
    ast.parse(source)
    return source


def main():
    path=Path('backend/scripts/apply_2020s_pop_additions.py')
    backup=path.with_suffix('.py.before_track_genre_fix')
    journal=Path('2020s-pop-backup/upload-journal.json')
    recovery=Path('2020s-pop-backup/recovery-report.json')
    if journal.exists() or not recovery.is_file():
        raise ValueError("Audio rollback must complete first; missing recovery report or upload journal still exists")
    if backup.exists():
        raise ValueError(f"Previous code backup exists; stopping without overwriting {backup}")
    original=path.read_text(encoding='utf-8')
    revised=patch_source(original)
    backup.write_text(original,encoding='utf-8')
    temp=path.with_suffix('.py.tmp')
    temp.write_text(revised,encoding='utf-8')
    temp.replace(path)
    print(f"Backed up original tool to {backup}")
    print(f"Patched {path}; sha256={hashlib.sha256(revised.encode()).hexdigest()}")
    print("Database transaction will now be rehearsed and rolled back before any upload")


if __name__ == '__main__':
    main()
