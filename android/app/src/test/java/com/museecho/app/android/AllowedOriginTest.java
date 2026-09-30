package com.museecho.app.android;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class AllowedOriginTest {
    @Test
    public void allowsOnlyProductionHttpsOrigin() {
        assertTrue(AllowedOrigin.isAllowed("https://museecho.toolgate.cloud"));
        assertTrue(AllowedOrigin.isAllowed("https://museecho.toolgate.cloud/workbench?tab=map#result"));
        assertTrue(AllowedOrigin.isAllowed("https://museecho.toolgate.cloud:443/api/health"));

        assertFalse(AllowedOrigin.isAllowed("http://museecho.toolgate.cloud"));
        assertFalse(AllowedOrigin.isAllowed("https://evil.example"));
        assertFalse(AllowedOrigin.isAllowed("https://museecho.toolgate.cloud.evil.example"));
        assertFalse(AllowedOrigin.isAllowed("https://user@museecho.toolgate.cloud"));
        assertFalse(AllowedOrigin.isAllowed("https://museecho.toolgate.cloud:444"));
        assertFalse(AllowedOrigin.isAllowed("https://museecho.toolgate.cloud\\@evil.example"));
        assertFalse(AllowedOrigin.isAllowed("https://museecho.toolgate.cloud/ bad"));
    }
}
