const test = require('node:test');
const assert = require('node:assert/strict');
const { VoiceSession } = require('../static/voice.js');

function setup(value = '', start = value.length, end = start, maxLength = 6000) {
  const input = { value, selectionStart: start, selectionEnd: end, maxLength,
    isConnected: true, readOnly: false, events: [],
    setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; },
    dispatchEvent(event) { this.events.push(event.type); }
  };
  const states = [], messages = [], instances = [];
  class Recognition {
    constructor() { instances.push(this); }
    start() { this.onstart(); }
    stop() { this.stopped = true; }
    abort() { this.aborted = true; }
    result(...segments) { this.onresult({ results: segments.map(transcript => [{ transcript }]) }); }
    end() { this.onend(); }
    error(error) { this.onerror({ error }); }
  }
  const session = new VoiceSession({ input, Recognition,
    onState: state => states.push(state), onMessage: text => messages.push(text) });
  return { input, session, states, messages, instances, Recognition };
}

test('dictation inserts at the selection and leaves surrounding text intact', () => {
  const { session, input, instances } = setup('之前旧内容之后', 2, 5);
  session.start(); instances[0].result('新讲解');
  assert.equal(input.value, '之前新讲解之后');
  assert.equal(input.selectionStart, 5);
});

test('interim revisions replace previous interim text instead of duplicating it', () => {
  const { session, input, instances } = setup('我理解：');
  session.start(); const recognition = instances[0];
  recognition.result('线性'); recognition.result('线性回归');
  recognition.result('线性回归', '会学习参数');
  assert.equal(input.value, '我理解：线性回归会学习参数');
  assert.deepEqual(input.events, ['input', 'input', 'input']);
});

test('stopping waits for the final result and preserves it for editing', () => {
  const { session, input, instances } = setup();
  session.start(); const recognition = instances[0];
  recognition.result('中间结果'); session.stop();
  assert.equal(recognition.stopped, true);
  assert.equal(input.readOnly, true);
  recognition.result('最后确认的结果'); recognition.end();
  assert.equal(input.value, '最后确认的结果');
  assert.equal(input.readOnly, false);
  assert.equal(session.state, 'idle');
});

test('dictation only emits input events and never submits a form', () => {
  const { session, input, instances } = setup();
  session.start(); instances[0].result('讲授内容'); instances[0].end();
  assert.deepEqual(input.events, ['input']);
});

test('maxLength accounts for existing text and does not split emoji', () => {
  const { session, input, instances, messages } = setup('前后', 1, 1, 5);
  session.start(); instances[0].result('好😀多余'); instances[0].result('好😀更多文字');
  assert.equal(input.value, '前好😀后');
  assert.equal(messages.length, 1);
});

test('microphone permission failure restores editing and retains recognized text', () => {
  const { session, input, instances, messages } = setup('已有文字');
  session.start(); instances[0].result('新增'); instances[0].error('not-allowed');
  assert.equal(input.value, '已有文字新增');
  assert.equal(input.readOnly, false);
  assert.equal(session.state, 'idle');
  assert.equal(instances[0].aborted, true);
  assert.match(messages[0], /麦克风权限/);
});

test('late recognition results cannot modify a field after cancellation', () => {
  const { session, input, instances } = setup('原文');
  session.start(); session.abort(); instances[0].result('迟到的结果');
  assert.equal(input.value, '原文');
  assert.equal(input.readOnly, false);
  assert.equal(instances[0].aborted, true);
});

test('removed fields do not receive stale results', () => {
  const { session, input, instances } = setup('原文');
  session.start(); input.isConnected = false; instances[0].result('不应写入');
  session.abort();
  assert.equal(input.value, '原文');
});

test('synchronous browser start failure does not lock the input', () => {
  const { session, input, Recognition, messages } = setup();
  Recognition.prototype.start = () => { throw new Error('blocked'); };
  session.start();
  assert.equal(input.readOnly, false);
  assert.equal(session.state, 'idle');
  assert.equal(messages.length, 1);
});

test('constructor failure restores a usable idle state', () => {
  const { session, input, messages } = setup();
  session.Recognition = class { constructor() { throw new Error('unsupported'); } };
  session.start();
  assert.equal(input.readOnly, false);
  assert.equal(session.state, 'idle');
  assert.equal(messages.length, 1);
});
