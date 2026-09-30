package com.museecho.app.android;

import java.net.URI;
import java.net.URISyntaxException;

final class AllowedOrigin {
    static final String SERVICE_URL = "https://museecho.toolgate.cloud";
    private static final String SERVICE_HOST = "museecho.toolgate.cloud";

    private AllowedOrigin() {
    }

    static boolean isAllowed(String value) {
        if (value == null || value.indexOf('\\') >= 0 || containsControlCharacter(value)) {
            return false;
        }
        try {
            URI uri = new URI(value);
            int port = uri.getPort();
            return "https".equalsIgnoreCase(uri.getScheme())
                    && SERVICE_HOST.equalsIgnoreCase(uri.getHost())
                    && uri.getRawUserInfo() == null
                    && (port == -1 || port == 443);
        } catch (URISyntaxException ignored) {
            return false;
        }
    }

    private static boolean containsControlCharacter(String value) {
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            if (character <= 0x20 || character == 0x7f) {
                return true;
            }
        }
        return false;
    }
}
