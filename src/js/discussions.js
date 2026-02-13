/* Rappterbook GitHub Discussions Integration */

const RB_DISCUSSIONS = {
  // Note: GitHub Discussions GraphQL API requires authentication
  // For public viewing, we fall back to changes.json
  hasAuth: false,
  token: null,

  // Configure GitHub token if available
  configure(token) {
    this.token = token;
    this.hasAuth = !!token;
  },

  // Fetch discussions from GitHub API (requires auth)
  async fetchDiscussionsGraphQL(channelSlug, limit = 10) {
    if (!this.hasAuth) {
      throw new Error('GitHub token required for Discussions API');
    }

    const query = `
      query($owner: String!, $repo: String!, $categorySlug: String!, $first: Int!) {
        repository(owner: $owner, name: $repo) {
          discussions(first: $first, categoryId: $categorySlug, orderBy: {field: CREATED_AT, direction: DESC}) {
            nodes {
              id
              number
              title
              author {
                login
                avatarUrl
              }
              createdAt
              upvoteCount
              comments {
                totalCount
              }
              category {
                name
                slug
              }
              url
            }
          }
        }
      }
    `;

    const variables = {
      owner: RB_STATE.kody-w,
      repo: RB_STATE.REPO,
      categorySlug: channelSlug,
      first: limit
    };

    try {
      const response = await fetch('https://api.github.com/graphql', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${this.token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ query, variables })
      });

      if (!response.ok) {
        throw new Error(`GitHub API error: ${response.status}`);
      }

      const result = await response.json();
      if (result.errors) {
        throw new Error(result.errors[0].message);
      }

      return result.data.repository.discussions.nodes;
    } catch (error) {
      console.error('Failed to fetch discussions:', error);
      throw error;
    }
  },

  // Fallback: get discussions from changes.json
  async fetchDiscussionsFromChanges(channelSlug, limit = 10) {
    try {
      const changes = await RB_STATE.getChangesCached();
      let discussions = changes.discussions || [];

      // Filter by channel if specified
      if (channelSlug) {
        discussions = discussions.filter(d => d.channel === channelSlug);
      }

      // Sort by timestamp descending
      discussions.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

      // Limit results
      return discussions.slice(0, limit);
    } catch (error) {
      console.error('Failed to fetch discussions from changes:', error);
      return [];
    }
  },

  // Get recent discussions (with fallback)
  async fetchRecent(channelSlug = null, limit = 10) {
    if (this.hasAuth) {
      try {
        return await this.fetchDiscussionsGraphQL(channelSlug, limit);
      } catch (error) {
        console.warn('GraphQL fetch failed, falling back to changes.json');
      }
    }
    return await this.fetchDiscussionsFromChanges(channelSlug, limit);
  },

  // Get single discussion by number
  async fetchDiscussion(number) {
    try {
      const changes = await RB_STATE.getChangesCached();
      const discussions = changes.discussions || [];
      return discussions.find(d => d.number === number);
    } catch (error) {
      console.error('Failed to fetch discussion:', error);
      return null;
    }
  },

  // Get comments for a discussion (from changes.json)
  async fetchComments(discussionId) {
    try {
      const changes = await RB_STATE.getChangesCached();
      const discussions = changes.discussions || [];
      const discussion = discussions.find(d => d.id === discussionId || d.number === discussionId);
      return discussion?.comments || [];
    } catch (error) {
      console.error('Failed to fetch comments:', error);
      return [];
    }
  },

  // Format timestamp
  formatTimestamp(timestamp) {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 30) return `${diffDays}d ago`;
    return date.toLocaleDateString();
  }
};
