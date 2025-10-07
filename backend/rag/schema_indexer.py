from sqlalchemy import inspect
from typing import List, Dict
from .vector_store import FAISSVectorStore
from ..db.database import engine


class SchemaIndexer:
    def __init__(self, vector_store: FAISSVectorStore):
        self.vector_store = vector_store
        self.inspector = inspect(engine)

    def index_database_schema(self):
        """Index all database tables and columns for semantic search"""
        texts = []
        metadata = []

        for table_name in self.inspector.get_table_names():
            columns = self.inspector.get_columns(table_name)

            # Index table description
            table_text = f"Table: {table_name}"
            texts.append(table_text)
            metadata.append({
                "type": "table",
                "table_name": table_name,
                "text": table_text
            })

            # Index each column
            for column in columns:
                col_name = column['name']
                col_type = str(column['type'])

                column_text = f"Table {table_name}, Column {col_name} (type: {col_type})"
                texts.append(column_text)
                metadata.append({
                    "type": "column",
                    "table_name": table_name,
                    "column_name": col_name,
                    "column_type": col_type,
                    "text": column_text
                })

            # Create relationship descriptions
            foreign_keys = self.inspector.get_foreign_keys(table_name)
            for fk in foreign_keys:
                fk_text = f"Table {table_name} has foreign key {fk['constrained_columns']} referencing {fk['referred_table']}.{fk['referred_columns']}"
                texts.append(fk_text)
                metadata.append({
                    "type": "relationship",
                    "table_name": table_name,
                    "foreign_key": fk,
                    "text": fk_text
                })

        # Add documents to vector store
        if texts:
            self.vector_store.add_documents(texts, metadata)
            print(f"Indexed {len(texts)} schema elements")

    def get_relevant_tables(self, query: str, k: int = 10) -> List[str]:
        """Get relevant table names for a query"""
        results = self.vector_store.search(query, k=k)
        tables = set()

        for metadata, score in results:
            if 'table_name' in metadata:
                tables.add(metadata['table_name'])

        return list(tables)

    def get_relevant_columns(self, query: str, k: int = 10) -> Dict[str, List[str]]:
        """Get relevant columns grouped by table"""
        results = self.vector_store.search(query, k=k)
        table_columns = {}

        for metadata, score in results:
            if metadata.get('type') == 'column':
                table = metadata['table_name']
                column = metadata['column_name']

                if table not in table_columns:
                    table_columns[table] = []
                if column not in table_columns[table]:
                    table_columns[table].append(column)

        return table_columns
