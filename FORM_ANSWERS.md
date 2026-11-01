# Submission form — draft answers

> Fill in the bracketed parts (links, hours) yourself and edit anything that isn't true for you.

**What did you build, and what business outcome does it move?**
A request router that runs locally (a scikit-learn text model) and a web service with a screen for agents. The service is built to be operated: a single-request and a batch endpoint for the CRM, optional API-key auth, rate limiting, a privacy-safe decision log, a feedback endpoint that turns closed requests into live accuracy (including model vs bot on the same requests, for the shadow trial), drift alerts, versioned models, a release gate on retraining, and 11 automated end-to-end tests. It sends each new service request to one of the seven teams, explains why in plain words, and flags vague requests for one clarifying question instead of guessing. It routes **84.6%** of requests to the team that actually resolves them, against **77.1%** for the current bot, and 96% on the 84% of requests that state a problem. At the policy's costs (about Rs 698 per misroute), that cuts misroute cost from about Rs 14.0 lakh to Rs 9.4 lakh a year. Add the Rs 3.2 lakh licence and the saving is **about Rs 7.8 lakh a year**, with a run cost of **Rs 0 a month**.

**What score do you expect predictions.csv to get, on which metric, and why that metric?**
**84.6% accuracy** (likely range 82.5–87%), measured against the team that resolved each request. Accuracy, because every misroute costs about the same in transfers plus an extra contact, so accuracy maps straight to rupees. (Macro-F1 in the back-test: 0.843.) How we estimated it: a rolling monthly back-test over Jan–Jun 2026, training only on earlier months and testing on the next (4,303 requests). We split accuracy into clear requests (96.0%) and vague ones (25.2%) and re-weighted to the test set's mix (83.8% clear). The range is the worst and best month. If the hidden outcomes turn out to be the bot's labels rather than the resolving team, expect about 79%. Team names: predictions use the current names (Installs & Demo, Filters & Consumables) because every test request is from after the 15 Jan 2026 rename, and the resolution log uses only the new names from February 2026. They map one-to-one to Installations and Consumables in teams.csv (policy §5: responsibilities did not change).

**How do you know it works?**
Sample: 4,303 requests in a time-ordered back-test, plus a fixed 2,135-request hold-out (Apr–Jun 2026) for per-team and error analysis. Error rate: 15.4% overall; 4.1% on requests marked "auto route" (83% of traffic). Confidence is calibrated: over 90% confidence (77% of requests) is right 97.6% of the time. The kinds of case it gets wrong: (1) vague messages like "please call me about my purifier", which are 77% of the errors; an extra model on channel, warranty, time and payment mentions did no better than guessing the biggest team, so there is no signal to find. (2) Messages with two problems in them. (3) Historical cases that look inconsistent (for example "arrived damaged" closed by Filters). Every hold-out error is in `evidence/holdout_errors.csv` (IDs and teams; the version with message text is written to the git-ignored `evidence/private/`).

**Did you change, narrow, or push back on the client's ask?**
Yes, at the very start, after the first look at the data. Ritu asked for 90% agreement with the bot's labels. Comparing the bot's label with the resolution log shows the bot is right only 77% of the time. We built the requested model anyway: it matches the bot 96.4% of the time but routes correctly only 77.4% of the time, no better than the bot. So we retargeted to `final_team` (where the request was actually resolved). Two smaller changes: (a) we don't force a confident answer on vague requests; the service says "ask first" and proposes the question, which follows directly from Meenal's email. (b) We kept raw customer data out of the public repo because of ops policy §10, even though the brief asks for a public repo.

