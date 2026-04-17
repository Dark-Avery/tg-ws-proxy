package main

import (
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/gorilla/websocket"
)

func TestValidateHandshakeAcceptsTelegramKwsDomains(t *testing.T) {
	cfg := Config{
		AuthToken:       "secret",
		UpstreamTimeout: 10 * time.Second,
	}

	req := HandshakeRequest{
		Version:   1,
		AuthToken: "secret",
		Mode:      modeTelegramWS,
		DC:        2,
		Media:     false,
		TargetIP:  "149.154.167.220",
		Domains: []string{
			"kws2.web.telegram.org",
			"kws2-1.web.telegram.org",
		},
	}

	if err := validateHandshake(req, cfg); err != nil {
		t.Fatalf("expected handshake to be valid, got %v", err)
	}
}

func TestValidateHandshakeRejectsNonTelegramDomains(t *testing.T) {
	cfg := Config{AuthToken: "secret"}
	req := HandshakeRequest{
		Version:   1,
		AuthToken: "secret",
		Mode:      modeTelegramWS,
		DC:        2,
		TargetIP:  "149.154.167.220",
		Domains: []string{
			"example.com",
			"kws2.web.telegram.org.evil.com",
		},
	}

	err := validateHandshake(req, cfg)
	if err == nil || err.Code != "invalid_domain_list" {
		t.Fatalf("expected invalid_domain_list, got %#v", err)
	}
}

func TestValidateHandshakeRejectsBadToken(t *testing.T) {
	cfg := Config{AuthToken: "secret"}
	req := HandshakeRequest{
		Version:   1,
		AuthToken: "wrong",
		Mode:      modeTelegramWS,
		DC:        2,
		TargetIP:  "149.154.167.220",
		Domains:   []string{"kws2.web.telegram.org"},
	}

	err := validateHandshake(req, cfg)
	if err == nil || err.Code != "auth_failed" {
		t.Fatalf("expected auth_failed, got %#v", err)
	}
}

func TestValidateHandshakeRequiresExactEmptyTokenWhenAllowEmptyEnabled(t *testing.T) {
	cfg := Config{
		AllowEmptyToken: true,
	}
	req := HandshakeRequest{
		Version:   1,
		AuthToken: "secret",
		Mode:      modeTelegramWS,
		DC:        2,
		TargetIP:  "149.154.167.220",
		Domains:   []string{"kws2.web.telegram.org"},
	}

	err := validateHandshake(req, cfg)
	if err == nil || err.Code != "auth_failed" {
		t.Fatalf("expected auth_failed, got %#v", err)
	}
}

func TestValidateHandshakeAcceptsOnlyEmptyTokenWhenRelayTokenEmptyAndAllowEmptyEnabled(t *testing.T) {
	cfg := Config{
		AllowEmptyToken: true,
	}
	emptyReq := HandshakeRequest{
		Version:  1,
		Mode:     modeTelegramWS,
		DC:       2,
		TargetIP: "149.154.167.220",
		Domains:  []string{"kws2.web.telegram.org"},
	}

	if err := validateHandshake(emptyReq, cfg); err != nil {
		t.Fatalf("expected empty token to be accepted, got %v", err)
	}
}

func TestValidateHandshakeRejectsUnsupportedMode(t *testing.T) {
	cfg := Config{AuthToken: "secret"}
	req := HandshakeRequest{
		Version:   1,
		AuthToken: "secret",
		Mode:      "relay_tcp",
		DC:        2,
		TargetIP:  "149.154.167.220",
		Domains:   []string{"kws2.web.telegram.org"},
	}

	err := validateHandshake(req, cfg)
	if err == nil || err.Code != "unsupported_mode" {
		t.Fatalf("expected unsupported_mode, got %#v", err)
	}
}

func TestValidateHandshakeRejectsInvalidTargetIP(t *testing.T) {
	cfg := Config{AuthToken: "secret"}
	req := HandshakeRequest{
		Version:   1,
		AuthToken: "secret",
		Mode:      modeTelegramWS,
		DC:        2,
		TargetIP:  "not-an-ip",
		Domains:   []string{"kws2.web.telegram.org"},
	}

	err := validateHandshake(req, cfg)
	if err == nil || err.Code != "invalid_target_ip" {
		t.Fatalf("expected invalid_target_ip, got %#v", err)
	}
}

