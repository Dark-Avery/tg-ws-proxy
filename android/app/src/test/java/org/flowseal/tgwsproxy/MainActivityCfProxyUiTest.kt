package org.flowseal.tgwsproxy

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MainActivityCfProxyUiTest {
    @Test
    fun android_ui_only_exposes_direct_upstream_mode() {
        assertEquals(listOf(UpstreamMode.DIRECT), UpstreamMode.options.map { it.value })
        assertEquals(UpstreamMode.DIRECT, UpstreamMode.normalize("auto"))
        assertEquals(UpstreamMode.DIRECT, UpstreamMode.normalize("relay_ws"))
    }

    @Test
    fun cfproxy_details_are_visible_only_when_cfproxy_enabled() {
        assertTrue(MainActivity.shouldShowCfProxyDetails(true))
        assertFalse(MainActivity.shouldShowCfProxyDetails(false))
    }
}
