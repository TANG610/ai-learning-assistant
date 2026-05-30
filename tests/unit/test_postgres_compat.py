from backend.models.database import _add_postgres_returning_id, _translate_postgres_sql


def test_translate_sqlite_placeholders_and_datetime_for_postgres():
    sql = (
        "UPDATE documents SET status=?, updated_at=datetime('now','localtime') "
        "WHERE id=?"
    )

    translated = _translate_postgres_sql(sql)

    assert "status=%s" in translated
    assert "updated_at=CURRENT_TIMESTAMP" in translated
    assert "WHERE id=%s" in translated


def test_translate_sqlite_interval_datetime_for_postgres():
    sql = "SELECT * FROM news_articles WHERE created_at >= datetime('now', 'localtime', ?)"

    translated = _translate_postgres_sql(sql)

    assert "created_at >= (CURRENT_TIMESTAMP + %s::interval)" in translated


def test_insert_or_ignore_translates_to_postgres_conflict_clause():
    sql = "INSERT OR IGNORE INTO raw_collected_items (task_id, record_json) VALUES (?, ?)"

    translated = _translate_postgres_sql(sql)

    assert translated.startswith("INSERT INTO raw_collected_items")
    assert translated.endswith("ON CONFLICT DO NOTHING")


def test_returning_id_is_not_added_for_collector_tasks():
    sql = "INSERT INTO collector_tasks (task_id, run_id, source_id) VALUES (%s, %s, %s)"

    translated, returns_id = _add_postgres_returning_id(sql)

    assert translated == sql
    assert returns_id is False
