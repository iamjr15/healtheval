import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { onRequest } from '../../functions/api/chat.js';
import { SYSTEM_PROMPT } from '../../functions/_shared/health_prompt.js';

const env = { SARVAM_API_KEY: 'test-sarvam', GEMINI_API_KEY: 'test-google' };
const request = body => new Request('http://localhost/api/chat', { method: 'POST', body: JSON.stringify(body) });
const triage = { triage_label: 'RED', referral_action: 'refer_emergency', red_flags_detected: ['सीने में दर्द'], triage_reason: 'Emergency signs' };

test('rejects methods, malformed requests, unsupported models and blank prompts', async () => {
  assert.equal((await onRequest({request: new Request('http://localhost'), env})).status, 405);
  for (const body of [{model:'sarvam-m',message:'hello'}, {model:'sarvam-105b',message:'   '}, {model:'sarvam-105b',message:'a'.repeat(4001)}]) {
    assert.equal((await onRequest({request:request(body),env})).status,400);
  }
});

test('current Sarvam IDs use explicit non-reasoning mode and shared health prompt', async t => {
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    const body=JSON.parse(options.body);
    assert.equal(body.reasoning_effort,null);
    assert.equal(body.max_tokens,2048);
    assert.equal(body.messages[0].content,SYSTEM_PROMPT);
    assert.match(body.model,/^sarvam-105b(?:-conversations)?$/);
    return Response.json({choices:[{message:{content:JSON.stringify(triage)+'\nअभी 112 से सहायता लें।'}}]});
  });
  for (const model of ['sarvam-105b-conversations','sarvam-105b']) {
    const response=await onRequest({request:request({model,message:'सीने में दर्द है'}),env});
    assert.equal(response.status,200);
    const body=await response.json();
    assert.deepEqual(body.triage_json,triage);
    assert.equal(body.parse_succeeded,true);
  }
});

test('Gemini accepts alias and joins visible text parts', async t => {
  t.mock.method(globalThis,'fetch',async url => {
    assert.ok(url.includes('key=test-google'));
    return Response.json({candidates:[{content:{parts:[{text:'hidden',thought:true},{text:JSON.stringify(triage)},{text:'\nअभी सहायता लें'}]}}]});
  });
  const response=await onRequest({request:request({model:'gemini-2.5-pro',message:'test'}),env});
  const body=await response.json();
  assert.equal(body.parse_succeeded,true);
  assert.ok(!body.response.includes('hidden'));
});

test('upstream errors do not expose credentials', async t => {
  t.mock.method(globalThis,'fetch',async () => new Response('secret-key-value',{status:401}));
  const response=await onRequest({request:request({model:'sarvam-105b',message:'test'}),env});
  assert.equal(response.status,500);
  assert.ok(!(await response.text()).includes('secret-key-value'));
});

test('invalid red flag types fail schema parsing', async t => {
  t.mock.method(globalThis,'fetch',async () => Response.json({choices:[{message:{content:JSON.stringify({...triage,red_flags_detected:[42]})}}]}));
  const response=await onRequest({request:request({model:'sarvam-105b',message:'test'}),env});
  assert.equal((await response.json()).parse_succeeded,false);
});
