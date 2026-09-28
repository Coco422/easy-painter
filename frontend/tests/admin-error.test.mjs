import { test } from 'node:test'
import assert from 'node:assert/strict'
import { adminErrorMessage } from '../src/lib/admin-error.ts'

test('admin creation validation errors show readable username and password guidance', () => {
  const message = adminErrorMessage({ detail: [
    { loc: ['body', 'username'], type: 'string_pattern_mismatch', msg: "String should match pattern '^[a-zA-Z0-9_]+$'" },
    { loc: ['body', 'password'], type: 'string_too_short', msg: 'String should have at least 6 characters' },
  ] }, '失败')
  assert.match(message, /用户名须为 2–64 位/)
  assert.match(message, /邮箱请填写到邮箱栏/)
  assert.match(message, /密码长度须为 6–128 个字符/)
  assert.ok(!message.includes('[object Object]'))
})

test('string, structured and other field errors retain useful messages', () => {
  assert.equal(adminErrorMessage({ detail: '用户名已存在' }, '失败'), '用户名已存在')
  assert.equal(adminErrorMessage({ detail: { message: '操作受限' } }, '失败'), '操作受限')
  assert.equal(adminErrorMessage({ detail: [{ loc: ['body', 'email'], msg: 'Value error, invalid email' }] }, '失败'), '邮箱：invalid email')
})

test('malformed error bodies safely fall back instead of stringifying objects', () => {
  for (const payload of [null, 'bad', {}, { detail: [] }, { detail: [null, {}, { msg: {} }] }, { detail: { message: {} } }]) {
    assert.equal(adminErrorMessage(payload, '请求未能完成。'), '请求未能完成。')
  }
})
