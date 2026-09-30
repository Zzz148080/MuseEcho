import { test } from 'node:test';
import assert from 'node:assert/strict';
import { normalizeServiceOrigin, isAllowedNavigation } from '../entry/src/main/ets/security/OriginPolicy.ts';

test('normalizes an HTTPS DNS origin without accepting other URLs', () => {
  assert.equal(normalizeServiceOrigin(' HTTPS://Music.Team.CN:443/ '), 'https://music.team.cn');
  for (const url of ['', 'http://music.team.cn', 'https://music.team.cn/api',
    'https://user:pass@music.team.cn', 'https://music.team.cn?token=secret',
    'https://music.team.cn#x', 'https://music.team.cn:8443', 'https://127.0.0.1',
    'https://[::1]', 'https://localhost', 'https://app.local', 'https://app.localhost',
    'https://example.com', 'https://app.invalid', 'https://music.team.cn\\@evil.cn',
    'https://-music.team.cn', `https://${'a'.repeat(64)}.cn`]) {
    assert.equal(normalizeServiceOrigin(url), '', url);
  }
});

test('only permits navigation within the exact selected origin', () => {
  const origin = 'https://music.team.cn';
  for (const url of [origin, `${origin}/`, `${origin}/analysis/123`, `${origin}?id=1`, `${origin}#view`]) {
    assert.equal(isAllowedNavigation(url, origin), true, url);
  }
  for (const url of ['https://music.team.cn.evil.cn/', 'https://music.team.cn@evil.cn/',
    'https://evil.cn', 'http://music.team.cn', 'file:///etc/passwd', 'javascript:alert(1)',
    'data:text/html,x', '//evil.cn', `${origin}\\evil.cn`, `${origin}/\nx`]) {
    assert.equal(isAllowedNavigation(url, origin), false, url);
  }
  assert.equal(isAllowedNavigation(origin, ''), false);
  assert.equal(isAllowedNavigation(origin, 'https://example.com'), false);
});