func TestValidateHandshakeRejectsInvalidDomainList(t *testing.T) {
	cfg := Config{AuthToken: "secret"}
	req := HandshakeRequest{
		Version:   1,
		AuthToken: "secret",
		Mode:      modeTelegramWS,
		DC:        2,
		TargetIP:  "149.154.167.220",
		Domains:   []string{"kws2.web.telegram.org/apiws"},
	}

	err := validateHandshake(req, cfg)
	if err == nil || err.Code != "invalid_domain_list" {
		t.Fatalf("expected invalid_domain_list, got %#v", err)
	}
}

func TestHealthzRespondsOK(t *testing.T) {
	server := NewRelayServer(Config{}, log.New(io.Discard, "", 0))
	httptestServer := httptest.NewServer(server.Routes())
	t.Cleanup(httptestServer.Close)

	resp, err := http.Get(httptestServer.URL + "/healthz")
	if err != nil {
		t.Fatalf("healthz request failed: %v", err)
	}
	t.Cleanup(func() { _ = resp.Body.Close() })

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("failed to read healthz body: %v", err)
	}

	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200 OK, got %d", resp.StatusCode)
	}
	if got := strings.TrimSpace(string(body)); got != "ok" {
		t.Fatalf("expected body ok, got %q", got)
	}
}

func TestConnectRejectsNonTextFirstFrame(t *testing.T) {
	server := NewRelayServer(Config{AuthToken: "secret"}, log.New(io.Discard, "", 0))
	httptestServer := httptest.NewServer(server.Routes())
	t.Cleanup(httptestServer.Close)

	wsURL := "ws" + strings.TrimPrefix(httptestServer.URL, "http") + "/connect"
	conn, _, err := websocket.DefaultDialer.Dial(wsURL, nil)
	if err != nil {
		t.Fatalf("websocket dial failed: %v", err)
	}
	t.Cleanup(func() { _ = conn.Close() })

	if err := conn.WriteMessage(websocket.BinaryMessage, []byte{0x01, 0x02}); err != nil {
		t.Fatalf("failed to send binary first frame: %v", err)
	}

	msgType, payload, err := conn.ReadMessage()
	if err != nil {
		t.Fatalf("failed to read handshake error: %v", err)
	}
	if msgType != websocket.TextMessage {
		t.Fatalf("expected text error frame, got %d", msgType)
	}

	var resp HandshakeResponse
	if err := json.Unmarshal(payload, &resp); err != nil {
		t.Fatalf("invalid handshake response JSON: %v", err)
	}
	if resp.ErrorCode != "bad_request" {
		t.Fatalf("expected bad_request, got %#v", resp)
	}
}

func TestTelegramUpstreamDialerUsesVerifiedTLS(t *testing.T) {
	dialer := newTelegramUpstreamDialer("149.154.167.220", "kws2.web.telegram.org")

	if dialer.TLSClientConfig == nil {
		t.Fatalf("expected TLSClientConfig to be set")
	}
	if dialer.TLSClientConfig.InsecureSkipVerify {
		t.Fatalf("expected certificate verification to remain enabled")
	}
	if got := dialer.TLSClientConfig.ServerName; got != "kws2.web.telegram.org" {
		t.Fatalf("expected ServerName to be set, got %q", got)
	}
}

func TestClassifyTelegramUpstreamDialErrorMarksTLSErrorAsSslFailure(t *testing.T) {
	relayErr := classifyTelegramUpstreamDialError(io.EOF)
	if relayErr == nil || relayErr.Code != "upstream_unreachable" {
		t.Fatalf("expected non-TLS errors to be classified as unreachable, got %#v", relayErr)
	}

	relayErr = classifyTelegramUpstreamDialError(
		errors.New("x509: certificate signed by unknown authority"),
	)
	if relayErr == nil || relayErr.Code != "upstream_ssl_error" {
		t.Fatalf("expected x509-related errors to map to upstream_ssl_error, got %#v", relayErr)
	}
}

func TestNewRelayServerDefaultsPathAndTimeout(t *testing.T) {
	server := NewRelayServer(Config{}, log.Default())

	if server.cfg.ConnectPath != "/connect" {
		t.Fatalf("expected default connect path, got %q", server.cfg.ConnectPath)
	}
	if server.cfg.UpstreamTimeout != 10*time.Second {
		t.Fatalf("expected default timeout, got %v", server.cfg.UpstreamTimeout)
	}
}
