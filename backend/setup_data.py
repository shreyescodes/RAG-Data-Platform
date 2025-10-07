#!/usr/bin/env python3
"""
Script to initialize database and load data
"""
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.db.database import SessionLocal, init_db
from backend.utils.data_loader import DataLoader
from backend.rag.vector_store import FAISSVectorStore
from backend.rag.schema_indexer import SchemaIndexer


def main():
    print("=" * 60)
    print("RAG Platform - Data Setup")
    print("=" * 60)

    # Initialize database
    print("\n[1/5] Initializing database schema...")
    init_db()
    print("✓ Database schema created")

    # Create database session
    db = SessionLocal()

    try:
        # Initialize data loader
        loader = DataLoader(db)

        # Load Excel data if available
        excel_path = "DEMO_DATASET.xlsx"
        if os.path.exists(excel_path):
            print(f"\n[2/5] Loading Excel data from {excel_path}...")
            loader.load_excel_data(excel_path)
            print("✓ Excel data loaded")
        else:
            print(f"\n[2/5] Excel file not found at {excel_path}, skipping...")

        # Synthesize data from Yahoo Finance
        print("\n[3/5] Synthesizing financial data from Yahoo Finance...")
        tickers = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META",
            "TSLA", "NVDA", "JPM", "BAC", "WMT"
        ]
        loader.synthesize_financial_data(tickers, num_years=2)
        print(f"✓ Synthesized data for {len(tickers)} companies")

        # Generate synthetic performance metrics to reach 5000+ rows
        print("\n[4/5] Generating synthetic performance metrics...")
        loader.generate_synthetic_performance_metrics(num_records=5000)
        print("✓ Generated 5000+ performance metrics")

        # Index database schema into vector store
        print("\n[5/5] Indexing database schema into vector store...")
        vector_store = FAISSVectorStore(dimension=1536, index_path="data/faiss_index")
        schema_indexer = SchemaIndexer(vector_store)
        schema_indexer.index_database_schema()
        print("✓ Schema indexed into vector store")

        print("\n" + "=" * 60)
        print("Setup Complete!")
        print("=" * 60)

        # Print statistics
        from backend.db.models import Company, FinancialStatement, PortfolioCompany, PerformanceMetric, MarketData

        print("\nDatabase Statistics:")
        print(f"  Companies: {db.query(Company).count()}")
        print(f"  Financial Statements: {db.query(FinancialStatement).count()}")
        print(f"  Portfolio Companies: {db.query(PortfolioCompany).count()}")
        print(f"  Performance Metrics: {db.query(PerformanceMetric).count()}")
        print(f"  Market Data: {db.query(MarketData).count()}")

        print(f"\nVector Store Statistics:")
        stats = vector_store.get_stats()
        print(f"  Total Documents: {stats['total_documents']}")
        print(f"  Dimension: {stats['dimension']}")

        print("\nYou can now start the API server with:")
        print("  cd backend && uvicorn api.main:app --reload")

    except Exception as e:
        print(f"\n✗ Error during setup: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        sys.exit(1)

    finally:
        db.close()


if __name__ == "__main__":
    main()
