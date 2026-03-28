package agr

import "fmt"

type AGRError struct {
	StatusCode int
	Message    string
	RequestID  string
}

func (e *AGRError) Error() string {
	if e == nil {
		return ""
	}
	if e.RequestID != "" {
		return fmt.Sprintf("agr api error (%d): %s [request_id=%s]", e.StatusCode, e.Message, e.RequestID)
	}
	return fmt.Sprintf("agr api error (%d): %s", e.StatusCode, e.Message)
}

type AGRAuthError struct {
	AGRError
}

type AGRRateLimitError struct {
	AGRError
	UpgradeURL string
}

func IsAuthError(err error) bool {
	_, ok := err.(*AGRAuthError)
	return ok
}

func IsRateLimitError(err error) bool {
	_, ok := err.(*AGRRateLimitError)
	return ok
}
