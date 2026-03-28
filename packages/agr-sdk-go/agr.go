package agr

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"
)

const (
	defaultBaseURL = "https://api.agr.dev"
	defaultTimeout = 10 * time.Second
	sdkVersion     = "0.1.0"
)

type Client struct {
	apiKey  string
	baseURL string
	timeout time.Duration
	http    *http.Client
}

type Option func(*Client)

func WithBaseURL(url string) Option {
	return func(c *Client) {
		c.baseURL = strings.TrimRight(url, "/")
	}
}

func WithTimeout(d time.Duration) Option {
	return func(c *Client) {
		c.timeout = d
		c.http.Timeout = d
	}
}

func New(apiKey string, opts ...Option) *Client {
	client := &Client{
		apiKey:  apiKey,
		baseURL: defaultBaseURL,
		timeout: defaultTimeout,
		http:    &http.Client{Timeout: defaultTimeout},
	}
	for _, opt := range opts {
		opt(client)
	}
	return client
}

func (c *Client) Evaluate(ctx context.Context, req EvaluateRequest) (*EvaluateResponse, error) {
	var resp EvaluateResponse
	if err := c.do(ctx, http.MethodPost, "/v1/evaluate", req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

func (c *Client) Simulate(ctx context.Context, req SimulateRequest) (*EvaluateResponse, error) {
	var resp EvaluateResponse
	if err := c.do(ctx, http.MethodPost, "/v1/policies/simulate", req, &resp); err != nil {
		return nil, err
	}
	return &resp, nil
}

func (c *Client) RegisterAgent(ctx context.Context, req RegisterAgentRequest) error {
	return c.do(ctx, http.MethodPost, "/v1/agents/register", req, nil)
}

func (c *Client) WaitForApproval(ctx context.Context, approvalID string, opts WaitOptions) (*ApprovalResponse, error) {
	opts = opts.normalized()
	timeoutCtx, cancel := context.WithTimeout(ctx, opts.Timeout)
	defer cancel()

	ticker := time.NewTicker(opts.PollInterval)
	defer ticker.Stop()

	for {
		var resp ApprovalResponse
		if err := c.do(timeoutCtx, http.MethodGet, "/v1/approvals/"+approvalID, nil, &resp); err != nil {
			if errors.Is(err, context.DeadlineExceeded) {
				return nil, err
			}
			return nil, err
		}
		if resp.Status != "pending" {
			return &resp, nil
		}

		select {
		case <-timeoutCtx.Done():
			return nil, timeoutCtx.Err()
		case <-ticker.C:
		}
	}
}

func (c *Client) do(ctx context.Context, method, path string, body any, out any) error {
	var reader io.Reader
	if body != nil {
		payload, err := json.Marshal(body)
		if err != nil {
			return err
		}
		reader = bytes.NewReader(payload)
	}

	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, reader)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+c.apiKey)
	req.Header.Set("AGR-Client-Version", "go-sdk/"+sdkVersion)
	req.Header.Set("Accept-Version", "application/vnd.agr.v1+json")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}

	resp, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		return parseError(resp)
	}
	if out == nil {
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(out)
}

func parseError(resp *http.Response) error {
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)

	var payload map[string]any
	_ = json.Unmarshal(body, &payload)
	message, _ := payload["message"].(string)
	requestID, _ := payload["request_id"].(string)

	base := AGRError{
		StatusCode: resp.StatusCode,
		Message:    message,
		RequestID:  requestID,
	}
	if base.Message == "" {
		base.Message = string(body)
	}

	switch resp.StatusCode {
	case http.StatusUnauthorized:
		return &AGRAuthError{AGRError: base}
	case http.StatusTooManyRequests:
		upgradeURL, _ := payload["upgrade_url"].(string)
		return &AGRRateLimitError{AGRError: base, UpgradeURL: upgradeURL}
	default:
		return &base
	}
}
