package main

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/gorilla/websocket"
)

const (
	modeTelegramWS = "telegram_ws"
)

type Config struct {
	ListenAddr      string
	ConnectPath     string
	AuthToken       string
	AllowEmptyToken bool
	UpstreamTimeout time.Duration
	TLSCertFile     string
	TLSKeyFile      string
}

type HandshakeRequest struct {
	Version   int      `json:"version"`
	AuthToken string   `json:"auth_token"`
	Mode      string   `json:"mode"`
	DC        int      `json:"dc"`
	Media     bool     `json:"media"`
	TargetIP  string   `json:"target_ip"`
	Domains   []string `json:"domains"`
}

type HandshakeResponse struct {
	OK             bool   `json:"ok"`
	Version        int    `json:"version"`
	Mode           string `json:"mode,omitempty"`
	UpstreamDomain string `json:"upstream_domain,omitempty"`
	ErrorCode      string `json:"error_code,omitempty"`
	ErrorMessage   string `json:"error_message,omitempty"`
}

type RelayError struct {
	Code    string
	Message string
	Err     error
}

func (e *RelayError) Error() string {
	if e == nil {
		return ""
	}
	if e.Err == nil {
		return fmt.Sprintf("%s: %s", e.Code, e.Message)
	}
	return fmt.Sprintf("%s: %s: %v", e.Code, e.Message, e.Err)
}

type RelayServer struct {
	cfg      Config
	logger   *log.Logger
	upgrader websocket.Upgrader
}

func NewRelayServer(cfg Config, logger *log.Logger) *RelayServer {
	if cfg.ConnectPath == "" {
		cfg.ConnectPath = "/connect"
	}
	if cfg.UpstreamTimeout <= 0 {
		cfg.UpstreamTimeout = 10 * time.Second
	}
	return &RelayServer{
		cfg:    cfg,
		logger: logger,
		upgrader: websocket.Upgrader{
			CheckOrigin: func(r *http.Request) bool {
				return true
			},
			EnableCompression: false,
			Subprotocols:      []string{"binary"},
		},
	}
}

func (s *RelayServer) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc(s.cfg.ConnectPath, s.handleConnect)
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})
	return mux
}

func (s *RelayServer) handleConnect(w http.ResponseWriter, r *http.Request) {
	clientConn, err := s.upgrader.Upgrade(w, r, nil)
	if err != nil {
		return
	}
	defer clientConn.Close()

	req, relayErr := s.readHandshake(clientConn)
	if relayErr != nil {
		_ = writeJSONMessage(clientConn, websocket.TextMessage,
			HandshakeResponse{
				OK:           false,
				Version:      1,
				ErrorCode:    relayErr.Code,
				ErrorMessage: relayErr.Message,
			})
		s.logger.Printf("handshake failed: %s", relayErr)
		return
	}

	upstreamConn, upstreamDomain, relayErr := dialTelegramUpstream(
		r.Context(), *req, s.cfg.UpstreamTimeout)
	if relayErr != nil {
		_ = writeJSONMessage(clientConn, websocket.TextMessage,
			HandshakeResponse{
				OK:           false,
				Version:      req.Version,
				ErrorCode:    relayErr.Code,
				ErrorMessage: relayErr.Message,
			})
		s.logger.Printf("upstream connect failed: %s", relayErr)
		return
	}
	defer upstreamConn.Close()

	if err := writeJSONMessage(clientConn, websocket.TextMessage,
		HandshakeResponse{
			OK:             true,
			Version:        req.Version,
			Mode:           req.Mode,
			UpstreamDomain: upstreamDomain,
		}); err != nil {
		s.logger.Printf("failed to send success response: %v", err)
		return
	}

	s.logger.Printf("relay session established: dc=%d media=%t domain=%s target=%s",
		req.DC, req.Media, upstreamDomain, req.TargetIP)

	bridgeBinaryFrames(clientConn, upstreamConn)
}

func (s *RelayServer) readHandshake(conn *websocket.Conn) (*HandshakeRequest, *RelayError) {
	msgType, payload, err := conn.ReadMessage()
	if err != nil {
		return nil, &RelayError{
			Code:    "bad_request",
			Message: "failed to read handshake frame",
			Err:     err,
		}
	}
	if msgType != websocket.TextMessage {
		return nil, &RelayError{
			Code:    "bad_request",
			Message: "first frame must be a JSON text handshake",
		}
	}

	var req HandshakeRequest
	if err := json.Unmarshal(payload, &req); err != nil {
		return nil, &RelayError{
			Code:    "bad_request",
			Message: "invalid handshake JSON",
			Err:     err,
		}
	}
	if relayErr := validateHandshake(req, s.cfg); relayErr != nil {
		return nil, relayErr
	}
	return &req, nil
}

