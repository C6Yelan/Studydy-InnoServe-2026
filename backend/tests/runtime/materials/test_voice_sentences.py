"""既存語音資料 schema 的安裝與回復。"""

def test_voice_sentence_migration_applies_and_rolls_back(clean_database_dsn,migrations_dir,tmp_path):
    import shutil
    import psycopg
    from runtime.storage.migrations import load_migrations,run_migrations
    previous=tmp_path/'previous';previous.mkdir()
    for path in sorted(migrations_dir.glob('*.sql'))[:26]:shutil.copyfile(path,previous/path.name)
    run_migrations(clean_database_dsn,migrations_dir=previous)
    migrations=load_migrations(migrations_dir)
    with psycopg.connect(clean_database_dsn,autocommit=True) as db:
        with db.transaction(force_rollback=True):
            db.execute(migrations[26].sql)
            db.execute('SELECT stage,timings FROM voice_turns')
        assert db.execute("SELECT to_regclass('voice_sentences')").fetchone()==(None,)
    assert run_migrations(clean_database_dsn,migrations_dir=migrations_dir)==tuple(m.version for m in migrations[26:])
