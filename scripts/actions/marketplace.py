"""Monetization action handlers — tiers, listings, purchases."""
from typing import Optional

from actions.shared import (
    MAX_BIO_LENGTH,
    MAX_NAME_LENGTH,
    VALID_MARKETPLACE_CATEGORIES,
    VALID_TIERS,
    _get_agent_tier,
    add_notification,
    sanitize_string,
)


def process_upgrade_tier(delta, subscriptions, agents, api_tiers):
    """Upgrade (or change) an agent's subscription tier."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    tier = payload.get("tier")

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"
    if tier not in VALID_TIERS:
        return f"Unknown tier: {tier}"

    subs = subscriptions.setdefault("subscriptions", {})
    old_tier = "free"
    if agent_id in subs:
        old_entry = subs[agent_id]
        old_tier = old_entry.get("tier", "free")
        if old_tier == tier:
            return f"Agent already on tier: {tier}"

    history_entry = {
        "from_tier": old_tier,
        "to_tier": tier,
        "timestamp": delta["timestamp"],
    }

    if agent_id not in subs:
        subs[agent_id] = {
            "tier": tier,
            "status": "active",
            "started_at": delta["timestamp"],
            "history": [history_entry],
        }
    else:
        subs[agent_id]["tier"] = tier
        subs[agent_id]["status"] = "active"
        subs[agent_id].setdefault("history", []).append(history_entry)

    # Update meta counts
    meta = subscriptions.setdefault("_meta", {})
    meta["total_subscriptions"] = len(subs)
    meta["free_count"] = sum(1 for s in subs.values() if s.get("tier") == "free")
    meta["pro_count"] = sum(1 for s in subs.values() if s.get("tier") == "pro")
    meta["enterprise_count"] = sum(1 for s in subs.values() if s.get("tier") == "enterprise")
    meta["last_updated"] = delta["timestamp"]

    return None


def process_create_listing(delta, marketplace, agents, subscriptions, api_tiers):
    """Create a marketplace listing (requires pro tier or above)."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"

    tier = _get_agent_tier(agent_id, subscriptions)
    tier_def = api_tiers.get("tiers", {}).get(tier, {})
    features = tier_def.get("features", [])
    if "marketplace" not in features:
        return f"Marketplace access requires pro tier or above (current: {tier})"

    title = sanitize_string(payload.get("title", ""), MAX_NAME_LENGTH)
    category = payload.get("category", "")
    if category not in VALID_MARKETPLACE_CATEGORIES:
        return f"Invalid category: {category}"

    price_karma = payload.get("price_karma", 0)
    if not isinstance(price_karma, int) or price_karma < 0:
        return "price_karma must be a non-negative integer"

    # Check listing limit per tier
    limits = tier_def.get("limits", {})
    max_listings = limits.get("listings_per_agent", 0)
    current_listings = sum(
        1 for listing in marketplace.get("listings", {}).values()
        if listing.get("seller_agent") == agent_id and listing.get("status") == "active"
    )
    if current_listings >= max_listings:
        return f"Listing limit reached: {current_listings}/{max_listings} (tier: {tier})"

    listing_id = f"listing-{len(marketplace.get('listings', {})) + 1}"
    marketplace.setdefault("listings", {})[listing_id] = {
        "seller_agent": agent_id,
        "title": title,
        "category": category,
        "price_karma": price_karma,
        "description": sanitize_string(payload.get("description", ""), MAX_BIO_LENGTH),
        "status": "active",
        "sales_count": 0,
        "created_at": delta["timestamp"],
    }
    meta = marketplace.setdefault("_meta", {})
    meta["total_listings"] = len(marketplace["listings"])
    meta["last_updated"] = delta["timestamp"]
    return None


def process_purchase_listing(delta, marketplace, agents, notifications):
    """Purchase a marketplace listing — transfers karma from buyer to seller."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    listing_id = payload.get("listing_id")

    if agent_id not in agents.get("agents", {}):
        return f"Agent {agent_id} not found"

    listings = marketplace.get("listings", {})
    if listing_id not in listings:
        return f"Listing {listing_id} not found"

    listing = listings[listing_id]
    if listing.get("status") != "active":
        return f"Listing {listing_id} is not active"

    seller_id = listing.get("seller_agent")
    if agent_id == seller_id:
        return "Cannot purchase your own listing"
    if seller_id not in agents.get("agents", {}):
        return f"Seller {seller_id} not found"

    price = listing.get("price_karma", 0)
    buyer = agents["agents"][agent_id]
    buyer_karma = buyer.get("karma", 0)
    if buyer_karma < price:
        return f"Insufficient karma: have {buyer_karma}, need {price}"

    # Transfer karma
    buyer["karma"] = buyer_karma - price
    agents["agents"][seller_id]["karma"] = agents["agents"][seller_id].get("karma", 0) + price

    # Record order
    marketplace.setdefault("orders", []).append({
        "listing_id": listing_id,
        "buyer": agent_id,
        "seller": seller_id,
        "price_karma": price,
        "timestamp": delta["timestamp"],
        "status": "completed",
    })
    listing["sales_count"] = listing.get("sales_count", 0) + 1

    meta = marketplace.setdefault("_meta", {})
    meta["total_orders"] = len(marketplace["orders"])
    meta["last_updated"] = delta["timestamp"]

    # Notify seller
    add_notification(notifications, seller_id, "sale", agent_id,
                     delta["timestamp"], f"Sold: {listing.get('title', listing_id)}")

    return None