func validateHandshake(req HandshakeRequest, cfg Config) *RelayError {
	if req.Version != 1 {
		return &RelayError{
			Code:    "unsupported_version",
			Message: "only protocol version 1 is supported",
		}
	}
	if !cfg.AllowEmptyToken && cfg.AuthToken == "" {
		return &RelayError{
			Code:    "internal_error",
			Message: "relay auth token is not configured",
		}
	}
	if !cfg.AllowEmptyToken && req.AuthToken != cfg.AuthToken {
		return &RelayError{
			Code:    "auth_failed",
			Message: "auth token is invalid",
		}
	}
	if req.Mode != modeTelegramWS {
		return &RelayError{
			Code:    "unsupported_mode",
			Message: "only telegram_ws mode is supported",
		}
	}
	if req.DC < 1 || req.DC > 5 {
		return &RelayError{
			Code:    "bad_request",
			Message: "dc must be in range 1..5",
		}
	}
	if ip := net.ParseIP(req.TargetIP); ip == nil {
		return &RelayError{
			Code:    "invalid_target_ip",
			Message: "target_ip must be a valid IP address",
		}
	}
	if len(req.Domains) == 0 {
		return &RelayError{
			Code:    "invalid_domain_list",
			Message: "domains must not be empty",
		}
	}
	for _, domain := range req.Domains {
		if !isValidUpstreamDomain(domain) {
			return &RelayError{
				Code:    "invalid_domain_list",
				Message: "domains must contain valid hostnames only",
			}
		}
	}
	return nil
}

func isValidUpstreamDomain(domain string) bool {
	if strings.TrimSpace(domain) == "" {
		return false
	}
	if strings.ContainsAny(domain, "/:") {
		return false
	}
	return strings.Contains(domain, ".")
}

func dialTelegramUpstream(ctx context.Context, req HandshakeRequest,
	timeout time.Duration) (*websocket.Conn, string, *RelayError) {
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	var lastErr *RelayError
	for _, domain := range req.Domains {
		conn, relayErr := dialSingleTelegramUpstream(ctx, req.TargetIP, domain)
		if relayErr == nil {
			return conn, domain, nil
		}
		lastErr = relayErr
	}

	if lastErr == nil {
		lastErr = &RelayError{
			Code:    "upstream_unreachable",
			Message: "no upstream domains were attempted",
		}
	}
	return nil, "", lastErr
}

func dialSingleTelegramUpstream(ctx context.Context, targetIP, domain string) (*websocket.Conn, *RelayError) {
	dialer := websocket.Dialer{
		NetDialContext: func(ctx context.Context, network, _ string) (net.Conn, error) {
			var d net.Dialer
			return d.DialContext(ctx, network, net.JoinHostPort(targetIP, "443"))
		},
		Proxy:             http.ProxyFromEnvironment,
		HandshakeTimeout:  10 * time.Second,
		EnableCompression: false,
		Subprotocols:      []string{"binary"},
		TLSClientConfig: &tls.Config{
			ServerName:         domain,
			InsecureSkipVerify: true,
		},
	}

	headers := http.Header{}
	headers.Set("Origin", "https://web.telegram.org")
	headers.Set("User-Agent",
		"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "+
			"(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

	u := url.URL{
		Scheme: "wss",
		Host:   domain,
		Path:   "/apiws",
	}

	conn, resp, err := dialer.DialContext(ctx, u.String(), headers)
	if err == nil {
		return conn, nil
	}

	if resp != nil {
		return nil, &RelayError{
			Code:    "upstream_handshake_error",
			Message: fmt.Sprintf("telegram upstream returned HTTP %d", resp.StatusCode),
			Err:     err,
		}
	}

	switch {
	case errors.Is(err, context.DeadlineExceeded):
		return nil, &RelayError{
			Code:    "upstream_timeout",
			Message: "timed out while connecting to Telegram WS",
			Err:     err,
		}
	case isTimeoutError(err):
		return nil, &RelayError{
			Code:    "upstream_timeout",
			Message: "timed out while connecting to Telegram WS",
			Err:     err,
		}
	case strings.Contains(strings.ToLower(err.Error()), "tls"),
		strings.Contains(strings.ToLower(err.Error()), "ssl"),
		strings.Contains(strings.ToLower(err.Error()), "x509"):
		return nil, &RelayError{
			Code:    "upstream_ssl_error",
			Message: "TLS handshake with Telegram WS failed",
			Err:     err,
		}
	default:
		return nil, &RelayError{
			Code:    "upstream_unreachable",
			Message: "failed to connect to Telegram WS",
			Err:     err,
		}
	}
}

func isTimeoutError(err error) bool {
	var netErr net.Error
	return errors.As(err, &netErr) && netErr.Timeout()
}

func writeJSONMessage(conn *websocket.Conn, msgType int, v interface{}) error {
	payload, err := json.Marshal(v)
	if err != nil {
		return err
	}
	return conn.WriteMessage(msgType, payload)
}

func bridgeBinaryFrames(clientConn, upstreamConn *websocket.Conn) {
	errCh := make(chan error, 2)

	go proxyBinaryFrames(clientConn, upstreamConn, "client_to_upstream", errCh)
	go proxyBinaryFrames(upstreamConn, clientConn, "upstream_to_client", errCh)

	<-errCh
	_ = clientConn.WriteControl(websocket.CloseMessage,
		websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""),
		time.Now().Add(time.Second))
	_ = upstreamConn.WriteControl(websocket.CloseMessage,
		websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""),
		time.Now().Add(time.Second))
}

func proxyBinaryFrames(src, dst *websocket.Conn, _ string, errCh chan<- error) {
	for {
		msgType, payload, err := src.ReadMessage()
		if err != nil {
			errCh <- err
			return
		}
		if msgType != websocket.BinaryMessage {
			errCh <- fmt.Errorf("unexpected message type %d", msgType)
			return
		}
		if err := dst.WriteMessage(websocket.BinaryMessage, payload); err != nil {
			errCh <- err
			return
		}
	}
}
