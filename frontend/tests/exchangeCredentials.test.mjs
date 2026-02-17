import test from 'node:test';
import assert from 'node:assert/strict';
import { buildRotatePayload, canManageCredentials } from '../src/utils/exchangeCredentials.mjs';

test('buildRotatePayload não inclui segredos vazios', () => {
  const payload = buildRotatePayload({
    label: 'Conta A',
    status: 'ACTIVE',
    apiKey: '   ',
    apiSecret: '',
    passphrase: '  '
  });
  assert.deepEqual(payload, { label: 'Conta A', status: 'ACTIVE' });
});

test('buildRotatePayload inclui apenas segredos preenchidos', () => {
  const payload = buildRotatePayload({
    label: 'Conta A',
    status: 'INACTIVE',
    apiKey: ' key123 ',
    apiSecret: ' sec123 ',
    passphrase: ''
  });
  assert.deepEqual(payload, {
    label: 'Conta A',
    status: 'INACTIVE',
    apiKey: 'key123',
    apiSecret: 'sec123'
  });
});

test('canManageCredentials respeita ADMIN/VIEWER', () => {
  assert.equal(canManageCredentials('ADMIN'), true);
  assert.equal(canManageCredentials('VIEWER'), false);
});
