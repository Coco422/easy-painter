/** Only return to known local account routes; never accept an external login destination. */
export function loginDestination(redirect: unknown): string {
  if (typeof redirect !== 'string' || /[\\\r\n]/.test(redirect)) return '/'
  return /^\/(?:canvas(?:\/[^?#]*)?|mcp(?:\/authorize)?|recharge(?:\/return)?)(?:\?[^#]*)?(?:#.*)?$/.test(redirect) ? redirect : '/'
}
