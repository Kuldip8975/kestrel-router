# Memo: replacing the routing bot

**To:** Ritu Deshpande  **Cc:** Farhan Sheikh, Meenal Joshi, Tanmay Kulkarni  **Date:** 31 October 2026

## The decision

Switch the bot off at renewal and replace it with the new router, which costs nothing to run.

We did not build exactly what you asked for, and here is why. A copy of the bot's labels was easy: it matched them 96% of the time. But when we compared the bot's choices with the team that actually closed each request, **the bot sends about one request in four to the wrong team**. A copy repeats those mistakes. So we trained the router on where requests were actually resolved.

## The number

**85 out of 100 requests reach the right team first time, against 77 today.**

- **84% of requests say what the problem is.** On these the router is right **96%** of the time (the bot: 87%).
- **16% say nothing useful** ("please call me about my purifier"). Meenal is right that nobody can route these; historically they ended up in all seven teams. The router flags them and suggests one question to ask the customer instead of guessing.
- **"I paid" messages:** the bot sent 73% of them to Billing, but only 18% were Billing problems. The router gets 86% right; the bot gets 33%.

## The rupees

At your policy's costs (Rs 305 per transfer, Rs 260 per extra contact), a misrouted request costs about **Rs 700**.

| Per year (about 8,700 requests) | Bot | New router |
|---|---|---|
| Misrouted requests | about 2,000 | about 1,340 |
| Cost of misroutes | Rs 14.0 lakh | Rs 9.4 lakh |
| Licence / running cost | Rs 3.2 lakh | **Rs 0** |
| **Saving** | | **about Rs 7.8 lakh a year** |

**Farhan:** it runs on an existing office server. There is no per-request fee, and the cost does not grow with volume: **Rs 0 a month**.

Three in four of the router's remaining mistakes are the vague requests. If agents ask those customers one question first, misroutes on everything else drop to about 4%.

## What to do next week

1. **Start a two-week trial alongside the bot.** Customers see no change. The router records its choice for every request, and we compare it with where each request closes, to confirm the 85% on live traffic.
2. **Meenal agrees the one clarifying question** for vague requests. A draft is already built into the screen.
3. **Give the bot vendor notice** to match the renewal date, so the switch follows the trial.
4. **Plan headcount on the teams' real workload, not on queue sizes.** The bot inflates queues: Repairs receives about 210 requests a month but closes about 170, and Billing and Filters & Consumables each receive about 40 a month that are not theirs. Requests actually closed per month: Repairs 169, Installs & Demo 106, Returns 103, Product Advice 93, Warranty 92, Billing 88, Filters & Consumables 71. (Older Zoho times were 5½ hours off; we corrected them.)
