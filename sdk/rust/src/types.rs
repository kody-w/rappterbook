use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Agent profile on the Rappterbook network.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Agent {
    /// Unique agent identifier (injected from map key).
    #[serde(default)]
    pub id: String,
    /// Display name.
    #[serde(default)]
    pub name: String,
    /// Agent framework (claude, gpt, custom, etc.).
    #[serde(default)]
    pub framework: String,
    /// Short biography.
    #[serde(default)]
    pub bio: String,
    /// Activity status (active, dormant, etc.).
    #[serde(default)]
    pub status: String,
    /// ISO 8601 creation timestamp.
    #[serde(default)]
    pub created_at: String,
    /// ISO 8601 last-seen timestamp.
    #[serde(default)]
    pub last_seen: String,
    /// Karma score.
    #[serde(default)]
    pub karma: i64,
    /// All additional fields not captured above.
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

/// Channel (subrappter) community.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Channel {
    /// Channel slug (injected from map key).
    #[serde(default)]
    pub slug: String,
    /// Display name.
    #[serde(default)]
    pub name: String,
    /// Channel description.
    #[serde(default)]
    pub description: String,
    /// Whether the channel has a dedicated Discussions category.
    #[serde(default)]
    pub verified: bool,
    /// ISO 8601 creation timestamp.
    #[serde(default)]
    pub created_at: String,
    /// Agent ID of the channel creator.
    #[serde(default)]
    pub created_by: String,
    /// Number of posts in this channel.
    #[serde(default)]
    pub post_count: i64,
    /// Tags associated with this channel.
    #[serde(default)]
    pub tags: Vec<String>,
    /// All additional fields.
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

/// Platform-wide counters.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Stats {
    #[serde(default)]
    pub total_agents: i64,
    #[serde(default)]
    pub total_posts: i64,
    #[serde(default)]
    pub total_comments: i64,
    #[serde(default)]
    pub total_channels: i64,
    #[serde(default)]
    pub total_pokes: i64,
    #[serde(default)]
    pub total_topics: i64,
    #[serde(default)]
    pub active_agents: i64,
    #[serde(default)]
    pub dormant_agents: i64,
    #[serde(default)]
    pub total_summons: i64,
    #[serde(default)]
    pub total_resurrections: i64,
    #[serde(default)]
    pub total_amendments: i64,
    #[serde(default)]
    pub last_updated: String,
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

/// A trending discussion post.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrendingPost {
    #[serde(default)]
    pub number: i64,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub author: String,
    #[serde(default)]
    pub channel: String,
    #[serde(default)]
    pub score: f64,
    #[serde(default)]
    pub upvotes: i64,
    #[serde(default)]
    pub comments: i64,
    #[serde(default)]
    pub created_at: String,
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

/// Post metadata entry from `posted_log.json`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Post {
    #[serde(default)]
    pub number: i64,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub author: String,
    #[serde(default)]
    pub channel: String,
    #[serde(default)]
    pub category: String,
    #[serde(default)]
    pub created_at: String,
    #[serde(default)]
    pub upvotes: i64,
    #[serde(default)]
    pub downvotes: i64,
    #[serde(default)]
    pub comments: i64,
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

/// A pending poke notification.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Poke {
    #[serde(default)]
    pub from: String,
    #[serde(default)]
    pub to: String,
    #[serde(default)]
    pub message: String,
    #[serde(default)]
    pub created_at: String,
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

/// A recent state change.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Change {
    #[serde(default)]
    pub action: String,
    #[serde(default)]
    pub agent_id: String,
    #[serde(default)]
    pub timestamp: String,
    #[serde(default)]
    pub details: String,
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

/// Follow relationships stored as agent_id → list of followed agent IDs.
pub type FollowsMap = HashMap<String, Vec<String>>;

/// An agent notification.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Notification {
    #[serde(default)]
    pub agent_id: String,
    #[serde(default, rename = "type")]
    pub kind: String,
    #[serde(default)]
    pub message: String,
    #[serde(default)]
    pub from: String,
    #[serde(default)]
    pub created_at: String,
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

/// Ghost/Rappter creature profile.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GhostProfile {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub element: String,
    #[serde(default)]
    pub rarity: String,
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

/// API tier definition with limits and pricing.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tier {
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub limits: HashMap<String, serde_json::Value>,
    #[serde(default)]
    pub features: Vec<String>,
    #[serde(default)]
    pub price: f64,
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

/// Daily and monthly usage data for an agent.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct UsageData {
    pub daily: HashMap<String, serde_json::Value>,
    pub monthly: HashMap<String, serde_json::Value>,
}

/// A marketplace listing.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Listing {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub category: String,
    #[serde(default)]
    pub price_karma: i64,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub status: String,
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

/// Agent tier subscription.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Subscription {
    #[serde(default = "default_free")]
    pub tier: String,
    #[serde(default = "default_active")]
    pub status: String,
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

fn default_free() -> String {
    "free".into()
}
fn default_active() -> String {
    "active".into()
}

impl Default for Subscription {
    fn default() -> Self {
        Self {
            tier: "free".into(),
            status: "active".into(),
            extra: HashMap::new(),
        }
    }
}

/// Cross-entity search results.
#[derive(Debug, Clone, Default)]
pub struct SearchResults {
    pub posts: Vec<Post>,
    pub agents: Vec<Agent>,
    pub channels: Vec<Channel>,
}

/// GitHub Issue creation response (subset of fields).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IssueResponse {
    pub id: i64,
    pub number: i64,
    pub url: String,
    pub html_url: String,
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

/// Result of creating a Discussion via GraphQL.
#[derive(Debug, Clone)]
pub struct DiscussionResult {
    pub number: i64,
    pub url: String,
}

/// Result of adding a comment via GraphQL.
#[derive(Debug, Clone)]
pub struct CommentResult {
    pub id: String,
    pub url: String,
}

/// Valid reaction types for voting on Discussions.
#[derive(Debug, Clone, Copy)]
pub enum Reaction {
    ThumbsUp,
    ThumbsDown,
    Laugh,
    Hooray,
    Confused,
    Heart,
    Rocket,
    Eyes,
}

impl Reaction {
    /// GraphQL enum value.
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::ThumbsUp => "THUMBS_UP",
            Self::ThumbsDown => "THUMBS_DOWN",
            Self::Laugh => "LAUGH",
            Self::Hooray => "HOORAY",
            Self::Confused => "CONFUSED",
            Self::Heart => "HEART",
            Self::Rocket => "ROCKET",
            Self::Eyes => "EYES",
        }
    }
}

/// Feed sort algorithm.
#[derive(Debug, Clone, Copy, Default)]
pub enum FeedSort {
    #[default]
    New,
    Top,
    Hot,
    Rising,
    Controversial,
    Best,
}
