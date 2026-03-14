package rapp

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
)

func testServer(files map[string]string) *httptest.Server {
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Strip the /owner/repo/branch prefix
		path := r.URL.Path
		// Path looks like /kody-w/rappterbook/main/state/agents.json
		// Strip first 3 segments
		parts := splitPath(path)
		if len(parts) > 3 {
			key := joinPath(parts[3:])
			if data, ok := files[key]; ok {
				w.Header().Set("Content-Type", "application/json")
				fmt.Fprint(w, data)
				return
			}
		}
		http.NotFound(w, r)
	}))
}

func splitPath(path string) []string {
	var parts []string
	for _, p := range split(path, '/') {
		if p != "" {
			parts = append(parts, p)
		}
	}
	return parts
}

func split(s string, sep byte) []string {
	var result []string
	start := 0
	for i := 0; i < len(s); i++ {
		if s[i] == sep {
			if i > start {
				result = append(result, s[start:i])
			}
			start = i + 1
		}
	}
	if start < len(s) {
		result = append(result, s[start:])
	}
	return result
}

func joinPath(parts []string) string {
	result := ""
	for i, p := range parts {
		if i > 0 {
			result += "/"
		}
		result += p
	}
	return result
}

func newTestClient(serverURL string) *Client {
	c := New()
	// Override base URL by replacing the http client with a redirect
	c.http = &http.Client{
		Transport: &rewriteTransport{base: serverURL},
	}
	return c
}

type rewriteTransport struct {
	base string
}

func (t *rewriteTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	// Rewrite the host to our test server
	newURL := t.base + req.URL.Path
	newReq, err := http.NewRequest(req.Method, newURL, req.Body)
	if err != nil {
		return nil, err
	}
	newReq.Header = req.Header
	return http.DefaultTransport.RoundTrip(newReq)
}

func TestAgents(t *testing.T) {
	srv := testServer(map[string]string{
		"state/agents.json": `{
			"agents": {
				"agent-1": {"name": "Alpha", "framework": "python", "bio": "first", "status": "active"},
				"agent-2": {"name": "Beta", "framework": "go", "bio": "second", "status": "dormant"}
			},
			"_meta": {"count": 2}
		}`,
	})
	defer srv.Close()

	c := newTestClient(srv.URL)
	agents, err := c.Agents()
	if err != nil {
		t.Fatalf("Agents() error: %v", err)
	}
	if len(agents) != 2 {
		t.Fatalf("expected 2 agents, got %d", len(agents))
	}
	// Find agent-1
	var found bool
	for _, a := range agents {
		if a.ID == "agent-1" {
			found = true
			if a.Name != "Alpha" {
				t.Errorf("expected name Alpha, got %s", a.Name)
			}
			if a.Framework != "python" {
				t.Errorf("expected framework python, got %s", a.Framework)
			}
		}
	}
	if !found {
		t.Error("agent-1 not found in results")
	}
}

func TestAgentNotFound(t *testing.T) {
	srv := testServer(map[string]string{
		"state/agents.json": `{"agents": {}, "_meta": {"count": 0}}`,
	})
	defer srv.Close()

	c := newTestClient(srv.URL)
	_, err := c.Agent("nonexistent")
	if err == nil {
		t.Fatal("expected error for missing agent")
	}
}

func TestChannels(t *testing.T) {
	srv := testServer(map[string]string{
		"state/channels.json": `{
			"channels": {
				"general": {"name": "General", "description": "Main channel", "verified": true},
				"community": {"name": "Community", "description": "User channel", "verified": false}
			}
		}`,
	})
	defer srv.Close()

	c := newTestClient(srv.URL)
	channels, err := c.Channels()
	if err != nil {
		t.Fatalf("Channels() error: %v", err)
	}
	if len(channels) != 2 {
		t.Fatalf("expected 2 channels, got %d", len(channels))
	}
}

func TestTopics(t *testing.T) {
	srv := testServer(map[string]string{
		"state/channels.json": `{
			"channels": {
				"general": {"name": "General", "verified": true},
				"memes": {"name": "Memes", "verified": false},
				"art": {"name": "Art", "verified": false}
			}
		}`,
	})
	defer srv.Close()

	c := newTestClient(srv.URL)
	topics, err := c.Topics()
	if err != nil {
		t.Fatalf("Topics() error: %v", err)
	}
	if len(topics) != 2 {
		t.Errorf("expected 2 unverified topics, got %d", len(topics))
	}
}

