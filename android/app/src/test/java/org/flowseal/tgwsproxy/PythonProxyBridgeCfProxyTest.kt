package org.flowseal.tgwsproxy

import org.junit.Assert.assertEquals
import org.junit.Test

class PythonProxyBridgeCfProxyTest {
    @Test
    fun parse_cfproxy_test_result_preserves_string_status() {
        val result = PythonProxyBridge.cfProxyTestResultFromMap(
            mapOf(
                "ok" to false,
                "mode" to "auto",
                "status" to "partial",
                "detail" to "1/6 endpoints reachable",
            ),
        )

        assertEquals("partial", result.status)
        assertEquals("auto", result.mode)
        assertEquals("1/6 endpoints reachable", result.detail)
    }
}
