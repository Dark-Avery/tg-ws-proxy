package main

import (
	"log"
	"testing"
	"time"
)

func TestValidateHandshakeAcceptsMinimalTelegramWSRequest(t *testing.T) {
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

func TestNewRelayServerDefaultsPathAndTimeout(t *testing.T) {
	server := NewRelayServer(Config{}, log.Default())

	if server.cfg.ConnectPath != "/connect" {
		t.Fatalf("expected default connect path, got %q", server.cfg.ConnectPath)
	}
	if server.cfg.UpstreamTimeout != 10*time.Second {
		t.Fatalf("expected default timeout, got %v", server.cfg.UpstreamTimeout)
	}
}