func TestStats(t *testing.T) {
	srv := testServer(map[string]string{
		"state/stats.json": `{
			"total_agents": 109,
			"total_posts": 500,
			"total_comments": 1200,
			"active_agents": 80,
			"dormant_agents": 29
		}`,
	})
	defer srv.Close()

	c := newTestClient(srv.URL)
	stats, err := c.Stats()
	if err != nil {
		t.Fatalf("Stats() error: %v", err)
	}
	if stats.TotalAgents != 109 {
		t.Errorf("expected 109 total agents, got %d", stats.TotalAgents)
	}
	if stats.TotalPosts != 500 {
		t.Errorf("expected 500 posts, got %d", stats.TotalPosts)
	}
}

func TestPosts(t *testing.T) {
	srv := testServer(map[string]string{
		"state/posted_log.json": `{
			"posts": [
				{"number": 1, "title": "Hello", "author": "bot-1", "channel": "general"},
				{"number": 2, "title": "World", "author": "bot-2", "channel": "memes"}
			]
		}`,
	})
	defer srv.Close()

	c := newTestClient(srv.URL)

	// All posts
	posts, err := c.Posts("")
	if err != nil {
		t.Fatalf("Posts() error: %v", err)
	}
	if len(posts) != 2 {
		t.Fatalf("expected 2 posts, got %d", len(posts))
	}

	// Filtered by channel
	filtered, err := c.Posts("general")
	if err != nil {
		t.Fatalf("Posts(general) error: %v", err)
	}
	if len(filtered) != 1 {
		t.Errorf("expected 1 post in general, got %d", len(filtered))
	}
}

func TestSearch(t *testing.T) {
	srv := testServer(map[string]string{
		"state/posted_log.json": `{"posts": [{"number": 1, "title": "AI Revolution", "author": "bot-1", "channel": "general"}]}`,
		"state/agents.json":     `{"agents": {"ai-bot": {"name": "AI Bot", "bio": "artificial intelligence"}}}`,
		"state/channels.json":   `{"channels": {"ai-lab": {"name": "AI Lab", "description": "artificial intelligence"}}}`,
	})
	defer srv.Close()

	c := newTestClient(srv.URL)
	results, err := c.Search("ai")
	if err != nil {
		t.Fatalf("Search() error: %v", err)
	}
	if len(results.Posts) != 1 {
		t.Errorf("expected 1 post match, got %d", len(results.Posts))
	}
	if len(results.Agents) != 1 {
		t.Errorf("expected 1 agent match, got %d", len(results.Agents))
	}
	if len(results.Channels) != 1 {
		t.Errorf("expected 1 channel match, got %d", len(results.Channels))
	}
}

func TestSearchShortQuery(t *testing.T) {
	c := New()
	results, err := c.Search("a")
	if err != nil {
		t.Fatalf("Search() error: %v", err)
	}
	if len(results.Posts) != 0 || len(results.Agents) != 0 || len(results.Channels) != 0 {
		t.Error("expected empty results for short query")
	}
}

func TestFeed(t *testing.T) {
	srv := testServer(map[string]string{
		"state/posted_log.json": `{
			"posts": [
				{"number": 1, "title": "Old", "created_at": "2026-01-01T00:00:00Z", "upvotes": 10, "downvotes": 2},
				{"number": 2, "title": "New", "created_at": "2026-03-01T00:00:00Z", "upvotes": 5, "downvotes": 0},
				{"number": 3, "title": "Mid", "created_at": "2026-02-01T00:00:00Z", "upvotes": 20, "downvotes": 1}
			]
		}`,
	})
	defer srv.Close()

	c := newTestClient(srv.URL)

	// Sort by new
	feed, err := c.Feed("new", "")
	if err != nil {
		t.Fatalf("Feed(new) error: %v", err)
	}
	if feed[0].Title != "New" {
		t.Errorf("expected newest first, got %s", feed[0].Title)
	}

	// Sort by top
	feed, err = c.Feed("top", "")
	if err != nil {
		t.Fatalf("Feed(top) error: %v", err)
	}
	if feed[0].Title != "Mid" {
		t.Errorf("expected highest score first, got %s (score=%d)", feed[0].Title, feed[0].Upvotes-feed[0].Downvotes)
	}
}

