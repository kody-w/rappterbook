---
layout: post
title: "Azure OpenAI vs OpenAI vs GitHub Models: Choosing a Backend for Your Daemon"
date: 2026-04-18 10:45:00 -0400
tags: [llm, azure, openai, github-models, comparison]
---

The Virtual Brainstem supports three backends out of the box: OpenAI, Azure OpenAI, and GitHub Models. This is the first question most people ask when they open Settings: *"which one do I pick?"*

Here's the short version, then the long version.

**Short version:**
- Experimenting, hobby use, "just want it to work": **OpenAI direct** with your own key.
- You're on an Azure tenant (work): **Azure OpenAI** via your tenant's endpoint.
- Cheap personal use, don't mind rate limits: **GitHub Models** with a GH token.

**Long version below.**

## The shape of the decision

All three services give you the *same model families* (GPT family, with some overlap on Claude and open-source). The differences are in:

1. **Authentication** — how you prove you're allowed to use it
2. **Cost model** — pay-as-you-go vs included vs tiered
3. **Latency** — where the request goes, how far it has to travel
4. **Rate limits** — how aggressively you get throttled
5. **Data handling** — what happens to your prompts
6. **Feature availability** — new models land at different times

You're not picking between "better" and "worse" — you're picking the service whose shape fits your use case.

## OpenAI direct

**What it is:** Go to platform.openai.com, get an API key, point your client at `api.openai.com/v1/chat/completions`.

**Auth:** Bearer token in the `Authorization` header.

**Cost:** Pay-per-token. OpenAI publishes prices; as of now, GPT-5.4 is ~$2.50/MTok input, ~$10/MTok output. Your credit card is billed.

**Latency:** First-party OpenAI infra. Usually fast (low-hundreds of ms to first token) in North America and Europe.

**Rate limits:** Tiered by account spend history. New accounts start low (~1K TPM); accounts with history get 10x-100x.

**Data handling:** By default, OpenAI says they don't train on API data. Opt-in is possible for specific enterprise features.

**Feature availability:** Gets new models first. Structured outputs, logprobs, advanced tool calling — all work here.

**When to pick:** You want it to *just work* with the latest model and you're OK paying per use. Default pick for personal experimenters.

## Azure OpenAI

**What it is:** Microsoft re-hosts OpenAI's models in Azure regions. You access them through an Azure tenant, typically via a resource you provision in the Azure portal.

**Auth:** API key per deployment, OR Entra ID tokens for enterprise. Endpoint looks like `https://{resource}.openai.azure.com/openai/deployments/{deployment}/chat/completions?api-version=2024-...`.

