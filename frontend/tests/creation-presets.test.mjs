import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildCreationPrompt, creationInputError } from '../src/lib/creation-presets.ts'

const defaults = { mode: 'text', template: 'free', style: 'auto', language: 'auto' }

test('free creation preserves the original description without adding instructions', () => {
  assert.equal(buildCreationPrompt('  一座城市\n云海之上  ', defaults), '一座城市\n云海之上')
  assert.equal(buildCreationPrompt('  ', { ...defaults, template: 'workflow' }), '')
})

test('template, style and image language are independently composed without mutating the description', () => {
  const description = '标题为“样本分析”，展示三个步骤。'
  const prompt = buildCreationPrompt(description, { ...defaults, template: 'workflow', style: 'flat', language: 'en' })
  assert.ok(prompt.startsWith(description + '\n\n'))
  assert.match(prompt, /科研工作流/)
  assert.match(prompt, /扁平插画/)
  assert.match(prompt, /图中文字语言：英语/)
  assert.equal(buildCreationPrompt(description, defaults), description)
})

test('editing skips the creation template and asks to retain the rest of the source image', () => {
  const prompt = buildCreationPrompt('把标题改成蓝色', { ...defaults, mode: 'edit', template: 'poster' })
  assert.match(prompt, /保留未提及部分/)
  assert.doesNotMatch(prompt, /海报或封面/)
})

test('reference and edit modes require an image, while text mode does not', () => {
  assert.match(creationInputError('reference', '描述', '描述', 0, 4000), /选择参考图/)
  assert.match(creationInputError('edit', '修改', '修改', 0, 4000), /要修改的图片/)
  assert.equal(creationInputError('text', '描述', '描述', 0, 4000), '')
  assert.equal(creationInputError('edit', '修改', '修改', 1, 4000), '')
})

test('validation counts the complete prompt and rejects empty descriptions even with presets', () => {
  const prompt = buildCreationPrompt('步骤', { ...defaults, template: 'workflow' })
  assert.match(creationInputError('text', '步骤', prompt, 0, prompt.length - 1), /加入预设后/)
  assert.equal(creationInputError('text', '步骤', prompt, 0, prompt.length), '')
  assert.match(creationInputError('edit', '', '', 1, 4000), /修改的内容/)
})
