import test from 'node:test'
import assert from 'node:assert/strict'
import { money, yuanToFen, rechargeStatus } from '../src/lib/recharge-format.ts'
import { loginDestination } from '../src/lib/login-redirect.ts'

test('recharge amounts convert using integer fen without floating point rounding', () => {
  for (const [value, expected] of [['0.01', 1], ['10', 1000], ['10.10', 1010], ['10000', 1000000]]) assert.equal(yuanToFen(value), expected)
  for (const value of ['0', '-1', '1.001', '1e2', 'NaN', '10000.01', '01.00', ' 10']) assert.equal(yuanToFen(value), null)
  assert.equal(money(1001), '¥10.01')
})

test('payment confirmation wins over an old expiry and login only returns locally', () => {
  assert.equal(rechargeStatus({ status: 'paid', expired: true }), '已到账')
  assert.equal(rechargeStatus({ status: 'pending', expired: true }), '支付链接已过期')
  assert.equal(loginDestination('/recharge/return?out_trade_no=123'), '/recharge/return?out_trade_no=123')
  assert.equal(loginDestination('/recharge-evil'), '/')
  assert.equal(loginDestination('//example.test/recharge'), '/')
})