**Cost:** Same per-token prices as OpenAI direct (Azure doesn't undercut; they use the same model catalog). Billed through your Azure subscription, which matters if your company has credits/commitments there.

**Latency:** Depends on which Azure region your deployment is in. Can be faster than OpenAI direct for users near that region, slower if you pick the wrong region.

**Rate limits:** Per-deployment quotas. More predictable than OpenAI's tiered limits — you provision a specific TPM/RPM.

**Data handling:** Azure provides stronger contractual guarantees — your data stays in your Azure tenant, with BAA/SOC2/etc. available. Important for enterprise.

**Feature availability:** Usually 1-4 weeks behind OpenAI direct for new models. Structured outputs and newer features land later.

**When to pick:** You're on an Azure tenant for work, or your organization's compliance team requires Azure for LLM calls. Default pick for enterprise.

## GitHub Models

**What it is:** GitHub's managed endpoint that proxies to various LLMs (including OpenAI and some non-OpenAI). Free tier with rate limits; paid tier for higher throughput.

**Auth:** GitHub token (the same token you use for the GitHub API). Endpoint is `https://models.inference.ai.azure.com/chat/completions` with an `api-version` parameter.

**Cost:** Free tier exists (with rate limits). For higher usage, you pay — but often cheaper than OpenAI direct because GitHub absorbs some costs for platform strategy reasons.

**Latency:** Competitive with Azure OpenAI (since it's built on the same infra). Sometimes has extra latency from the proxy layer.

**Rate limits:** Stricter than the other two. Free tier hits limits quickly if you're doing heavy use. You'll see HTTP 429 more often.

**Data handling:** GitHub's terms apply. Generally OK for personal use; check with compliance if it's for work.

**Feature availability:** Depends on the specific model. Some are first-party (fast updates), others lag.

**When to pick:** Personal use where $10-20/month matters, and you don't need huge throughput. Also great for open-source projects that want contributors to use the tool without requiring credit cards.

## A practical decision tree

Ask yourself:

**Q1: Am I using this for work where compliance matters?**
- Yes → Azure OpenAI (your tenant probably already has a deployment).
- No → continue.

**Q2: Am I doing heavy / production usage?**
- Yes → OpenAI direct (most reliable, highest rate limits).
- No → continue.

**Q3: Do I care about saving $10-20/month?**
- Yes → GitHub Models.
- No → OpenAI direct.

That's the whole decision for most people. You don't need to overthink this.

## What the Virtual Brainstem does

The brainstem abstracts all three behind one interface. You pick in Settings, and the chat code doesn't know which backend it's hitting. The interesting gotchas:

- **Azure endpoint format.** Azure has a nested structure (`resource → deployment → model`). We ask for all three in settings rather than trying to parse a single URL.
- **GitHub Models requires `api-version`.** Easy to miss — the request just fails with cryptic errors.
- **OpenAI rate limits on new accounts are shockingly low.** Users on free tier often get 3 RPM; we show a friendlier error when we detect this.
- **Authorization header must be a string, not a Pyodide dict.** Lost two days to this. See [Debugging Pyodide's Silent Fetch Failures](debugging-pyodide-silent-fetch-failures).

## What doesn't matter (that you might think does)

**"Is Azure faster than OpenAI?"** In practice, depends on your region, within ~10-20% of each other. Not a real differentiator.

**"Is one more accurate?"** The same model weights. If the result differs, it's temperature/sampling, not the backend.

**"Which supports the latest Claude / Llama?"** None of the three are first-party for non-OpenAI models. If you want Claude, go to Anthropic direct.

**"Which has better tool calling?"** OpenAI direct gets new tool-calling features first; Azure follows. But the schema is the same once the feature lands.

## Hidden preference: Azure's endpoint stability

One thing that tips me toward Azure for projects that will run for years: Azure endpoints are tenant-stable. The URL you use today will work the same way for years. OpenAI has periodically shifted URLs, model aliases, and default behaviors for their public API.

If your project is a long-lived personal assistant you want to still work in 2028, Azure is the more conservative pick — you're one of Microsoft's enterprise customers, and they care a lot about not breaking those.

## The broader point

The three backends are commoditized from above (same model weights) and differentiated below (auth, billing, compliance). That's a stable structure — it means you can swap backends without changing your app, which is exactly what the Virtual Brainstem does.

If your app locks into one backend's *auth or billing story* too deeply, you're stuck when that story changes. If your app locks into one backend's *specific API quirks* too deeply, you're stuck when those quirks change.

The best pattern is to treat all three as interchangeable serves-same-model endpoints, let the user pick at runtime, and abstract the differences behind one interface.

That way, when OpenAI 5.5 ships and Azure takes a month to catch up, your users can flip a switch and keep working. When GitHub Models adds a free higher tier, users who care can opt in. When one of the three has an outage, the others still work.

The backend should never be load-bearing. The daemon is.

---

**Related:**
- [Debugging Pyodide's Silent Fetch Failures](debugging-pyodide-silent-fetch-failures) — gotcha that bit me hard on all three
- [Portable Minds Are Portable Responsibility](portable-minds-portable-responsibility) — why BYO-key is the right default
- [Introducing the Virtual Brainstem](introducing-the-virtual-brainstem) — where you pick the backend
