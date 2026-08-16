export type DatasourceKind = 'postgresql' | 'mysql';

export interface Datasource {
  id: string;
  name: string;
  type: DatasourceKind;
  host: string;
  port: number;
  database: string;
  username: string;
  schema?: string;
  ssl?: boolean;
  status?: 'CONNECTED' | 'ERROR' | 'PENDING';
  table_count?: number;
  column_count?: number;
  last_synced_at?: string;
  last_sync_at?: string;
}

export type DatasourceInput = Omit<Datasource, 'id' | 'status' | 'table_count' | 'column_count' | 'last_synced_at'> & { password: string };

export interface SchemaInfo { name: string; table_count?: number }
export interface TableInfo { id?: string; name: string; schema?: string; schema_name?: string; qualified_name?: string; comment?: string; column_count?: number }
export interface ColumnInfo {
  name: string; type?: string; data_type?: string; nullable?: boolean; is_nullable?: boolean; primary_key?: boolean; is_primary_key?: boolean; foreign_key?: boolean; is_foreign_key?: boolean;
  default?: string; comment?: string; sample_values?: unknown[];
}

export type SemanticStatus = 'DRAFT' | 'PUBLISHED' | 'DEPRECATED';
export interface SemanticResource { [key: string]: unknown }
export interface SemanticEntity extends SemanticResource { id?: string; name: string; source_table: string; primary_key: string; time_dimension?: string }
export interface Metric extends SemanticResource { id?: string; name: string; label: string; description?: string; expression: string; aggregation: string; filters?: string[] }
export interface Dimension extends SemanticResource { id?: string; name: string; label: string; source_column: string; type: string }
export interface Relationship extends SemanticResource { id?: string; left_entity: string; right_entity: string; join_type: string; join_keys: Array<{ left: string; right: string }>; cardinality: string }
export interface BusinessTerm extends SemanticResource { id?: string; term: string; synonyms: string[]; definition: string; mapped_object: string }

export interface SemanticModel {
  id: string; name: string; description?: string; datasource_id: string; status: SemanticStatus; version?: number | string;
  entities?: SemanticEntity[]; metrics?: Metric[]; dimensions?: Dimension[]; relationships?: Relationship[];
  business_terms?: BusinessTerm[]; updated_at?: string;
}

export interface SemanticModelInput { name: string; description?: string; datasource_id: string }
