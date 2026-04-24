from running_coach.storage.schema import _split_sql_statements


def test_split_sql_statements_preserves_dollar_quoted_blocks():
    sql = """
    CREATE TABLE example (id integer);
    DO $$
    BEGIN
        EXECUTE $migrate$
            UPDATE example SET id = 1;
        $migrate$;
    END $$;
    CREATE INDEX idx_example ON example (id);
    """

    statements = _split_sql_statements(sql)

    assert len(statements) == 3
    assert statements[1].startswith("DO $$")
    assert "UPDATE example SET id = 1;" in statements[1]
