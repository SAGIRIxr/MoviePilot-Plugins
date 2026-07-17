<script setup>
import { ref, reactive, computed, onMounted } from 'vue'

const props = defineProps({
  initialConfig: { type: Object, default: () => ({}) },
  api: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['save', 'close', 'switch'])

const PLUGIN_ID = 'DiscordMsgForward'

function defaultRule() {
  return {
    id: Math.random().toString(36).slice(2, 10),
    name: '',
    enabled: true,
    channels: [],
    notify_channels: [],
    keywords: '',
    blocked_keywords: '',
    author_include: '',
    author_exclude: '',
    code_regex: '',
    aggregate: true,
    forward_image: true,
    quiet_hours: '',
    title_template: '',
    text_template: '',
  }
}

const config = reactive({
  enabled: false,
  token: '',
  use_proxy: true,
  interval: 5,
  msgtype: 'Plugin',
  fail_alert: true,
  history_days: 30,
  ...props.initialConfig,
  rules: (props.initialConfig?.rules || []).map(r => ({ ...defaultRule(), ...r })),
})

const channelOptions = ref([])
const notifierOptions = ref([])
const msgtypeOptions = ref([])
const loadingChannels = ref(false)
const showToken = ref(false)
const message = ref('')
const messageType = ref('info')

// 规则编辑弹窗
const dialog = ref(false)
const editIndex = ref(-1)
const editRule = ref(defaultRule())

// 删除确认
const deleteDialog = ref(false)
const deleteIndex = ref(-1)

const channelNameMap = computed(() => {
  const map = {}
  channelOptions.value.forEach(o => { map[o.value] = o.title })
  return map
})

function channelName(cid) {
  return channelNameMap.value[cid] || cid
}

function showMessage(text, type = 'info') {
  message.value = text
  messageType.value = type
  setTimeout(() => { message.value = '' }, 4000)
}

async function loadOptions() {
  try {
    const [notifiers, msgtypes] = await Promise.all([
      props.api.get(`plugin/${PLUGIN_ID}/notifiers`),
      props.api.get(`plugin/${PLUGIN_ID}/msgtypes`),
    ])
    notifierOptions.value = notifiers?.options || []
    msgtypeOptions.value = msgtypes?.options || []
  } catch (e) {
    console.error('加载选项失败', e)
  }
}

async function loadChannels(refresh = false) {
  loadingChannels.value = true
  try {
    const res = await props.api.get(`plugin/${PLUGIN_ID}/channels`, { params: { refresh } })
    channelOptions.value = res?.options || []
    if (refresh) {
      showMessage(`已刷新，共 ${channelOptions.value.length} 个频道`, 'success')
    }
  } catch (e) {
    console.error('加载频道失败', e)
    if (refresh) showMessage('刷新频道列表失败，请检查 Token 和代理', 'error')
  } finally {
    loadingChannels.value = false
  }
}

function addRule() {
  editIndex.value = -1
  editRule.value = defaultRule()
  dialog.value = true
}

function openRule(index) {
  editIndex.value = index
  editRule.value = JSON.parse(JSON.stringify(config.rules[index]))
  dialog.value = true
}

function confirmRule() {
  if (!editRule.value.name) {
    editRule.value.name = `规则 ${config.rules.length + 1}`
  }
  if (editIndex.value >= 0) {
    config.rules.splice(editIndex.value, 1, JSON.parse(JSON.stringify(editRule.value)))
  } else {
    config.rules.push(JSON.parse(JSON.stringify(editRule.value)))
  }
  dialog.value = false
}

function askDelete(index) {
  deleteIndex.value = index
  deleteDialog.value = true
}

function confirmDelete() {
  if (deleteIndex.value >= 0) {
    config.rules.splice(deleteIndex.value, 1)
  }
  deleteDialog.value = false
  deleteIndex.value = -1
}

function ruleFilterSummary(rule) {
  const parts = []
  if (rule.keywords) parts.push(`关键词:${rule.keywords}`)
  if (rule.blocked_keywords) parts.push(`屏蔽:${rule.blocked_keywords}`)
  if (rule.author_include) parts.push(`作者:${rule.author_include}`)
  if (rule.author_exclude) parts.push(`排除作者:${rule.author_exclude}`)
  if (rule.code_regex) parts.push('提取正则')
  return parts.join('　')
}

function saveConfig() {
  if (!config.token) {
    showMessage('请填写 Bot Token', 'error')
    return
  }
  emit('save', JSON.parse(JSON.stringify(config)))
}

onMounted(() => {
  loadOptions()
  loadChannels(false)
})
</script>

<template>
  <div class="plugin-config">
    <v-alert v-if="message" :type="messageType" variant="tonal" density="compact" class="mb-3">
      {{ message }}
    </v-alert>

    <!-- 全局设置 -->
    <v-card class="mb-4">
      <v-card-title class="d-flex align-center">
        <v-icon color="info" class="mr-2">mdi-cog</v-icon>
        全局设置
      </v-card-title>
      <v-divider />
      <v-card-text>
        <v-row dense>
          <v-col cols="12" md="3">
            <v-switch v-model="config.enabled" label="启用插件" color="primary" hide-details />
          </v-col>
          <v-col cols="12" md="3">
            <v-switch v-model="config.use_proxy" label="使用系统代理" color="warning" hide-details />
          </v-col>
          <v-col cols="12" md="3">
            <v-switch v-model="config.fail_alert" label="失败告警" color="error" hide-details />
          </v-col>
          <v-col cols="12" md="3">
            <v-text-field
              v-model.number="config.interval" label="轮询间隔(分钟)" type="number"
              density="compact" variant="outlined" prepend-inner-icon="mdi-timer-outline" hide-details
            />
          </v-col>
        </v-row>
        <v-row dense class="mt-2">
          <v-col cols="12" md="6">
            <v-text-field
              v-model="config.token" label="Bot Token"
              :type="showToken ? 'text' : 'password'"
              :append-inner-icon="showToken ? 'mdi-eye-off' : 'mdi-eye'"
              density="compact" variant="outlined" prepend-inner-icon="mdi-key"
              hint="保存后自动拉取 Bot 可见频道列表" persistent-hint
              autocomplete="new-password"
              @click:append-inner="showToken = !showToken"
            />
          </v-col>
          <v-col cols="12" md="3">
            <v-select
              v-model="config.msgtype" label="通知类型" :items="msgtypeOptions"
              item-title="title" item-value="value"
              density="compact" variant="outlined" prepend-inner-icon="mdi-bell-outline"
              hint="所选通知渠道需开启该类型开关" persistent-hint
            />
          </v-col>
          <v-col cols="12" md="3">
            <v-text-field
              v-model.number="config.history_days" label="历史保留天数" type="number"
              density="compact" variant="outlined" prepend-inner-icon="mdi-history" hide-details
            />
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>

    <!-- 转发规则 -->
    <v-card class="mb-4">
      <v-card-title class="d-flex align-center">
        <v-icon color="info" class="mr-2">mdi-swap-horizontal</v-icon>
        转发规则
        <v-spacer />
        <v-btn
          size="small" variant="tonal" color="info" class="mr-2"
          :loading="loadingChannels" prepend-icon="mdi-refresh"
          @click="loadChannels(true)"
        >
          刷新频道列表
        </v-btn>
        <v-btn size="small" color="primary" prepend-icon="mdi-plus" @click="addRule">
          添加规则
        </v-btn>
      </v-card-title>
      <v-divider />
      <v-card-text>
        <v-alert v-if="!config.rules.length" type="info" variant="tonal">
          还没有转发规则，点击右上角「添加规则」创建第一条：选择监听频道和转发渠道即可。
        </v-alert>
        <v-row v-else dense>
          <v-col v-for="(rule, index) in config.rules" :key="rule.id" cols="12" md="6" lg="4">
            <v-card variant="tonal" :color="rule.enabled ? 'primary' : undefined" class="rule-card">
              <v-card-item>
                <template #prepend>
                  <v-icon :color="rule.enabled ? 'primary' : 'grey'">
                    {{ rule.enabled ? 'mdi-send-circle' : 'mdi-send-lock' }}
                  </v-icon>
                </template>
                <v-card-title class="text-subtitle-1">{{ rule.name || '未命名规则' }}</v-card-title>
                <template #append>
                  <v-switch
                    v-model="rule.enabled" color="primary" density="compact" hide-details
                    @click.stop
                  />
                </template>
              </v-card-item>
              <v-card-text class="pt-0">
                <div class="mb-1">
                  <v-chip
                    v-for="cid in rule.channels.slice(0, 3)" :key="cid"
                    size="x-small" variant="outlined" class="mr-1 mb-1"
                  >
                    {{ channelName(cid) }}
                  </v-chip>
                  <v-chip v-if="rule.channels.length > 3" size="x-small" variant="text" class="mb-1">
                    +{{ rule.channels.length - 3 }}
                  </v-chip>
                  <v-chip v-if="!rule.channels.length" size="x-small" color="warning" variant="tonal" class="mb-1">
                    未选频道
                  </v-chip>
                </div>
                <div class="text-caption mb-1">
                  <v-icon size="x-small" class="mr-1">mdi-send</v-icon>
                  {{ rule.notify_channels.length ? rule.notify_channels.join('、') : '全部渠道' }}
                  <v-icon v-if="rule.quiet_hours" size="x-small" class="ml-2 mr-1">mdi-sleep</v-icon>
                  <span v-if="rule.quiet_hours">{{ rule.quiet_hours }}</span>
                </div>
                <div v-if="ruleFilterSummary(rule)" class="text-caption text-truncate">
                  <v-icon size="x-small" class="mr-1">mdi-filter</v-icon>
                  {{ ruleFilterSummary(rule) }}
                </div>
              </v-card-text>
              <v-card-actions class="pt-0">
                <v-spacer />
                <v-btn size="small" variant="text" prepend-icon="mdi-pencil" @click="openRule(index)">
                  编辑
                </v-btn>
                <v-btn size="small" variant="text" color="error" prepend-icon="mdi-delete" @click="askDelete(index)">
                  删除
                </v-btn>
              </v-card-actions>
            </v-card>
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>

    <!-- 操作按钮 -->
    <div class="d-flex">
      <v-spacer />
      <v-btn class="mr-2" variant="text" @click="emit('switch')">详情页</v-btn>
      <v-btn class="mr-2" variant="text" @click="emit('close')">关闭</v-btn>
      <v-btn color="primary" prepend-icon="mdi-content-save" @click="saveConfig">保存配置</v-btn>
    </div>

    <!-- 规则编辑弹窗 -->
    <v-dialog v-model="dialog" max-width="800" scrollable>
      <v-card>
        <v-card-title class="d-flex align-center">
          <v-icon color="info" class="mr-2">{{ editIndex >= 0 ? 'mdi-pencil' : 'mdi-plus' }}</v-icon>
          {{ editIndex >= 0 ? '编辑规则' : '添加规则' }}
          <v-spacer />
          <v-switch v-model="editRule.enabled" label="启用" color="primary" density="compact" hide-details />
        </v-card-title>
        <v-divider />
        <v-card-text>
          <v-row dense>
            <v-col cols="12" md="6">
              <v-text-field
                v-model="editRule.name" label="规则名称" placeholder="如：WOS 礼包码"
                density="compact" variant="outlined" prepend-inner-icon="mdi-tag"
              />
            </v-col>
            <v-col cols="12" md="6">
              <v-text-field
                v-model="editRule.quiet_hours" label="免打扰时段（可选）" placeholder="23:00-08:00，留空不启用"
                density="compact" variant="outlined" prepend-inner-icon="mdi-sleep"
                hint="时段内消息暂存，结束后汇总推送" persistent-hint
              />
            </v-col>
          </v-row>
          <v-row dense>
            <v-col cols="12">
              <v-select
                v-model="editRule.channels" label="监听频道" :items="channelOptions"
                item-title="title" item-value="value"
                multiple chips closable-chips clearable
                density="compact" variant="outlined" prepend-inner-icon="mdi-pound"
                :loading="loadingChannels"
                no-data-text="暂无频道：请先在全局设置填写 Token 并保存，或点击「刷新频道列表」"
              />
            </v-col>
          </v-row>
          <v-row dense>
            <v-col cols="12">
              <v-select
                v-model="editRule.notify_channels" label="转发渠道" :items="notifierOptions"
                item-title="title" item-value="value"
                multiple chips closable-chips clearable
                density="compact" variant="outlined" prepend-inner-icon="mdi-send-circle"
                hint="留空 = 发送到全部启用的通知渠道" persistent-hint
              />
            </v-col>
          </v-row>
          <v-row dense>
            <v-col cols="12" md="3">
              <v-switch v-model="editRule.aggregate" label="消息聚合" color="info" density="compact" hide-details />
            </v-col>
            <v-col cols="12" md="3">
              <v-switch v-model="editRule.forward_image" label="图片转发" color="info" density="compact" hide-details />
            </v-col>
          </v-row>

          <v-expansion-panels variant="accordion" class="mt-2">
            <v-expansion-panel>
              <v-expansion-panel-title>
                <v-icon size="small" class="mr-2">mdi-filter</v-icon>
                过滤规则（可选，留空全部转发）
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <v-row dense>
                  <v-col cols="12" md="6">
                    <v-text-field
                      v-model="editRule.keywords" label="关键词（白名单）"
                      placeholder="含任一关键词才转发，逗号或 | 分隔"
                      density="compact" variant="outlined" prepend-inner-icon="mdi-text-search"
                    />
                  </v-col>
                  <v-col cols="12" md="6">
                    <v-text-field
                      v-model="editRule.blocked_keywords" label="屏蔽词（黑名单）"
                      placeholder="含任一屏蔽词不转发"
                      density="compact" variant="outlined" prepend-inner-icon="mdi-text-box-remove"
                    />
                  </v-col>
                  <v-col cols="12" md="6">
                    <v-text-field
                      v-model="editRule.author_include" label="只转发这些作者"
                      placeholder="用户名精确匹配，不分大小写"
                      density="compact" variant="outlined" prepend-inner-icon="mdi-account-check"
                    />
                  </v-col>
                  <v-col cols="12" md="6">
                    <v-text-field
                      v-model="editRule.author_exclude" label="屏蔽这些作者"
                      placeholder="用户名精确匹配，不分大小写"
                      density="compact" variant="outlined" prepend-inner-icon="mdi-account-cancel"
                    />
                  </v-col>
                </v-row>
              </v-expansion-panel-text>
            </v-expansion-panel>
            <v-expansion-panel>
              <v-expansion-panel-title>
                <v-icon size="small" class="mr-2">mdi-tune</v-icon>
                高级选项（可选，默认即可）
              </v-expansion-panel-title>
              <v-expansion-panel-text>
                <v-row dense>
                  <v-col cols="12">
                    <v-text-field
                      v-model="editRule.code_regex" label="内容提取正则（如礼包码）"
                      placeholder="如：[A-Za-z0-9]{6,20}，留空不提取"
                      density="compact" variant="outlined" prepend-inner-icon="mdi-regex"
                      hint="命中内容在通知中单独列出，对应模板变量 {codes}" persistent-hint
                    />
                  </v-col>
                  <v-col cols="12" md="5">
                    <v-text-field
                      v-model="editRule.title_template" label="标题模板"
                      placeholder="【Discord | {channel}】"
                      density="compact" variant="outlined" prepend-inner-icon="mdi-format-title"
                    />
                  </v-col>
                  <v-col cols="12" md="7">
                    <v-textarea
                      v-model="editRule.text_template" label="内容模板" rows="3"
                      placeholder="{content}\n\n🎁 提取内容：{codes}\n\n👤 {author}  🕐 {time}"
                      density="compact" variant="outlined" prepend-inner-icon="mdi-text"
                      hint="变量：{channel} {author} {content} {codes} {time} {count}；提取内容为空时含 {codes} 的行自动隐藏" persistent-hint
                    />
                  </v-col>
                </v-row>
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>
        </v-card-text>
        <v-divider />
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="dialog = false">取消</v-btn>
          <v-btn color="primary" @click="confirmRule">确定</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 删除确认弹窗 -->
    <v-dialog v-model="deleteDialog" max-width="360">
      <v-card>
        <v-card-title>删除规则</v-card-title>
        <v-card-text>
          确定删除规则「{{ deleteIndex >= 0 && config.rules[deleteIndex] ? config.rules[deleteIndex].name || '未命名规则' : '' }}」吗？
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="deleteDialog = false">取消</v-btn>
          <v-btn color="error" @click="confirmDelete">删除</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<style scoped>
.rule-card {
  height: 100%;
}
</style>
