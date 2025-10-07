import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from ..db.models import Company, FinancialStatement, PortfolioCompany, PerformanceMetric, MarketData
from ..db.database import SessionLocal
import random


class DataLoader:
    def __init__(self, db: Session):
        self.db = db

    def load_excel_data(self, file_path: str):
        """Load data from Excel file"""
        print(f"Loading Excel data from {file_path}")

        try:
            # Read all sheets from Excel
            excel_file = pd.ExcelFile(file_path)
            print(f"Found sheets: {excel_file.sheet_names}")

            for sheet_name in excel_file.sheet_names:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
                print(f"Processing sheet '{sheet_name}' with {len(df)} rows")

                # Process based on sheet name/content
                if "portfolio" in sheet_name.lower() or "company" in sheet_name.lower():
                    self._load_portfolio_data(df)
                elif "financial" in sheet_name.lower() or "statement" in sheet_name.lower():
                    self._load_financial_data(df)
                elif "metric" in sheet_name.lower() or "performance" in sheet_name.lower():
                    self._load_performance_data(df)

            self.db.commit()
            print("Excel data loaded successfully")

        except Exception as e:
            print(f"Error loading Excel data: {e}")
            self.db.rollback()
            raise

    def _load_portfolio_data(self, df: pd.DataFrame):
        """Load portfolio company data"""
        for _, row in df.iterrows():
            # Create or get company
            company_name = row.get('Company Name') or row.get('Company') or row.get('Name')
            if pd.isna(company_name):
                continue

            company = self.db.query(Company).filter(Company.name == company_name).first()

            if not company:
                company = Company(
                    name=str(company_name),
                    ticker=row.get('Ticker') if not pd.isna(row.get('Ticker')) else None,
                    sector=row.get('Sector') if not pd.isna(row.get('Sector')) else None,
                    industry=row.get('Industry') if not pd.isna(row.get('Industry')) else None,
                    description=row.get('Description') if not pd.isna(row.get('Description')) else None
                )
                self.db.add(company)
                self.db.flush()

            # Create portfolio entry
            investment_date = row.get('Investment Date')
            if not pd.isna(investment_date):
                portfolio = PortfolioCompany(
                    company_id=company.id,
                    investment_date=investment_date,
                    investment_amount=row.get('Investment Amount') if not pd.isna(row.get('Investment Amount')) else None,
                    current_valuation=row.get('Current Valuation') if not pd.isna(row.get('Current Valuation')) else None,
                    ownership_percentage=row.get('Ownership %') if not pd.isna(row.get('Ownership %')) else None,
                    investment_stage=row.get('Stage') if not pd.isna(row.get('Stage')) else None,
                    status=row.get('Status', 'Active')
                )
                self.db.add(portfolio)

    def _load_financial_data(self, df: pd.DataFrame):
        """Load financial statement data"""
        for _, row in df.iterrows():
            company_name = row.get('Company Name') or row.get('Company')
            if pd.isna(company_name):
                continue

            company = self.db.query(Company).filter(Company.name == company_name).first()
            if not company:
                continue

            statement = FinancialStatement(
                company_id=company.id,
                statement_date=row.get('Date') if not pd.isna(row.get('Date')) else datetime.now(),
                period_type=row.get('Period') if not pd.isna(row.get('Period')) else 'Annual',
                fiscal_year=row.get('Year') if not pd.isna(row.get('Year')) else datetime.now().year,
                revenue=row.get('Revenue') if not pd.isna(row.get('Revenue')) else None,
                gross_profit=row.get('Gross Profit') if not pd.isna(row.get('Gross Profit')) else None,
                operating_income=row.get('Operating Income') if not pd.isna(row.get('Operating Income')) else None,
                net_income=row.get('Net Income') if not pd.isna(row.get('Net Income')) else None,
                total_assets=row.get('Total Assets') if not pd.isna(row.get('Total Assets')) else None,
                total_liabilities=row.get('Total Liabilities') if not pd.isna(row.get('Total Liabilities')) else None,
                shareholders_equity=row.get('Equity') if not pd.isna(row.get('Equity')) else None
            )
            self.db.add(statement)

    def _load_performance_data(self, df: pd.DataFrame):
        """Load performance metrics data"""
        for _, row in df.iterrows():
            company_name = row.get('Company Name') or row.get('Company')
            if pd.isna(company_name):
                continue

            company = self.db.query(Company).filter(Company.name == company_name).first()
            if not company:
                continue

            portfolio = self.db.query(PortfolioCompany).filter(
                PortfolioCompany.company_id == company.id
            ).first()

            if not portfolio:
                continue

            metric = PerformanceMetric(
                portfolio_company_id=portfolio.id,
                metric_date=row.get('Date') if not pd.isna(row.get('Date')) else datetime.now(),
                arr=row.get('ARR') if not pd.isna(row.get('ARR')) else None,
                mrr=row.get('MRR') if not pd.isna(row.get('MRR')) else None,
                customer_count=row.get('Customers') if not pd.isna(row.get('Customers')) else None,
                churn_rate=row.get('Churn Rate') if not pd.isna(row.get('Churn Rate')) else None
            )
            self.db.add(metric)

    def synthesize_financial_data(self, tickers: list, num_years: int = 3):
        """Synthesize financial data from Yahoo Finance for given tickers"""
        print(f"Synthesizing financial data for {len(tickers)} tickers")

        for ticker_symbol in tickers:
            try:
                ticker = yf.Ticker(ticker_symbol)
                info = ticker.info

                # Create company
                company = self.db.query(Company).filter(Company.ticker == ticker_symbol).first()

                if not company:
                    company = Company(
                        name=info.get('longName', ticker_symbol),
                        ticker=ticker_symbol,
                        sector=info.get('sector'),
                        industry=info.get('industry'),
                        description=info.get('longBusinessSummary', '')[:500] if info.get('longBusinessSummary') else None
                    )
                    self.db.add(company)
                    self.db.flush()

                # Get historical market data
                end_date = datetime.now()
                start_date = end_date - timedelta(days=365 * num_years)

                hist = ticker.history(start=start_date, end=end_date)

                for date, row in hist.iterrows():
                    market_data = MarketData(
                        ticker=ticker_symbol,
                        date=date.date(),
                        open_price=row['Open'],
                        high_price=row['High'],
                        low_price=row['Low'],
                        close_price=row['Close'],
                        volume=int(row['Volume']),
                        adj_close=row['Close']
                    )
                    self.db.add(market_data)

                print(f"Added {len(hist)} market data points for {ticker_symbol}")

                # Get quarterly financials
                quarterly_financials = ticker.quarterly_financials
                quarterly_balance = ticker.quarterly_balance_sheet
                quarterly_cashflow = ticker.quarterly_cashflow

                if not quarterly_financials.empty:
                    for date in quarterly_financials.columns[:12]:  # Last 3 years of quarters
                        try:
                            statement = FinancialStatement(
                                company_id=company.id,
                                statement_date=date.date() if hasattr(date, 'date') else date,
                                period_type='Quarterly',
                                fiscal_year=date.year if hasattr(date, 'year') else datetime.now().year,
                                revenue=self._safe_get(quarterly_financials, 'Total Revenue', date),
                                cost_of_revenue=self._safe_get(quarterly_financials, 'Cost Of Revenue', date),
                                gross_profit=self._safe_get(quarterly_financials, 'Gross Profit', date),
                                operating_income=self._safe_get(quarterly_financials, 'Operating Income', date),
                                ebitda=self._safe_get(quarterly_financials, 'EBITDA', date),
                                net_income=self._safe_get(quarterly_financials, 'Net Income', date),
                                total_assets=self._safe_get(quarterly_balance, 'Total Assets', date) if not quarterly_balance.empty else None,
                                total_liabilities=self._safe_get(quarterly_balance, 'Total Liabilities Net Minority Interest', date) if not quarterly_balance.empty else None,
                                shareholders_equity=self._safe_get(quarterly_balance, 'Stockholders Equity', date) if not quarterly_balance.empty else None,
                                operating_cash_flow=self._safe_get(quarterly_cashflow, 'Operating Cash Flow', date) if not quarterly_cashflow.empty else None,
                                free_cash_flow=self._safe_get(quarterly_cashflow, 'Free Cash Flow', date) if not quarterly_cashflow.empty else None
                            )
                            self.db.add(statement)
                        except Exception as e:
                            print(f"Error processing quarter {date}: {e}")
                            continue

                self.db.commit()
                print(f"Successfully synthesized data for {ticker_symbol}")

            except Exception as e:
                print(f"Error synthesizing data for {ticker_symbol}: {e}")
                self.db.rollback()
                continue

    def _safe_get(self, df, key, date):
        """Safely get value from DataFrame"""
        try:
            if key in df.index and date in df.columns:
                value = df.loc[key, date]
                if pd.notna(value):
                    return float(value)
        except:
            pass
        return None

    def generate_synthetic_performance_metrics(self, num_records: int = 5000):
        """Generate synthetic performance metrics to meet row requirements"""
        print(f"Generating {num_records} synthetic performance metrics")

        portfolio_companies = self.db.query(PortfolioCompany).all()

        if not portfolio_companies:
            print("No portfolio companies found, skipping synthetic metrics")
            return

        base_date = datetime(2020, 1, 1)

        for i in range(num_records):
            portfolio_company = random.choice(portfolio_companies)

            metric_date = base_date + timedelta(days=random.randint(0, 1460))  # 4 years

            metric = PerformanceMetric(
                portfolio_company_id=portfolio_company.id,
                metric_date=metric_date,
                arr=random.uniform(100000, 10000000),
                mrr=random.uniform(10000, 1000000),
                customer_count=random.randint(10, 10000),
                churn_rate=random.uniform(0.01, 0.15),
                cac=random.uniform(100, 5000),
                ltv=random.uniform(1000, 50000),
                burn_rate=random.uniform(10000, 500000),
                runway_months=random.uniform(6, 36),
                revenue_multiple=random.uniform(2, 20),
                ebitda_multiple=random.uniform(5, 30)
            )
            self.db.add(metric)

            if i % 1000 == 0:
                self.db.commit()
                print(f"Generated {i} metrics...")

        self.db.commit()
        print(f"Successfully generated {num_records} synthetic metrics")
