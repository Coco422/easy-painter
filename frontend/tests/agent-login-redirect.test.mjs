import { test } from 'node:test'
import assert from 'node:assert/strict'
import { loginDestination } from '../src/lib/login-redirect.ts'

test('agent setup and consent login returns stay on their exact local routes', () => {
  for (const path of ['/mcp', '/mcp?client=codex', '/mcp/authorize?request=example']) assert.equal(loginDestination(path), path)
  for (const path of ['/mcp-evil', '/mcp/callback?code=evil', '/mcp//evil', '//example.com/mcp', '/mcp\\evil']) assert.equal(loginDestination(path), '/')
})
