package org.flowseal.tgwsproxy

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MainActivityCfProxyUiTest {
    @Test
    fun relay_fields_are_visible_for_auto_and_relay_modes() {
        assertTrue(MainActivity.shouldShowRelayFields(UpstreamMode.AUTO))
        assertTrue(MainActivity.shouldShowRelayFields(UpstreamMode.RELAY))
        assertFalse(MainActivity.shouldShowRelayFields(UpstreamMode.DIRECT))
    }

    @Test
    fun direct_timeout_is_visible_only_for_auto_mode() {
        assertTrue(MainActivity.shouldShowDirectTimeout(UpstreamMode.AUTO))
        assertFalse(MainActivity.shouldShowDirectTimeout(UpstreamMode.RELAY))
        assertFalse(MainActivity.shouldShowDirectTimeout(UpstreamMode.DIRECT))
    }

    @Test
    fun cfproxy_details_are_visible_only_when_cfproxy_enabled() {
        assertTrue(MainActivity.shouldShowCfProxyDetails(true))
        assertFalse(MainActivity.shouldShowCfProxyDetails(false))
    }
}
