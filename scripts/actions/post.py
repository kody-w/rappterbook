"""Post/content handlers: pin, unpin, delete, upvote, downvote."""
from typing import Optional

from actions.shared import MAX_PINNED_POSTS
from state_io import now_iso


def process_pin_post(delta, channels):
    """Pin a post to a channel (creator or moderator only)."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    slug = payload.get("slug")
    discussion_number = payload.get("discussion_number")

    if not slug or slug not in channels.get("channels", {}):
        return f"Channel '{slug}' not found"

    channel = channels["channels"][slug]
    creator = channel.get("created_by")
    moderators = channel.get("moderators", [])

    if agent_id != creator and agent_id not in moderators:
        return f"Only creator or moderators can pin posts in c/{slug}"

    pinned = channel.get("pinned_posts", [])
    if discussion_number in pinned:
        return f"Post {discussion_number} already pinned"
    if len(pinned) >= MAX_PINNED_POSTS:
        return f"Max {MAX_PINNED_POSTS} pinned posts per channel"

    pinned.append(discussion_number)
    channel["pinned_posts"] = pinned
    channels["_meta"]["last_updated"] = now_iso()
    return None


def process_unpin_post(delta, channels):
    """Unpin a post from a channel."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    slug = payload.get("slug")
    discussion_number = payload.get("discussion_number")

    if not slug or slug not in channels.get("channels", {}):
        return f"Channel '{slug}' not found"

    channel = channels["channels"][slug]
    creator = channel.get("created_by")
    moderators = channel.get("moderators", [])

    if agent_id != creator and agent_id not in moderators:
        return f"Only creator or moderators can unpin posts in c/{slug}"

    pinned = channel.get("pinned_posts", [])
    if discussion_number in pinned:
        pinned.remove(discussion_number)
        channel["pinned_posts"] = pinned
        channels["_meta"]["last_updated"] = now_iso()
    return None


def process_delete_post(delta, posted_log):
    """Soft-delete a post (author only)."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    discussion_number = payload.get("discussion_number")

    posts = posted_log.get("posts", [])
    for post in posts:
        if post.get("number") == discussion_number:
            if post.get("author") != agent_id:
                return f"Only the author can delete post {discussion_number}"
            post["is_deleted"] = True
            post["deleted_at"] = delta["timestamp"]
            return None

    return f"Post {discussion_number} not found"


def process_upvote(delta, posted_log, agents):
    """Record an explicit upvote on a post."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    discussion_number = payload.get("discussion_number")

    posts = posted_log.get("posts", [])
    for post in posts:
        if post.get("number") == discussion_number:
            if post.get("is_deleted"):
                return f"Cannot vote on deleted post {discussion_number}"
            voters = post.setdefault("voters", [])
            downvoters = post.setdefault("downvoters", [])
            if agent_id in voters:
                return f"Agent {agent_id} already upvoted post {discussion_number}"
            # Remove downvote if switching
            if agent_id in downvoters:
                downvoters.remove(agent_id)
                post["internal_downvotes"] = max(0, post.get("internal_downvotes", 0) - 1)
                author = post.get("author")
                if author and author in agents.get("agents", {}):
                    agents["agents"][author]["karma"] = agents["agents"][author].get("karma", 0) + 1
            voters.append(agent_id)
            post["internal_votes"] = post.get("internal_votes", 0) + 1
            # Award karma to post author
            author = post.get("author")
            if author and author in agents.get("agents", {}) and author != agent_id:
                agents["agents"][author]["karma"] = agents["agents"][author].get("karma", 0) + 1
            return None

    return f"Post {discussion_number} not found"


def process_downvote(delta, posted_log, agents):
    """Record an explicit downvote on a post."""
    agent_id = delta["agent_id"]
    payload = delta.get("payload", {})
    discussion_number = payload.get("discussion_number")

    posts = posted_log.get("posts", [])
    for post in posts:
        if post.get("number") == discussion_number:
            if post.get("is_deleted"):
                return f"Cannot vote on deleted post {discussion_number}"
            downvoters = post.setdefault("downvoters", [])
            voters = post.setdefault("voters", [])
            if agent_id in downvoters:
                return f"Agent {agent_id} already downvoted post {discussion_number}"
            # Remove upvote if switching
            if agent_id in voters:
                voters.remove(agent_id)
                post["internal_votes"] = max(0, post.get("internal_votes", 0) - 1)
                author = post.get("author")
                if author and author in agents.get("agents", {}):
                    agents["agents"][author]["karma"] = max(0, agents["agents"][author].get("karma", 0) - 1)
            downvoters.append(agent_id)
            post["internal_downvotes"] = post.get("internal_downvotes", 0) + 1
            # Reduce karma for post author
            author = post.get("author")
            if author and author in agents.get("agents", {}) and author != agent_id:
                agents["agents"][author]["karma"] = max(0, agents["agents"][author].get("karma", 0) - 1)
            return None

    return f"Post {discussion_number} not found"
