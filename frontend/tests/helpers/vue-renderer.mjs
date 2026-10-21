import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
import { parse, compileScript } from '@vue/compiler-sfc'
import * as vue from 'vue'

export function compileComponent(filename, modules, environment = {}) {
  const { descriptor } = parse(fs.readFileSync(filename, 'utf8'), { filename: filename.pathname })
  const script = compileScript(descriptor, { id: 'component-test', inlineTemplate: true })
  const compiled = ts.transpileModule(script.content, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
  const context = { exports: {}, require: name => { assert.ok(modules[name], name); return modules[name] }, ...environment }
  vm.runInNewContext(compiled, context)
  return context.exports.default
}

export function node(tag = '', text = '') {
  return { tag, tagName: tag.toUpperCase(), text, props: {}, children: [], parent: null, listeners: {},
    addEventListener(event, handler) { this.listeners[event] = handler },
    removeEventListener(event) { delete this.listeners[event] },
    focus() { this.focused = true },
    scrollIntoView() {},
    get options() { return this.children.filter(child => child.tag === 'option') },
  }
}
export const teleportTarget = node('body')
export const renderer = vue.createRenderer({
  querySelector: selector => { assert.equal(selector, 'body'); return teleportTarget },
  createElement: tag => node(tag), createText: text => node('', text), createComment: () => node(),
  setText: (item, text) => { item.text = text },
  setElementText: (item, text) => { item.children = []; item.text = text },
  patchProp: (item, key, _, value) => { item.props[key] = value; if (key === 'value') item.value = item._value = value },
  insert(item, parent, anchor = null) {
    if (item.parent) item.parent.children.splice(item.parent.children.indexOf(item), 1)
    const index = anchor ? parent.children.indexOf(anchor) : -1
    parent.children.splice(index < 0 ? parent.children.length : index, 0, item)
    item.parent = parent
  },
  remove(item) { if (item.parent) item.parent.children.splice(item.parent.children.indexOf(item), 1) },
  parentNode: item => item.parent,
  nextSibling: item => item.parent?.children[item.parent.children.indexOf(item) + 1] ?? null,
})
export const all = root => [root, ...root.children.flatMap(all)]
export const hasClass = (item, name) => String(item.props.class ?? '').split(' ').includes(name)
export const textOf = item => item.text + item.children.map(textOf).join('')