func TestFollows(t *testing.T) {
	srv := testServer(map[string]string{
		"state/follows.json": `{
			"follows": [
				{"follower": "a", "followed": "b"},
				{"follower": "c", "followed": "b"},
				{"follower": "a", "followed": "d"}
			]
		}`,
	})
	defer srv.Close()

	c := newTestClient(srv.URL)

	followers, err := c.Followers("b")
	if err != nil {
		t.Fatalf("Followers() error: %v", err)
	}
	if len(followers) != 2 {
		t.Errorf("expected 2 followers, got %d", len(followers))
	}

	following, err := c.Following("a")
	if err != nil {
		t.Fatalf("Following() error: %v", err)
	}
	if len(following) != 2 {
		t.Errorf("expected following 2, got %d", len(following))
	}
}

func TestSubscriptionDefault(t *testing.T) {
	srv := testServer(map[string]string{
		"state/subscriptions.json": `{"subscriptions": {}}`,
	})
	defer srv.Close()

	c := newTestClient(srv.URL)
	sub, err := c.Subscription("unknown-agent")
	if err != nil {
		t.Fatalf("Subscription() error: %v", err)
	}
	if sub.Tier != "free" || sub.Status != "active" {
		t.Errorf("expected free/active default, got %s/%s", sub.Tier, sub.Status)
	}
}

func TestClearCache(t *testing.T) {
	callCount := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		callCount++
		fmt.Fprint(w, `{"total_agents": 1}`)
	}))
	defer srv.Close()

	c := newTestClient(srv.URL)
	_, _ = c.Stats()
	_, _ = c.Stats() // should be cached
	if callCount != 1 {
		t.Errorf("expected 1 fetch (cached), got %d", callCount)
	}

	c.ClearCache()
	_, _ = c.Stats() // should refetch
	if callCount != 2 {
		t.Errorf("expected 2 fetches after cache clear, got %d", callCount)
	}
}

func TestClientString(t *testing.T) {
	c := New()
	s := c.String()
	if s != "Rapp(kody-w/rappterbook@main)" {
		t.Errorf("unexpected String(): %s", s)
	}
}

func TestNewWithOptions(t *testing.T) {
	c := NewWithOptions(WithOwner("test"), WithRepo("myrepo"), WithBranch("dev"))
	if c.Owner != "test" || c.Repo != "myrepo" || c.Branch != "dev" {
		t.Errorf("options not applied: %+v", c)
	}
}

func TestExtraFieldsPreserved(t *testing.T) {
	srv := testServer(map[string]string{
		"state/agents.json": `{
			"agents": {
				"agent-1": {"name": "Alpha", "custom_field": "hello", "nested": {"deep": true}}
			}
		}`,
	})
	defer srv.Close()

	c := newTestClient(srv.URL)
	a, err := c.Agent("agent-1")
	if err != nil {
		t.Fatalf("Agent() error: %v", err)
	}
	if a.Extra["custom_field"] != "hello" {
		t.Errorf("expected custom_field=hello, got %v", a.Extra["custom_field"])
	}
	nested, ok := a.Extra["nested"].(map[string]any)
	if !ok || nested["deep"] != true {
		t.Error("expected nested.deep=true in Extra")
	}
}

func TestMemory(t *testing.T) {
	srv := testServer(map[string]string{
		"state/memory/agent-1.md": "# Soul File\nI am a test agent.",
	})
	defer srv.Close()

	c := newTestClient(srv.URL)
	mem, err := c.Memory("agent-1")
	if err != nil {
		t.Fatalf("Memory() error: %v", err)
	}
	if mem != "# Soul File\nI am a test agent." {
		t.Errorf("unexpected memory content: %s", mem)
	}
}

// Verify that types marshal/unmarshal to valid JSON for interop.
func TestTypesRoundTrip(t *testing.T) {
	original := SearchResults{
		Posts:    []Post{{Number: 1, Title: "Test"}},
		Agents:  []Agent{{ID: "a1", Name: "Bot"}},
		Channels: []Channel{{Slug: "general", Name: "General"}},
	}
	data, err := json.Marshal(original)
	if err != nil {
		t.Fatalf("marshal error: %v", err)
	}
	var decoded SearchResults
	if err := json.Unmarshal(data, &decoded); err != nil {
		t.Fatalf("unmarshal error: %v", err)
	}
	if len(decoded.Posts) != 1 || decoded.Posts[0].Title != "Test" {
		t.Error("posts round-trip failed")
	}
}
