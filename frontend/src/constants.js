// Phrased to match the seeded dataset (see backend `python -m app.cli seed`).
export const EXAMPLE_QUERIES = [
  'Which 5 portfolio companies have the highest latest ARR?',
  'Average monthly churn rate by investment stage',
  "Apple's quarterly revenue and net income over the last year",
  'NVDA closing price and 50-day moving average for the last 30 trading days',
]

// Rows rendered in the results table; the full result stays available for export.
export const MAX_TABLE_ROWS = 50
