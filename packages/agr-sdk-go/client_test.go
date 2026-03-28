package agr

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestEvaluateHappyPath(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(EvaluateResponse{
			Decision:  "ALLOW",
			Reason:    "ok",
			LatencyMs: 1.5,
			EvalID:    "eval-1",
		})
	}))
	defer server.Close()

	client := New("agr_sk_test", WithBaseURL(server.URL))
	resp, err := client.Evaluate(context.Background(), EvaluateRequest{
		AgentID:  "agent",
		Action:   "read",
		Resource: "doc",
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if resp.Decision != "ALLOW" {
		t.Fatalf("expected ALLOW, got %s", resp.Decision)
	}
}

func TestEvaluateUnauthorized(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, `{"message":"unauthorized"}`, http.StatusUnauthorized)
	}))
	defer server.Close()

	client := New("agr_sk_test", WithBaseURL(server.URL))
	_, err := client.Evaluate(context.Background(), EvaluateRequest{AgentID: "agent", Action: "read", Resource: "doc"})
	if !IsAuthError(err) {
		t.Fatalf("expected auth error, got %v", err)
	}
}

func TestEvaluateRateLimited(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, `{"message":"slow down","upgrade_url":"https://agr.dev/pricing"}`, http.StatusTooManyRequests)
	}))
	defer server.Close()

	client := New("agr_sk_test", WithBaseURL(server.URL))
	_, err := client.Evaluate(context.Background(), EvaluateRequest{AgentID: "agent", Action: "read", Resource: "doc"})
	if !IsRateLimitError(err) {
		t.Fatalf("expected rate limit error, got %v", err)
	}
}

func TestWaitForApprovalPollsUntilResolved(t *testing.T) {
	calls := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		status := "pending"
		if calls > 1 {
			status = "approved"
		}
		_ = json.NewEncoder(w).Encode(ApprovalResponse{ID: "appr-1", Status: status})
	}))
	defer server.Close()

	client := New("agr_sk_test", WithBaseURL(server.URL))
	resp, err := client.WaitForApproval(context.Background(), "appr-1", WaitOptions{
		PollInterval: 10 * time.Millisecond,
		Timeout:      200 * time.Millisecond,
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if resp.Status != "approved" {
		t.Fatalf("expected approved, got %s", resp.Status)
	}
}

func TestWaitForApprovalTimeout(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(ApprovalResponse{ID: "appr-1", Status: "pending"})
	}))
	defer server.Close()

	client := New("agr_sk_test", WithBaseURL(server.URL))
	_, err := client.WaitForApproval(context.Background(), "appr-1", WaitOptions{
		PollInterval: 10 * time.Millisecond,
		Timeout:      30 * time.Millisecond,
	})
	if err == nil {
		t.Fatal("expected timeout error")
	}
}
