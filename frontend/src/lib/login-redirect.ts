/** Only return to local canvas or MCP setup routes; never accept an external login destination. */
export function loginDestination(redirect: unknown): string {
  if (typeof redirect !== 'string' || /[\\\r\n]/.test(redirect)) return '/'
  return /^\/(?:canvas(?:\/[^?#]*)?|mcp(?:\/authorize)?)(?:\?[^#]*)?(?:#.*)?$/.test(redirect) ? redirect : '/'
}
