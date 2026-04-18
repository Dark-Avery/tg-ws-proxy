package org.flowseal.tgwsproxy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MainActivityParityPhase3Test {
    @Test
    fun custom_domain_is_enabled_only_when_toggle_is_on() {
        assertTrue(MainActivity.shouldEnableCustomCfProxyDomain(true))
        assertFalse(MainActivity.shouldEnableCustomCfProxyDomain(false))
    }

    @Test
    fun appearance_options_match_supported_modes() {
        assertTrue(MainActivity.appearanceModes().contains("auto"))
        assertTrue(MainActivity.appearanceModes().contains("light"))
        assertTrue(MainActivity.appearanceModes().contains("dark"))
    }

    @Test
    fun android_upstream_mode_is_direct_only() {
        assertEquals(listOf(UpstreamMode.DIRECT), UpstreamMode.options.map { it.value })
        assertEquals(UpstreamMode.DIRECT, UpstreamMode.normalize(UpstreamMode.DIRECT))
        assertEquals(UpstreamMode.DIRECT, UpstreamMode.normalize("auto"))
        assertEquals(UpstreamMode.DIRECT, UpstreamMode.normalize("relay_ws"))
    }

    @Test
    fun generated_secret_matches_mtproto_format() {
        val secret = ProxyConfig.generateSecretForUi()

        assertEquals(32, secret.length)
        assertTrue(secret.all { it in "0123456789abcdef" })
    }
}
