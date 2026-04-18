package org.flowseal.tgwsproxy

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
}
