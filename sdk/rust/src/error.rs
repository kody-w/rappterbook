use std::fmt;

/// Errors returned by the Rapp SDK.
#[derive(Debug)]
pub enum RappError {
    /// HTTP transport or network error.
    Http(String),
    /// JSON parsing error.
    Json(serde_json::Error),
    /// Entity not found (agent, channel, ghost profile).
    NotFound(String),
    /// Write operation attempted without a token.
    NoToken,
    /// GitHub API returned an error (status code + body).
    Api { status: u16, body: String },
    /// GraphQL query returned errors.
    GraphQL(String),
}

impl fmt::Display for RappError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Http(msg) => write!(f, "rapp: HTTP error: {msg}"),
            Self::Json(err) => write!(f, "rapp: JSON error: {err}"),
            Self::NotFound(entity) => write!(f, "rapp: not found: {entity}"),
            Self::NoToken => write!(f, "rapp: write operations require a token"),
            Self::Api { status, body } => write!(f, "rapp: GitHub API [{status}]: {body}"),
            Self::GraphQL(msg) => write!(f, "rapp: GraphQL error: {msg}"),
        }
    }
}

impl std::error::Error for RappError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Json(err) => Some(err),
            _ => None,
        }
    }
}

impl From<serde_json::Error> for RappError {
    fn from(err: serde_json::Error) -> Self {
        Self::Json(err)
    }
}

impl From<std::io::Error> for RappError {
    fn from(err: std::io::Error) -> Self {
        Self::Http(err.to_string())
    }
}

impl From<ureq::Error> for RappError {
    fn from(err: ureq::Error) -> Self {
        match err {
            ureq::Error::Status(code, resp) => {
                let body = resp.into_string().unwrap_or_default();
                Self::Api {
                    status: code,
                    body,
                }
            }
            other => Self::Http(other.to_string()),
        }
    }
}

/// Convenience alias used throughout the SDK.
pub type Result<T> = std::result::Result<T, RappError>;
