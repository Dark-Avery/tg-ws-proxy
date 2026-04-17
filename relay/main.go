package main

import (
	"context"
	"flag"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func main() {
	cfg := Config{}
	flag.StringVar(&cfg.ListenAddr, "listen", ":8080",
		"relay listen address")
	flag.StringVar(&cfg.ConnectPath, "path", "/connect",
		"WebSocket connect path")
	flag.StringVar(&cfg.AuthToken, "auth-token", "",
		"shared auth token required from clients")
	flag.BoolVar(&cfg.AllowEmptyToken, "allow-empty-token", false,
		"allow empty auth token (development only)")
	flag.DurationVar(&cfg.UpstreamTimeout, "upstream-timeout", 10*time.Second,
		"timeout for Telegram upstream connect")
	flag.StringVar(&cfg.TLSCertFile, "tls-cert", "",
		"TLS certificate file for public relay")
	flag.StringVar(&cfg.TLSKeyFile, "tls-key", "",
		"TLS private key file for public relay")
	flag.Parse()

	logger := log.New(os.Stdout, "tg-ws-relay ", log.LstdFlags)

	if cfg.ConnectPath == "" {
		cfg.ConnectPath = "/connect"
	}
	if cfg.UpstreamTimeout <= 0 {
		cfg.UpstreamTimeout = 10 * time.Second
	}

	server := NewRelayServer(cfg, logger)

	httpServer := &http.Server{
		Addr:              cfg.ListenAddr,
		Handler:           server.Routes(),
		ReadHeaderTimeout: 10 * time.Second,
	}

	ctx, stop := signal.NotifyContext(context.Background(),
		os.Interrupt, syscall.SIGTERM)
	defer stop()

	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(),
			5*time.Second)
		defer cancel()
		if err := httpServer.Shutdown(shutdownCtx); err != nil {
			logger.Printf("shutdown error: %v", err)
		}
	}()

	logger.Printf("listening on %s%s", cfg.ListenAddr, cfg.ConnectPath)

	var err error
	if cfg.TLSCertFile != "" || cfg.TLSKeyFile != "" {
		err = httpServer.ListenAndServeTLS(cfg.TLSCertFile, cfg.TLSKeyFile)
	} else {
		err = httpServer.ListenAndServe()
	}

	if err != nil && err != http.ErrServerClosed {
		logger.Fatalf("server failed: %v", err)
	}
}
