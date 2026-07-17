<script setup>
import { ref, onMounted } from 'vue'

const props = defineProps({
  api: { type: Object, default: () => ({}) },
})

const emit = defineEmits(['action', 'switch', 'close'])

const PLUGIN_ID = 'DiscordMsgForward'

const status = ref(null)
const history = ref([])
const loading = ref(false)
const checking = ref(false)
const message = ref('')
const messageType = ref('info')
const clearDialog = ref(false)

function showMessage(text, type = 'info') {
  message.value = text
  messageType.value = type
  setTimeout(() => { message.value = '' }, 4000)
}

async function loadData() {
  loading.value = true
  try {
    const [st, hi] = await Promise.all([
      props.api.get(`plugin/${PLUGIN_ID}/status`),
      props.api.get(`plugin/${PLUGIN_ID}/history`),
    ])
    status.value = st || null
    history.value = hi?.history || []
  } catch (e) {
    console.error('加载数据失败', e)
  } finally {
    loading.value = false
  }
}

async function checkNow() {
  checking.value = true
  try {
    const res = await props.api.post(`plugin/${PLUGIN_ID}/check`)
    showMessage(res?.message || '已触发检查', 'success')
    setTimeout(loadData, 5000)
  } catch (e) {
    showMessage('触发检查失败', 'error')
  } finally {
    checking.value = false
  }
}

async function clearHistory() {
  clearDialog.value = false
  try {
    await props.api.delete(`plugin/${PLUGIN_ID}/history`)
    showMessage('已清空历史', 'success')
    loadData()
  } catch (e) {
    showMessage('清空失败', 'error')
  }
}

onMounted(loadData)
</script>

<template>
  <div class="plugin-page">
    <v-alert v-if="message" :type="messageType" variant="tonal" density="compact" class="mb-3">
      {{ message }}
    </v-alert>

    <!-- 状态卡片 -->
    <v-card class="mb-4">
      <v-card-title class="d-flex align-center">
        <v-icon color="info" class="mr-2">mdi-monitor-dashboard</v-icon>
        运行状态
        <v-spacer />
        <v-btn
          size="small" variant="tonal" color="success" class="mr-2"
          :loading="checking" prepend-icon="mdi-play" @click="checkNow"
        >
          立即检查
        </v-btn>
        <v-btn
          size="small" variant="tonal" color="info" class="mr-2"
          :loading="loading" prepend-icon="mdi-refresh" @click="loadData"
        >
          刷新
        </v-btn>
        <v-btn size="small" variant="text" prepend-icon="mdi-cog" @click="emit('switch')">
          配置
        </v-btn>
      </v-card-title>
      <v-divider />
      <v-card-text v-if="status">
        <v-row dense>
          <v-col cols="6" md="3">
            <div class="text-caption">插件状态</div>
            <v-chip :color="status.enabled ? 'success' : 'grey'" size="small" variant="tonal">
              {{ status.enabled ? '已启用' : '未启用' }}
            </v-chip>
          </v-col>
          <v-col cols="6" md="3">
            <div class="text-caption">转发规则</div>
            <span class="text-h6">{{ status.rules_enabled }}</span>
            <span class="text-caption"> / {{ status.rules_total }} 条启用</span>
          </v-col>
          <v-col cols="6" md="3">
            <div class="text-caption">免打扰暂存</div>
            <span class="text-h6">{{ status.pending_count }}</span>
            <span class="text-caption"> 条待推送</span>
          </v-col>
          <v-col cols="6" md="3">
            <div class="text-caption">Bot Token</div>
            <v-chip :color="status.token_set ? 'success' : 'error'" size="small" variant="tonal">
              {{ status.token_set ? '已配置' : '未配置' }}
            </v-chip>
          </v-col>
        </v-row>
        <v-alert
          v-if="status.fail_streak > 0" type="warning" variant="tonal" density="compact" class="mt-3"
        >
          已连续 {{ status.fail_streak }} 次轮询失败{{ status.last_error ? `：${status.last_error}` : '' }}
        </v-alert>
      </v-card-text>
    </v-card>

    <!-- 历史记录 -->
    <v-card>
      <v-card-title class="d-flex align-center">
        <v-icon color="info" class="mr-2">mdi-history</v-icon>
        转发历史
        <v-spacer />
        <v-btn
          v-if="history.length" size="small" variant="text" color="error"
          prepend-icon="mdi-delete-sweep" @click="clearDialog = true"
        >
          清空
        </v-btn>
      </v-card-title>
      <v-divider />
      <v-card-text>
        <v-alert v-if="!history.length" type="info" variant="tonal">
          暂无转发记录
        </v-alert>
        <v-table v-else hover density="compact">
          <thead>
            <tr>
              <th class="text-start">时间</th>
              <th class="text-start">规则</th>
              <th class="text-start">频道</th>
              <th class="text-start">发送者</th>
              <th class="text-start">内容</th>
              <th class="text-start">条数</th>
              <th class="text-start">提取内容</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(h, i) in history" :key="i">
              <td class="text-no-wrap">{{ h.date }}</td>
              <td class="text-no-wrap">{{ h.rule || '-' }}</td>
              <td>{{ h.channel }}</td>
              <td class="text-no-wrap">{{ h.author }}</td>
              <td class="content-cell">{{ h.content }}</td>
              <td>{{ h.count || 1 }}</td>
              <td>
                <v-chip v-if="h.codes" color="success" size="small" variant="tonal">{{ h.codes }}</v-chip>
                <span v-else>-</span>
              </td>
            </tr>
          </tbody>
        </v-table>
      </v-card-text>
    </v-card>

    <div class="d-flex mt-4">
      <v-spacer />
      <v-btn variant="text" @click="emit('close')">关闭</v-btn>
    </div>

    <!-- 清空确认 -->
    <v-dialog v-model="clearDialog" max-width="360">
      <v-card>
        <v-card-title>清空历史</v-card-title>
        <v-card-text>确定清空全部转发历史记录吗？此操作不可恢复。</v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="clearDialog = false">取消</v-btn>
          <v-btn color="error" @click="clearHistory">清空</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<style scoped>
.content-cell {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
