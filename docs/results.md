# Measured accuracy

[← Back to the README](../README.md)

How the pipeline scores against ground truth, and the defects the evaluation found.

[`backend/eval/`](../backend/eval) runs a fixed question set through the real
pipeline and scores it against hand-written ground-truth SQL. A case passes
only if every value returned by the ground-truth query appears in the
pipeline's result rows.

| Run | Execution accuracy | Behaviour checks | Median latency |
|-----|-------------------:|-----------------:|---------------:|
| 2026-11-19, `openai/gpt-oss-120b` (Groq), real SEC and Yahoo data | **49/50** | **6/6** | 2.1 s per SQL answer |
| 2026-11-06, `openai/gpt-oss-120b` (Groq), previous dataset | 12/12 | 5/5 | 7.2 s per full answer |
| 2026-11-06, `qwen2.5:1.5b` (local Ollama, CPU only), previous dataset | 9/12 | 5/5 | 58.3 s per full answer |

**The current run** ([report](evaluation.md)) asks 50 questions about the real
data: company lists, quarterly and annual statements, prices and moving
averages, returns between dates, and 13F holdings, including joins across
them. It scores the generated SQL with `python -m eval.run --sql-only`, which
skips the written answer and so uses about a third of the tokens; Groq's free
tier allows about 200,000 tokens a day. The six behaviour checks run the full
pipeline: refusing an unanswerable question and a question about how much data
is stored, answering from live data, surviving a prompt injection, redacting
PII and serving a repeat from the cache.

- **The miss:** asked which position Berkshire Hathaway grew most by shares,
  the model matched the two quarters on issuer name and ticker. Alphabet has
  two share classes, and a missing ticker on one of them broke the match, so a
  different stock came out on top. The question set keeps this case as a
  known failure.
- **Provider errors are retried, not scored.** In the first pass Groq
  returned errors for 14 questions in a row while the quota ran low. Those
  cases were run again with `--resume`, which only reruns provider failures,
  and all passed. A pipeline failure is never rerun.
- The two earlier runs used the previous dataset (12 questions, partly
  generated data) and cannot be compared directly. The local run proved the
  self-hosted path on a laptop without a GPU; a 1.5B model is far weaker at
  SQL than a 120B one.

A flagged claim is one the rows do not show, which is not always a false one,
so read each flag with its reason. `VERIFICATION_MODE=heuristic` keeps the
rule-based checks and drops the judge's extra LLM call.

Building this evaluation surfaced three defects, all now fixed:

1. **The default model had been retired.** Groq no longer serves
   `llama-3.3-70b-versatile` (HTTP 404). The default is now
   `openai/gpt-oss-120b`, chosen from Groq's live model list.
2. **The first full run scored 14/15.** The prompt told the model to match
   company names with `ILIKE`, so it treated the ticker `NVDA` as a name and
   returned no rows. The prompt now distinguishes tickers from names, and a
   regression test pins the rule.
3. **"What is NVDA's market cap?" was refused.** The data isn't in the
   database, and enrichment only ran after a successful SQL step. The
   orchestrator now falls back to live data for such questions, and the
   evaluation set gained a case for it.

Running it against the upgraded pipeline surfaced three more, also fixed:

4. **One rejected reply switched the fact check off.** Groq answers HTTP 400
   `json_validate_failed` when a JSON-mode reply is malformed, which the
   client treated as an outage. It is now retried with feedback like any
   invalid reply, the judge has room for a reasoning model's hidden
   reasoning, and a reply cut off at `max_tokens` is logged.
5. **The fact check flagged correct answers.** In the first upgraded Groq run
   it flagged 26 of 76 claims, most of them true: bounds ("all above
   $180M"), gaps ("$7.6M ahead"), sums, dates written "June 30, 2026" or
   with typographic hyphens, ranks ("the top three") and claims about the
   SQL's own filters. The checker now handles each of these, the judge sees
   the SQL, and the labelled set gained cases for them. The latest run flags
   9 of 70.
6. **Answers called the rows they analysed "the sample".** The analysis
   prompt now says the user sees every row and asks for what the rows cover
   ("over the most recent 25 trading days").

Building the real-data evaluation surfaced two more:

7. **The fact check flagged correct company names and ratios.** "Coca-Cola"
   did not match the SEC's "COCA COLA CO", "two-thirds" was read as a count of
   two, and "five times larger" passed whenever the question contained a 5.
   Names now match however a filing abbreviates them, ratios in words go to
   the judge, and multiples are computed between the companies named.
8. **Long results were summarised from their first 25 rows.** The analysis now
   sees an overview of every column and patterns computed from every row,
   and claims about movements over time are checked against them.

Still open, seen while recording the demo: an answer said NVDA's close "ranged
from $227.21 to $178.67" over 30 days, but the highest close was $239.24. Both
numbers are real cells, so the rule-based checks passed it; they do not yet
test that a stated range uses the column's lowest and highest values.
