# Screen recording script (under 3 minutes, no slides)

Have three things open before you start: the terminal in the repo, `EVIDENCE.md`, and http://localhost:8000.

**0:00–0:25 — The ask, and the first thing I checked** *(terminal / EVIDENCE.md)*
"Ritu asked for a model that matches the bot's labels at 90%. Before training anything, I compared the bot's label with the resolution log, which records the team that actually closed each request. The bot is right only 77% of the time. One request in four goes to the wrong team."

**0:25–1:00 — What I tried first, and threw away** *(scroll to the first table in EVIDENCE.md)*
"So I built exactly what was asked first: a model trained on the bot's labels. It matches the bot 96% of the time, so it passes the 90% bar. But it's still only 77% right. It's a perfect copy of a bad router. I threw that away and kept it only as evidence. I retrained on where requests were actually resolved. That model is 85% right, in a back-test where each month is predicted using only earlier months."

**1:00–1:35 — What I changed after the error analysis** *(the clear vs vague table)*
"Then I looked at the errors. On messages that say what's wrong, it's 96% right. Almost all the misses are messages like 'please call me about my purifier'. I tried a second model on channel, warranty, time of day and payment mentions. It was no better than guessing the biggest team, so I threw that away too. These messages need a question, not a model. That's what Meenal said in her email."

**1:35–2:25 — The product** *(browser)*
- Click **Paid, not installed**: "Mentions payment, but it goes to Installs & Demo, not Billing. That's policy §3. The bot sent 73% of 'I paid' messages to Billing; only 18% belonged there."
- Click **Please call me**: "Amber. It doesn't pretend. It gives a best guess, says ask first, and gives the agent the one question to ask."
- Terminal: `curl` the endpoint: "Same thing as JSON for the CRM. No API key, runs on a laptop, Rs 0 per request. Farhan asked for that."
- Terminal: `python -m unittest discover -s tests` (11 tests pass in a second), then open `/metrics`: "Every decision is logged without the customer's words. When a request closes, the CRM posts the real team to `/feedback`, so we see live accuracy, and model versus bot on the same requests, during the shadow trial. Retraining has a gate: a worse model never replaces the live one."
- "I also dropped FastAPI and any language model from the product. The standard-library server is simpler to start, and an LLM would add a per-request bill without fixing the vague cases."

**2:25–2:55 — Money and next step** *(MEMO.md)*
"At the policy's costs, about Rs 700 per misroute, it saves about Rs 4.6 lakh a year in transfers plus the Rs 3.2 lakh licence: Rs 7.8 lakh a year. I expect about 85% on the hidden test. My recommendation is to run it alongside the bot for two weeks, then switch."
