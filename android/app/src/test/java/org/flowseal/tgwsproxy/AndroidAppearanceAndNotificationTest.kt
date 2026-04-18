package org.flowseal.tgwsproxy

import java.io.File
import java.nio.file.Files
import java.nio.file.Paths
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
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

    @Test
    fun notification_details_format_uses_fallback_summary_not_dc_count() {
        val details = ProxyForegroundService.formatNotificationDetailsForTest(
            routeLabel = "Direct Telegram WS",
            fallbackSummary = NotificationSummary.FALLBACK_CFPROXY_PRIO,
            upRate = "1.0 KB",
            downRate = "2.0 KB",
            totalUp = "3.0 KB",
            totalDown = "4.0 KB",
        )

        assertTrue(details.contains("Fallback: CfProxy (prio)"))
        assertFalse(details.contains("DC mappings"))
    }

    @Test
    fun notification_details_resource_uses_fallback_placeholder() {
        val resourcePath = listOf(
            Paths.get("app", "src", "main", "res", "values", "strings.xml"),
            Paths.get("src", "main", "res", "values", "strings.xml"),
            Paths.get("..", "app", "src", "main", "res", "values", "strings.xml"),
        ).firstOrNull { Files.exists(it) }
            ?: error("notification string resource not found from cwd=${System.getProperty("user.dir")}")
        val xml = File(resourcePath.toString()).readText()
        val rawValue = Regex(
            """<string name="notification_details">(.*?)</string>""",
            setOf(RegexOption.DOT_MATCHES_ALL),
        ).find(xml)?.groupValues?.get(1)

        assertEquals(
            "Route: %1\$s\\n%2\$s\\nTraffic: ↑ %3\$s/s ↓ %4\$s/s\\nTransferred: ↑ %5\$s ↓ %6\$s",
            rawValue,
        )
    }
}
