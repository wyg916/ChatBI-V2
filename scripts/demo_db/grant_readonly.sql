GRANT USAGE ON SCHEMA {{schema}} TO {{reader_role}};
GRANT SELECT ON ALL TABLES IN SCHEMA {{schema}} TO {{reader_role}};
ALTER DEFAULT PRIVILEGES IN SCHEMA {{schema}} GRANT SELECT ON TABLES TO {{reader_role}};
