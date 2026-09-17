from app.connectors import MySQLConnector, PostgreSQLConnector, connector_for


def connector_kwargs():
    return {
        "host": "db.internal",
        "port": 5432,
        "database": "analytics",
        "username": "readonly-user",
        "password": "p@ss:/?#[]!",
        "ssl": False,
        "schema": "public",
    }


def test_postgresql_connector_uses_structured_url_and_hides_password():
    connector = connector_for("postgresql", **connector_kwargs())
    assert isinstance(connector, PostgreSQLConnector)
    assert connector.url.drivername == "postgresql+psycopg"
    assert connector.url.password == "p@ss:/?#[]!"
    assert "p@ss" not in str(connector.url)


def test_mysql_connector_uses_structured_url_and_hides_password():
    kwargs = connector_kwargs() | {"port": 3306, "schema": "analytics"}
    connector = connector_for("mysql", **kwargs)
    assert isinstance(connector, MySQLConnector)
    assert connector.url.drivername == "mysql+pymysql"
    assert connector.url.password == "p@ss:/?#[]!"
    assert "p@ss" not in str(connector.url)
