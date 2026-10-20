// Creation-page presets are prompt instructions, not additional model capabilities.
export type CreationMode = 'text' | 'reference' | 'edit'

export const creationTemplates = [
  { id: 'free', label: '自由创作', detail: '从一句描述开始', instruction: '', example: '一座漂浮在云海上的城市，黄昏光线，丰富的建筑细节。' },
  { id: 'workflow', label: '科研工作流', detail: '清楚展示实验步骤', instruction: '使用科研工作流的构图，明确区分步骤，按逻辑顺序排列，用箭头表达流程，保持标注清晰。', example: '绘制一张实验工作流示意图，依次展示样本采集、样本处理和结果分析，横向排列，白色背景。' },
  { id: 'mechanism', label: '机制示意图', detail: '表达元素之间的关系', instruction: '使用机制示意图的构图，突出核心对象，用清晰的箭头和分组表达作用关系，统一标注层级。', example: '绘制植物光合作用示意图，展示阳光、水和二氧化碳进入叶片，以及氧气和有机物的产生，用箭头标明关系。' },
  { id: 'poster', label: '海报与封面', detail: '安排主题与文字层级', instruction: '采用海报或封面的构图，突出主题，合理留白，为标题和必要的信息安排清晰的视觉层级。', example: '制作一张读书分享会海报，标题为“在文字里相遇”，时间为“周六 14:00”，温暖的阅读氛围。' },
  { id: 'product', label: '产品展示', detail: '突出产品与使用场景', instruction: '采用产品展示的构图，突出产品主体，保持材质与比例自然，让环境和光线服务于产品展示。', example: '一只白色陶瓷杯放在木质书桌上，旁边有翻开的书，柔和的晨间自然光，突出陶瓷的质感。' },
] as const

export const creationStyles = [
  { id: 'auto', label: '由描述决定', instruction: '' },
  { id: 'flat', label: '扁平插画', instruction: '视觉风格：扁平插画，形状简洁，配色统一，边缘清晰。' },
  { id: 'scientific', label: '科学插画', instruction: '视觉风格：清晰的科学插画，结构明确，配色克制，标注易读。' },
  { id: 'photo', label: '写实摄影', instruction: '视觉风格：写实摄影，自然的材质、光线与空间关系。' },
  { id: 'isometric', label: '等轴测 3D', instruction: '视觉风格：等轴测 3D 插画，统一视角，立体结构清晰。' },
] as const

export const creationLanguages = [
  { id: 'auto', label: '跟随描述', instruction: '' },
  { id: 'zh', label: '简体中文', instruction: '图中文字语言：简体中文。按描述准确呈现需要的文字和标注。' },
  { id: 'en', label: 'English', instruction: '图中文字语言：英语。按描述准确呈现需要的文字和标注。' },
] as const

export function buildCreationPrompt(description: string, options: {
  mode: CreationMode
  template: string
  style: string
  language: string
}): string {
  if (!description.trim()) return ''
  return [
    description.trim(),
    options.mode === 'edit'
      ? '根据参考图执行以上修改要求，尽量保留未提及部分的内容与布局。'
      : creationTemplates.find(item => item.id === options.template)?.instruction,
    creationStyles.find(item => item.id === options.style)?.instruction,
    creationLanguages.find(item => item.id === options.language)?.instruction,
  ].filter(Boolean).join('\n\n')
}

export function creationInputError(mode: CreationMode, description: string, finalPrompt: string, referenceCount: number, maxLength: number): string {
  if (!description.trim()) return mode === 'edit' ? '请写下想修改的内容。' : '先写下一句你想看到的画面吧。'
  if (mode !== 'text' && referenceCount === 0) return mode === 'edit' ? '请先上传或选择要修改的图片。' : '请先上传或选择参考图。'
  if (finalPrompt.length > maxLength) return `加入预设后的提示词超过 ${maxLength} 字，请缩短描述或减少预设。`
  return ''
}
