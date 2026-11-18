# Measured accuracy

[← Back to the README](../README.md)

How the pipeline scores against ground truth, and the defects the evaluation found.

[`backend/eval/`](../backend/eval) runs a fixed question set through the real
pipeline and scores it against hand-written ground-truth SQL. A case passes
only if every value returned by the ground-truth query appears in the
pipeline's result rows.

| Run | Execution accuracy | Behaviour checks | Claims flagged by the fact check | Median latency |
|-----|-------------------:|-----------------:|---------------------------------:|---------------:|
| 2026-10-28, `openai/gpt-oss-120b` (Groq), before the upgrade | **12/12** | **4/4** (refusal, live-data fallback, injection, PII) | – | 2.6 s |
| 2026-11-06, `openai/gpt-oss-120b` (Groq) | **12/12** | **5/5** (adds the cache check) | 9 of 70 | 7.2 s |
| 2026-11-06, `qwen2.5:1.5b` (local Ollama, CPU only) | 9/12 | **5/5** | 19 of 64 | 58.3 s |

The upgraded pipeline makes a third LLM call per answer: the fact check's
judge, for the claims the rule-based checks cannot settle. It accounts for
most of the added latency (a median of 3.8 s per judge call on Groq in the
latest run). `VERIFICATION_MODE=heuristic` keeps the rule-based checks and
drops the extra call. A flagged claim is one the rows do not show, which is
not always a false one. Flags seen while testing included real errors ("a gap
of about $9M" between two companies $5.2M apart) and commentary the rows
cannot confirm ("the amount is expressed in billions"), so read each flag
with its reason.

The full reports, including every generated SQL statement and answer, are in
[docs/evaluation.md](evaluation.md) and
[docs/evaluation-local-llm.md](evaluation-local-llm.md). These runs used
the previous dataset, which still included a generated private-equity
portfolio; the cases now target the real SEC 13F holdings, so re-run with
`make eval` after seeding to refresh them. The local run proves the self-hosted path end to end on a laptop
with no GPU. A 1.5B model is far weaker at SQL than a 120B one. Its 3
misses: a misspelt column the repair attempt could not fix, `name = 'Apple'`
where the prompt asks for `ILIKE`, and sorting by date instead of by closing
price. The fact check cannot catch that last one: the answer faithfully
reports a row the wrong query returned. In that run every answered case cited
the tables its ground-truth query reads (11/11). Use a
7B model or larger on a GPU (see [docs/PRODUCTION_UPGRADES.md](PRODUCTION_UPGRADES.md#which-model))
for real use.

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
