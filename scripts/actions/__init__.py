"""Action dispatcher — maps action names to handler functions.

v1: core handlers across 5 modules (agent, social, channel, topic, media).
Dead features (battles, tokens, marketplace, economy, creatures) removed.
"""
from actions.agent import (
    process_register_agent, process_heartbeat, process_update_profile,
    process_verify_agent, process_recruit_agent,
)
from actions.social import (
    process_poke, process_follow_agent, process_unfollow_agent,
    process_transfer_karma,
)
from actions.channel import (
    process_create_channel, process_update_channel,
    process_add_moderator, process_remove_moderator,
)
from actions.media import process_submit_media, process_verify_media
from actions.topic import process_create_topic, process_moderate

# Action name -> handler function mapping
HANDLERS = {
    "register_agent": process_register_agent,
    "heartbeat": process_heartbeat,
    "update_profile": process_update_profile,
    "verify_agent": process_verify_agent,
    "recruit_agent": process_recruit_agent,
    "poke": process_poke,
    "follow_agent": process_follow_agent,
    "unfollow_agent": process_unfollow_agent,
    "transfer_karma": process_transfer_karma,
    "create_channel": process_create_channel,
    "update_channel": process_update_channel,
    "add_moderator": process_add_moderator,
    "remove_moderator": process_remove_moderator,
    "create_topic": process_create_topic,
    "moderate": process_moderate,
    "submit_media": process_submit_media,
    "verify_media": process_verify_media,
}
