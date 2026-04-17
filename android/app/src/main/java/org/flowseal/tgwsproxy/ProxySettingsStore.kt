package org.flowseal.tgwsproxy

import android.content.Context

class ProxySettingsStore(context: Context) {
    private val preferences = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    fun load(): ProxyConfig {
        return ProxyConfig(
            host = preferences.getString(KEY_HOST, ProxyConfig.DEFAULT_HOST).orEmpty(),
            portText = preferences.getInt(KEY_PORT, ProxyConfig.DEFAULT_PORT).toString(),
            secretText = preferences.getString(KEY_SECRET, ProxyConfig.DEFAULT_SECRET).orEmpty(),
            dcIpText = preferences.getString(
                KEY_DC_IP_TEXT,
                ProxyConfig.DEFAULT_DC_IP_LINES.joinToString("\n"),
            ).orEmpty(),
            upstreamMode = preferences.getString(KEY_UPSTREAM_MODE, UpstreamMode.DIRECT).orEmpty(),
            relayUrlText = preferences.getString(KEY_RELAY_URL, "").orEmpty(),
            relayTokenText = preferences.getString(KEY_RELAY_TOKEN, "").orEmpty(),
            directWsTimeoutText = ProxyConfig.formatDecimal(
                preferences.getFloat(
                    KEY_DIRECT_WS_TIMEOUT_SECONDS,
                    ProxyConfig.DEFAULT_DIRECT_WS_TIMEOUT_SECONDS.toFloat(),
                ).toDouble()
            ),
            logMaxMbText = ProxyConfig.formatDecimal(
                preferences.getFloat(
                    KEY_LOG_MAX_MB,
                    ProxyConfig.DEFAULT_LOG_MAX_MB.toFloat(),
                ).toDouble()
            ),
            bufferKbText = preferences.getInt(
                KEY_BUFFER_KB,
                ProxyConfig.DEFAULT_BUFFER_KB,
            ).toString(),
            poolSizeText = preferences.getInt(
                KEY_POOL_SIZE,
                ProxyConfig.DEFAULT_POOL_SIZE,
            ).toString(),
            checkUpdates = preferences.getBoolean(KEY_CHECK_UPDATES, false),
            verbose = preferences.getBoolean(KEY_VERBOSE, false),
        )
    }

    fun save(config: NormalizedProxyConfig) {
        preferences.edit()
            .putString(KEY_HOST, config.host)
            .putInt(KEY_PORT, config.port)
            .putString(KEY_SECRET, config.secret)
            .putString(KEY_DC_IP_TEXT, config.dcIpList.joinToString("\n"))
            .putString(KEY_UPSTREAM_MODE, config.upstreamMode)
            .putString(KEY_RELAY_URL, config.relayUrl)
            .putString(KEY_RELAY_TOKEN, config.relayToken)
            .putFloat(
                KEY_DIRECT_WS_TIMEOUT_SECONDS,
                config.directWsTimeoutSeconds.toFloat(),
            )
            .putFloat(KEY_LOG_MAX_MB, config.logMaxMb.toFloat())
            .putInt(KEY_BUFFER_KB, config.bufferKb)
            .putInt(KEY_POOL_SIZE, config.poolSize)
            .putBoolean(KEY_CHECK_UPDATES, config.checkUpdates)
            .putBoolean(KEY_VERBOSE, config.verbose)
            .apply()
    }

    companion object {
        private const val PREFS_NAME = "proxy_settings"
        private const val KEY_HOST = "host"
        private const val KEY_PORT = "port"
        private const val KEY_SECRET = "secret"
        private const val KEY_DC_IP_TEXT = "dc_ip_text"
        private const val KEY_UPSTREAM_MODE = "upstream_mode"
        private const val KEY_RELAY_URL = "relay_url"
        private const val KEY_RELAY_TOKEN = "relay_token"
        private const val KEY_DIRECT_WS_TIMEOUT_SECONDS = "direct_ws_timeout_seconds"
        private const val KEY_LOG_MAX_MB = "log_max_mb"
        private const val KEY_BUFFER_KB = "buf_kb"
        private const val KEY_POOL_SIZE = "pool_size"
        private const val KEY_CHECK_UPDATES = "check_updates"
        private const val KEY_VERBOSE = "verbose"
    }
}
