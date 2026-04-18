package org.flowseal.tgwsproxy

import org.junit.Assert.assertEquals
import org.junit.Test

class AndroidAppearanceAndNotificationTest {
    @Test
    fun normalize_appearance_defaults_to_auto() {
        assertEquals("auto", ProxyConfig.normalizeAppearance(""))
        assertEquals("auto", ProxyConfig.normalizeAppearance("weird"))
        assertEquals("light", ProxyConfig.normalizeAppearance("light"))
        assertEquals("dark", ProxyConfig.normalizeAppearance("dark"))
    }

    @Test
    fun fallback_summary_prefers_custom_cfproxy_label() {
        val config = NormalizedProxyConfig(
            host = "127.0.0.1",
            port = 1443,
            secret = "0123456789abcdef0123456789abcdef",
            dcIpList = listOf("2:149.154.167.220"),
            upstreamMode = UpstreamMode.AUTO,
            relayUrl = "",
            relayToken = "",
            directWsTimeoutSeconds = 3.5,
            logMaxMb = 5.0,
            bufferKb = 256,
            poolSize = 4,
            cfproxy = true,
            cfproxyPriority = true,
            cfproxyUserDomain = "cdn.example.com",
            checkUpdates = true,
            verbose = false,
            appearance = "dark",
        )

        assertEquals(
            NotificationSummary.FALLBACK_CFPROXY_CUSTOM,
            NotificationSummary.formatFallbackSummary(config),
        )
    }
}
