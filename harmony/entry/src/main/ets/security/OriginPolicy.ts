// Restrict the shell to a DNS origin on HTTPS/443. No credentials or URL paths.
export function normalizeServiceOrigin(value: string): string {
  const candidate = value.trim().toLowerCase();
  const match = candidate.match(/^https:\/\/([a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+)(?::443)?\/?$/);
  if (match === null) {
    return '';
  }
  const host = match[1];
  if (host.length > 253 || /^[0-9.]+$/.test(host) || host.endsWith('.localhost') ||
    host.endsWith('.local') || host.endsWith('.invalid') || host.endsWith('.test') ||
    host === 'example.com' || host.endsWith('.example.com')) {
    return '';
  }
  const labels = host.split('.');
  for (let i = 0; i < labels.length; i++) {
    if (labels[i].length > 63) {
      return '';
    }
  }
  return `https://${host}`;
}

export function isAllowedNavigation(target: string, origin: string): boolean {
  if (origin === '' || normalizeServiceOrigin(origin) !== origin || /[\\\u0000-\u0020\u007f]/.test(target)) {
    return false;
  }
  return target === origin || target.startsWith(`${origin}/`) ||
    target.startsWith(`${origin}?`) || target.startsWith(`${origin}#`);
}