**What is wrong with what you are handing us?**
- The vague-request detector is a hand-written keyword list. It has not been tuned against agents' judgement, and it will miss new phrasings.
- No policy rule for "payment is the problem" when the message also names a spare part. One hold-out case ("AMC filter kit, payment deducted") went to Filters instead of Billing.
- Two-problem messages are routed on whichever problem sounds stronger; there is no explicit priority between problems.
- The training labels contain noise (resolving teams that contradict the text). We did not clean it, so the model has learned a little of it.
- The rupee saving assumes the 2025–26 misroute cost (1.44 transfers) holds for the new router's errors. If its misroutes are easier to spot and bounce faster, the saving is slightly understated; if harder, overstated.
- The committed model is pinned to scikit-learn 1.9.1; on another version you may need to run `python train.py` (which needs the data pack).
- `models/router.joblib` contains a word vocabulary learned from customer messages (order and registration numbers masked; only words seen at least twice). It is not raw data, but Kestrel should confirm it is happy for that to be public.
- The `Dockerfile` was written but never built: no Docker daemon was available to us. Treat it as a starting point.
- No TLS in the service itself; it expects to sit behind Kestrel's reverse proxy. One shared API key, not per-user logins.
- Logs are plain JSON Lines files on local disk, with no rotation. `/metrics` re-reads them on each call, which is fine at Kestrel's ~730 requests a month but not at 100x that.
- The rate limiter is in memory per process; it resets on restart and isn't shared across multiple instances.
- Live accuracy depends on the CRM calling `/feedback` when a request closes. That integration is specified in the README, not built.
- The Google Fonts link fails offline, so the screen falls back to system fonts. It still works.

**What did you deliberately leave out, and why?**
- **A language-model API in the product.** The local model already reaches the ceiling the data allows on clear requests (96%). On vague ones, an LLM can't route what the customer hasn't said. It would add exactly the per-request bill Farhan asked us not to create.
- **Heavier models (transformers, gradient boosting on text).** Messages are short and formulaic; the cheap model is accurate, explainable and starts in a second.
- **Hand-correcting historical labels.** It would inflate our own score without telling Kestrel anything true.
- **Extra infrastructure (a database, a web framework, a queue).** Kestrel handles about 730 requests a month; standard-library Python with file logs serves that with zero dependencies to install, and keeps the "clean machine" start trivial. The README says when to upgrade.
- **Per-user logins and a batch upload screen.** One API key and a batch API cover the CRM integration; agent identity belongs in the CRM.

**Anything you built or found that nobody asked for?**
- Legacy Zoho resolution times are in UTC (policy §9): **1,140 requests appear resolved before they were created.** Fixed in `analysis_workload.py`.
- A workload view for Ritu's headcount planning (`evidence/workload_by_team.csv`): the bot's queues overstate Repairs by about 40 requests a month and dump about 39 a month each on Billing and Filters & Consumables that are not theirs.
- A per-case "action" (auto-route / check / ask first) with a ready clarifying question, so the vague 16% becomes a process fix rather than a model problem.
- The policy §3 measurement: the bot sends 73% of "I paid" messages to Billing; only 18% belong there.

**What did you use AI for?**
[Edit to match what you actually did.] Claude (Anthropic, Opus 5.5) in claude.ai, as a coding and analysis agent. It did the data profiling, spotted the label-quality problem, wrote the training, back-test and service code, and drafted the memo and these answers; I reviewed and directed. Cost: [my existing Claude subscription / Rs X]; no API spend inside the product. Where it helped: fast data exploration and building the time-ordered back-test. Where it wasted time: the sandbox couldn't install FastAPI, so we rebuilt the service on Python's standard library (simpler for a clean machine anyway). Thrown away: FastAPI; a linear SVM (same accuracy, no probabilities for the confidence display); a gradient-boosting model on metadata for vague requests (no better than guessing); the model trained on bot labels (kept only as evidence). Screen recording: [Google Drive link]

**Someone picks this up on Monday and you are unreachable. The three things they need to know.**
1. The target is `final_team` (where the request was resolved), **not** `team_label` (the bot's guess). Never switch back to bot labels "to hit 90%": that number is meaningless, because the bot is wrong 23% of the time.
2. About 16% of requests are unroutable from the text. They are flagged `clarify_first` by the keyword list in `router/model.py` (`VAGUE` / `SPECIFIC`). Improving the clarifying-question process is worth more than improving the model.
3. `python train.py` regenerates everything (back-test, evidence, model, predictions.csv) from `./data/`, and refuses to replace the live model if the new one back-tests worse (it goes to `models/candidate/`). After a retrain: run the tests, then `POST /admin/reload`. Watch `/metrics` alerts. Raw data must never be committed (policy §10). Zoho resolution timestamps are UTC; add 5h30m.

**Honest hours spent.** [your number]

**GitHub repo link.** [your public repo URL]
