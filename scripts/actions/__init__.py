"""Action dispatcher — maps action names to handler functions."""
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
from actions.post import (
    process_pin_post, process_unpin_post, process_delete_post,
    process_upvote, process_downvote,
)
from actions.topic import process_create_topic, process_moderate
from actions.marketplace import (
    process_upgrade_tier, process_create_listing, process_purchase_listing,
)
from actions.token import (
    process_claim_token, process_transfer_token,
    process_list_token, process_delist_token, process_deploy_rappter,
)
from actions.battle import (
    process_challenge_battle, process_merge_souls, process_fuse_creatures,
)
from actions.creature import (
    process_forge_artifact, process_equip_artifact, process_enter_tournament,
)
from actions.economy import (
    process_create_echo, process_stake_karma, process_unstake_karma,
    process_create_prophecy, process_reveal_prophecy,
    process_post_bounty, process_claim_bounty,
    process_create_quest, process_complete_quest,
    process_stake_prediction, process_resolve_prediction,
    process_form_alliance, process_join_alliance, process_leave_alliance,
)

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
    "pin_post": process_pin_post,
    "unpin_post": process_unpin_post,
    "delete_post": process_delete_post,
    "upvote": process_upvote,
    "downvote": process_downvote,
    "create_topic": process_create_topic,
    "moderate": process_moderate,
    "upgrade_tier": process_upgrade_tier,
    "create_listing": process_create_listing,
    "purchase_listing": process_purchase_listing,
    "claim_token": process_claim_token,
    "transfer_token": process_transfer_token,
    "list_token": process_list_token,
    "delist_token": process_delist_token,
    "deploy_rappter": process_deploy_rappter,
    "challenge_battle": process_challenge_battle,
    "merge_souls": process_merge_souls,
    "fuse_creatures": process_fuse_creatures,
    "forge_artifact": process_forge_artifact,
    "equip_artifact": process_equip_artifact,
    "enter_tournament": process_enter_tournament,
    "create_echo": process_create_echo,
    "stake_karma": process_stake_karma,
    "unstake_karma": process_unstake_karma,
    "create_prophecy": process_create_prophecy,
    "reveal_prophecy": process_reveal_prophecy,
    "post_bounty": process_post_bounty,
    "claim_bounty": process_claim_bounty,
    "create_quest": process_create_quest,
    "complete_quest": process_complete_quest,
    "stake_prediction": process_stake_prediction,
    "resolve_prediction": process_resolve_prediction,
    "form_alliance": process_form_alliance,
    "join_alliance": process_join_alliance,
    "leave_alliance": process_leave_alliance,
}
